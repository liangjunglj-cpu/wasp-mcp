using System;
using System.Drawing;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading.Tasks;
using GH_MCP_Wasp.Commands;
using GH_MCP_Wasp.Models;
using Grasshopper.Kernel;
using Newtonsoft.Json;
using Rhino;

namespace GH_MCP_Wasp
{
    /// <summary>
    /// Wasp MCP Bridge component. Runs a localhost TCP listener (default port
    /// 8090) that accepts one JSON command per connection and replies with a
    /// single JSON response, per PROTOCOL.md.
    ///
    /// Threading: the TCP listener and per-client handlers run on thread-pool
    /// threads and NEVER touch GH_Document. All canvas work is marshalled to
    /// the Rhino UI thread via UiSync.OnUi (TaskCompletionSource + 30 s timeout).
    /// </summary>
    public class WaspMCPComponent : GH_Component
    {
        private static TcpListener listener;
        private static bool isRunning = false;
        private static int waspPort = 8090;

        // Optional shared secret (PROTOCOL.md v0.5). Empty = open access
        // (backward compatible). Volatile: written by the UI thread in
        // SolveInstance, read by TCP worker threads in HandleClient.
        // NEVER written to logs or the Status/LastCommand outputs.
        private static volatile string authToken = string.Empty;

        // Explicit settings so another plugin mutating JsonConvert.DefaultSettings
        // in the shared Rhino process can't change our wire format.
        private static readonly JsonSerializerSettings WireSettings = new JsonSerializerSettings();

        public WaspMCPComponent()
            : base("Wasp MCP Bridge", "WaspMCP",
                   "TCP bridge that lets an MCP server place and wire Wasp components on the Grasshopper canvas",
                   "Params", "Util")
        {
        }

        protected override void RegisterInputParams(GH_Component.GH_InputParamManager pManager)
        {
            pManager.AddBooleanParameter("Enabled", "E", "Enable or disable the Wasp MCP bridge server", GH_ParamAccess.item, false);
            pManager.AddIntegerParameter("Port", "P", "Port to listen on (default 8090)", GH_ParamAccess.item, waspPort);
            // v0.5: optional shared secret. Non-empty = every request must
            // carry a matching top-level "token" field; empty/absent = open
            // access (backward compatible).
            pManager.AddTextParameter("Token", "T", "Optional shared secret; when set, every request must carry a matching top-level \"token\" field", GH_ParamAccess.item, string.Empty);
            pManager[2].Optional = true;
        }

        protected override void RegisterOutputParams(GH_Component.GH_OutputParamManager pManager)
        {
            pManager.AddTextParameter("Status", "S", "Server status", GH_ParamAccess.item);
            pManager.AddTextParameter("LastCommand", "C", "Last received command", GH_ParamAccess.item);
        }

        protected override void SolveInstance(IGH_DataAccess DA)
        {
            bool enabled = false;
            int port = waspPort;
            string token = string.Empty;

            if (!DA.GetData(0, ref enabled)) return;
            if (!DA.GetData(1, ref port)) return;
            // Optional input: absent data (e.g. component saved before v0.5)
            // simply leaves auth off. The token value itself must never reach
            // the Status/LastCommand outputs or the Rhino command line.
            if (!DA.GetData(2, ref token) || token == null) token = string.Empty;

            waspPort = port;
            authToken = token;

            // Status reports WHETHER auth is on, never the token value.
            string running = $"Running on port {waspPort}" + (authToken.Length > 0 ? " (auth on)" : "");

            if (enabled && !isRunning)
            {
                Start();
                DA.SetData(0, running);
            }
            else if (!enabled && isRunning)
            {
                Stop();
                DA.SetData(0, "Stopped");
            }
            else if (enabled && isRunning)
            {
                DA.SetData(0, running);
            }
            else
            {
                DA.SetData(0, "Stopped");
            }

            DA.SetData(1, LastCommand);
        }

