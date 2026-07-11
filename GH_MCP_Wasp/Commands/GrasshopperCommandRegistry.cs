using System;
using System.Collections.Generic;
using System.Linq;
using GH_MCP_Wasp.Models;
using Rhino;

namespace GH_MCP_Wasp.Commands
{
    /// <summary>
    /// Command registry: maps wire command names to handlers.
    /// Handlers may return a plain object (wrapped in a success Response) or a
    /// Response instance (passed through verbatim, e.g. "solution_running").
    /// </summary>
    public static class GrasshopperCommandRegistry
    {
        private static readonly Dictionary<string, Func<Command, object>> CommandHandlers =
            new Dictionary<string, Func<Command, object>>();

        private static bool _initialized = false;

        public static void Initialize()
        {
            if (_initialized) return;
            _initialized = true;

            // Baseline geometry commands
            RegisterCommand("create_point", GeometryCommandHandler.CreatePoint);
            RegisterCommand("create_curve", GeometryCommandHandler.CreateCurve);
            RegisterCommand("create_circle", GeometryCommandHandler.CreateCircle);

            // Baseline component commands
            RegisterCommand("add_component", ComponentCommandHandler.AddComponent);
            RegisterCommand("connect_components", ConnectionCommandHandler.ConnectComponents);
            RegisterCommand("set_component_value", ComponentCommandHandler.SetComponentValue);
            RegisterCommand("get_component_info", ComponentCommandHandler.GetComponentInfo);
            RegisterCommand("get_all_components", ComponentCommandHandler.GetAllComponents);
            RegisterCommand("get_connections", ConnectionCommandHandler.GetConnections);
            RegisterCommand("search_components", ComponentCommandHandler.SearchComponents);
            RegisterCommand("get_component_parameters", ComponentCommandHandler.GetComponentParameters);
            RegisterCommand("validate_connection", ConnectionCommandHandler.ValidateConnection);

            // Baseline document commands
            RegisterCommand("get_document_info", DocumentCommandHandler.GetDocumentInfo);
            RegisterCommand("clear_document", DocumentCommandHandler.ClearDocument);
            RegisterCommand("save_document", DocumentCommandHandler.SaveDocument);
            RegisterCommand("load_document", DocumentCommandHandler.LoadDocument);

            // Baseline intent commands (kept, not extended)
            RegisterCommand("create_pattern", IntentCommandHandler.CreatePattern);
            RegisterCommand("get_available_patterns", IntentCommandHandler.GetAvailablePatterns);

            // Wasp MCP commands (PROTOCOL.md v0.1)
            RegisterCommand("add_user_object", WaspCommandHandler.AddUserObject);
            RegisterCommand("connect_by_name", WaspCommandHandler.ConnectByName);
            RegisterCommand("set_slider", WaspCommandHandler.SetSlider);
            RegisterCommand("set_panel", WaspCommandHandler.SetPanel);
            RegisterCommand("set_geometry_ref", WaspCommandHandler.SetGeometryRef);
            RegisterCommand("get_component_output", WaspCommandHandler.GetComponentOutput);
            RegisterCommand("get_canvas_state", WaspCommandHandler.GetCanvasState);
            RegisterCommand("expire_solution", WaspCommandHandler.ExpireSolution);
            RegisterCommand("bake_component_output", WaspCommandHandler.BakeComponentOutput);

            // Wasp MCP commands (PROTOCOL.md v0.2)
            RegisterCommand("set_plane_values", WaspCommandHandler.SetPlaneValues);
            RegisterCommand("set_toggle", WaspCommandHandler.SetToggle);
            RegisterCommand("delete_components", WaspCommandHandler.DeleteComponents);

            // Wasp MCP commands (PROTOCOL.md v0.3)
            RegisterCommand("wait_for_idle", WaspCommandHandler.WaitForIdle);
            RegisterCommand("list_component_types", ComponentCommandHandler.ListComponentTypes);
            RegisterCommand("get_component_schema", ComponentCommandHandler.GetComponentSchema);

            // Wasp MCP commands (PROTOCOL.md v0.4 — canvas organization)
            RegisterCommand("add_group", WaspCommandHandler.AddGroup);
            RegisterCommand("add_scribble", WaspCommandHandler.AddScribble);
            RegisterCommand("set_nickname", WaspCommandHandler.SetNickname);
            // Exploratory: registered so it answers "not_supported_yet"
            // instead of "Unknown command type" (a v0.4 bridge DOES know the
            // command; it deliberately declines it).
            RegisterCommand("create_cluster", WaspCommandHandler.CreateCluster);

            // Wasp MCP commands (PROTOCOL.md v0.5 — vision)
            RegisterCommand("capture_viewport", CaptureCommandHandler.CaptureViewport);
            RegisterCommand("capture_canvas", CaptureCommandHandler.CaptureCanvas);

            RhinoApp.WriteLine("WaspMCP: Command registry initialized.");
        }

        public static void RegisterCommand(string commandType, Func<Command, object> handler)
        {
            if (string.IsNullOrEmpty(commandType))
                throw new ArgumentNullException(nameof(commandType));

            if (handler == null)
                throw new ArgumentNullException(nameof(handler));

            CommandHandlers[commandType] = handler;
        }

        public static Response ExecuteCommand(Command command)
        {
            if (command == null)
            {
                return Response.CreateError("Command is null");
            }

            if (string.IsNullOrEmpty(command.Type))
            {
                return Response.CreateError("Command type is null or empty");
            }

            if (CommandHandlers.TryGetValue(command.Type, out var handler))
            {
                try
                {
                    var result = handler(command);

                    // Allow handlers to return a fully-formed Response
                    // (e.g. {"success": false, "error": "solution_running"}).
                    if (result is Response response)
                    {
                        return response;
                    }

                    return Response.Ok(result);
                }
                catch (Exception ex)
                {
                    RhinoApp.WriteLine($"WaspMCP: Error executing command '{command.Type}': {ex.Message}");
                    return Response.CreateError($"Error executing command '{command.Type}': {ex.Message}");
                }
            }

            // Exact prefix "Unknown command type" is load-bearing: the Python
            // server substring-matches it to detect bridge capability
            // (v0.2 probe/fallback, PROTOCOL.md "v0.2 commands").
            return Response.CreateError($"Unknown command type '{command.Type}'");
        }

        public static List<string> GetRegisteredCommandTypes()
        {
            return CommandHandlers.Keys.ToList();
        }
    }
}
