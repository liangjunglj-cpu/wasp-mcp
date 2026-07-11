using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using GH_MCP_Wasp.Models;
using GH_MCP_Wasp.Utils;
using Grasshopper.Kernel;

namespace GH_MCP_Wasp.Commands
{
    /// <summary>
    /// Baseline document commands. save_document/load_document are implemented
    /// for real here (the vendored baseline stubbed them out); save uses
    /// GH_Archive, load uses GH_DocumentIO.
    /// </summary>
    public static class DocumentCommandHandler
    {
        public static object GetDocumentInfo(Command command)
        {
            return UiSync.OnUi<object>(() =>
            {
                var doc = CanvasUtils.RequireDocument();

                var components = new List<object>();
                foreach (var obj in doc.Objects)
                {
                    components.Add(new Dictionary<string, object>
                    {
                        { "id", obj.InstanceGuid.ToString() },
                        { "type", obj.GetType().Name },
                        { "name", obj.NickName }
                    });
                }

                return new Dictionary<string, object>
                {
                    { "name", doc.DisplayName },
                    { "path", doc.FilePath },
                    { "componentCount", doc.Objects.Count },
                    { "components", components },
                    // Additive as of v0.2: lets clients detect bridge capability
                    // without probing (PROTOCOL.md "v0.2 commands").
                    { "version", WaspMCPInfo.BridgeVersion }
                };
            });
        }

        public static object ClearDocument(Command command)
        {
            return UiSync.OnUi<object>(() =>
            {
                var doc = CanvasUtils.RequireDocument();

                var objectsToRemove = doc.Objects.ToList();

                // Preserve the bridge component and its support objects so
                // clearing the canvas never severs the MCP connection.
                var essentialComponents = objectsToRemove.Where(obj =>
                    obj is WaspMCPComponent ||
                    obj.NickName.Contains("MCP") ||
                    obj.NickName.Contains("Claude") ||
                    obj.GetType().Name.Contains("GH_MCP") ||
                    obj.Description.Contains("MCP server") ||
                    obj.GetType().Name.Contains("GH_BooleanToggle") ||
                    obj.NickName.Contains("Toggle") ||
                    obj.NickName.Contains("Status")
                ).ToList();

                // Also preserve anything directly wired to an essential object
                // (e.g. the status panel fed by the bridge component).
                foreach (var component in essentialComponents)
                {
                    objectsToRemove.Remove(component);
                }

                doc.RemoveObjects(objectsToRemove, false);
                doc.ScheduleSolution(10);

                return new
                {
                    message = "Document cleared",
                    removedCount = objectsToRemove.Count
                };
            });
        }

        public static object SaveDocument(Command command)
        {
            string path = command.GetParameter<string>("path");
            if (string.IsNullOrEmpty(path))
            {
                throw new ArgumentException("Save path is required");
            }

            return UiSync.OnUi<object>(() =>
            {
                var doc = CanvasUtils.RequireDocument();

                var dir = Path.GetDirectoryName(path);
                if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
                {
                    Directory.CreateDirectory(dir);
                }

                var archive = new GH_IO.Serialization.GH_Archive();
                if (!archive.AppendObject(doc, "Definition"))
                {
                    throw new InvalidOperationException("Failed to serialize the Grasshopper document");
                }
                if (!archive.WriteToFile(path, true, false))
                {
                    throw new InvalidOperationException($"Failed to write file: {path}");
                }

                return new
                {
                    message = "Document saved",
                    path = path
                };
            });
        }

        public static object LoadDocument(Command command)
        {
            string path = command.GetParameter<string>("path");
            if (string.IsNullOrEmpty(path))
            {
                throw new ArgumentException("Load path is required");
            }

            return UiSync.OnUi<object>(() =>
            {
                if (!File.Exists(path))
                {
                    throw new FileNotFoundException($"File not found: {path}");
                }

                var io = new GH_DocumentIO();
                if (!io.Open(path))
                {
                    throw new InvalidOperationException($"Failed to open document: {path}");
                }

                var newDoc = io.Document;
                if (newDoc == null)
                {
                    throw new InvalidOperationException($"Document loaded but is null: {path}");
                }

                Grasshopper.Instances.DocumentServer.AddDocument(newDoc);
                if (Grasshopper.Instances.ActiveCanvas != null)
                {
                    Grasshopper.Instances.ActiveCanvas.Document = newDoc;
                }
                newDoc.ScheduleSolution(10);

                return new
                {
                    message = "Document loaded",
                    path = path,
                    componentCount = newDoc.Objects.Count
                };
            });
        }
    }
}