        public override Guid ComponentGuid => new Guid("c4d70f76-1fdf-46c8-9f9b-c57e85c8cb90");

        protected override Bitmap Icon => null;

        public static string LastCommand { get; private set; } = "None";

        public static void Start()
        {
            if (isRunning) return;

            GrasshopperCommandRegistry.Initialize();

            isRunning = true;
            listener = new TcpListener(IPAddress.Loopback, waspPort);
            listener.Start();
            RhinoApp.WriteLine($"WaspMCP bridge started on port {waspPort}.");

            Task.Run(ListenerLoop);
        }

        public static void Stop()
        {
            if (!isRunning) return;

            isRunning = false;
            try { listener?.Stop(); } catch { }
            RhinoApp.WriteLine("WaspMCP bridge stopped.");
        }

        private static async Task ListenerLoop()
        {
            try
            {
                while (isRunning)
                {
                    var client = await listener.AcceptTcpClientAsync();
                    _ = Task.Run(() => HandleClient(client));
                }
            }
            catch (Exception ex)
            {
                if (isRunning)
                {
                    RhinoApp.WriteLine($"WaspMCP bridge error: {ex.Message}");
                    isRunning = false;
                }
            }
        }

        private static async Task HandleClient(TcpClient client)
        {
            using (client)
            using (var stream = client.GetStream())
            using (var reader = new StreamReader(stream, new UTF8Encoding(false)))
            using (var writer = new StreamWriter(stream, new UTF8Encoding(false)) { AutoFlush = true })
            {
                try
                {
                    // One newline-terminated JSON command per connection.
                    string commandJson = await reader.ReadLineAsync();
                    if (string.IsNullOrEmpty(commandJson))
                    {
                        return;
                    }

                    Command command = JsonConvert.DeserializeObject<Command>(commandJson, WireSettings);
                    if (command == null)
                    {
                        return;
                    }

                    // v0.5 shared-secret auth: when the component's Token
                    // input is non-empty, every request must carry a matching
                    // top-level "token". Missing/wrong token -> auth_failed
                    // and the connection is closed (the enclosing using
                    // blocks dispose the client). Constant response either
                    // way; the token value is never echoed or logged.
                    string requiredToken = authToken;
                    if (requiredToken.Length > 0 &&
                        !string.Equals(command.Token, requiredToken, StringComparison.Ordinal))
                    {
                        Response denied = Response.CreateError("auth_failed");
                        await writer.WriteLineAsync(JsonConvert.SerializeObject(denied, WireSettings));
                        RhinoApp.WriteLine("WaspMCP: rejected request (auth_failed).");
                        return;
                    }

                    // LastCommand feeds the component's status output: record
                    // a sanitized re-serialization (type + parameters only) so
                    // the token never appears there, rather than the raw wire
                    // text (which may carry "token").
                    LastCommand = JsonConvert.SerializeObject(
                        new { type = command.Type, parameters = command.Parameters }, WireSettings);

                    RhinoApp.WriteLine($"WaspMCP: Received command: {command.Type}");

                    // Executes on this worker thread; handlers marshal to the
                    // UI thread internally via UiSync.OnUi.
                    Response response = GrasshopperCommandRegistry.ExecuteCommand(command);

                    string responseJson = JsonConvert.SerializeObject(response, WireSettings);
                    await writer.WriteLineAsync(responseJson);

                    RhinoApp.WriteLine($"WaspMCP: Command {command.Type} -> {(response.Success ? "success" : "error: " + response.Error)}");
                }
                catch (Exception ex)
                {
                    RhinoApp.WriteLine($"WaspMCP: Error handling client: {ex.Message}");
                    try
                    {
                        Response errorResponse = Response.CreateError($"Server error: {ex.Message}");
                        string errorResponseJson = JsonConvert.SerializeObject(errorResponse, WireSettings);
                        await writer.WriteLineAsync(errorResponseJson);
                    }
                    catch { }
                }
            }
        }
    }
}
