using System;
using System.Drawing;
using Grasshopper.Kernel;

namespace GH_MCP_Wasp
{
    public class WaspMCPInfo : GH_AssemblyInfo
    {
        /// <summary>
        /// Bridge component/protocol version. Reported additively in the
        /// get_document_info and get_canvas_state results so clients can
        /// detect v0.2+/v0.3 capability without probing. Keep in sync with
        /// &lt;Version&gt; in GH_MCP_Wasp.csproj.
        /// </summary>
        public const string BridgeVersion = "0.5.0";

        public override string Name => "GH_MCP_Wasp";

        public override Bitmap Icon => null;

        public override string Description => "Wasp MCP Bridge - lets an MCP server place and wire Wasp components on a live Grasshopper canvas";

        public override Guid Id => new Guid("ce95b4df-c89e-4a7a-9622-e888fe025cf0");

        public override string AuthorName => "wasp-mcp";

        public override string AuthorContact => "";

        public override string AssemblyVersion => GetType().Assembly.GetName().Version.ToString();
    }
}
