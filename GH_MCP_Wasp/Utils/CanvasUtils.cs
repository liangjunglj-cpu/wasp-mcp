using System;
using System.Collections.Generic;
using System.Linq;
using GH_MCP_Wasp.Models;
using Grasshopper.Kernel;
using Grasshopper.Kernel.Types;
using Rhino;
using Rhino.DocObjects;

namespace GH_MCP_Wasp.Utils
{
    /// <summary>
    /// Shared helpers for canvas access, parameter resolution and data
    /// serialization. All methods that touch GH_Document assume they are
    /// already running on the UI thread (callers go through UiSync.OnUi).
    /// </summary>
    public static class CanvasUtils
    {
        public static GH_Document RequireDocument()
        {
            var doc = Grasshopper.Instances.ActiveCanvas?.Document;
            if (doc == null)
            {
                throw new InvalidOperationException("No active Grasshopper document");
            }
            return doc;
        }

        /// <summary>
        /// v0.3 batch-solve support: true unless the command carries
        /// "solve": false. Every mutating command consults this so a wiring
        /// batch can suppress intermediate solves and end with one explicit
        /// expire_solution (PROTOCOL.md "v0.3 commands").
        /// </summary>
        public static bool ShouldSolve(Command command)
        {
            return !command.HasParameter("solve") || command.GetParameter<bool>("solve");
        }

        /// <summary>
        /// Expire <paramref name="obj"/> (when given) and schedule a solution,
        /// unless the command requested "solve": false. Callers must already
        /// be on the UI thread (as with every other doc-touching helper here).
        /// </summary>
        public static void MaybeExpire(Command command, GH_Document doc, IGH_DocumentObject obj = null)
        {
            if (!ShouldSolve(command)) return;
            if (obj is IGH_ActiveObject active)
            {
                active.ExpireSolution(false);
            }
            doc.ScheduleSolution(10);
        }

        public static IGH_DocumentObject RequireObject(GH_Document doc, string idStr)
        {
            if (string.IsNullOrEmpty(idStr))
            {
                throw new ArgumentException("Component ID is required");
            }
            if (!Guid.TryParse(idStr, out Guid id))
            {
                throw new ArgumentException($"Invalid component ID format: {idStr}");
            }
            IGH_DocumentObject obj = doc.FindObject(id, true);
            if (obj == null)
            {
                throw new ArgumentException($"Component with ID {idStr} not found");
            }
            return obj;
        }

        /// <summary>
        /// Resolve a parameter on a document object by name/nickname
        /// (case-insensitive) or explicit index. Floating params resolve to
        /// themselves. Throws with the available parameter names on failure.
        /// </summary>
        public static IGH_Param ResolveParam(IGH_DocumentObject obj, string name, int? index, bool isInput)
        {
            if (obj is IGH_Param floating)
            {
                return floating;
            }

            if (!(obj is IGH_Component component))
            {
                throw new ArgumentException($"Object {obj.NickName} ({obj.GetType().Name}) has no parameters");
            }

            IList<IGH_Param> parameters = isInput ? component.Params.Input : component.Params.Output;
            if (parameters == null || parameters.Count == 0)
            {
                throw new ArgumentException($"Component {obj.NickName} has no {(isInput ? "input" : "output")} parameters");
            }

            // Explicit index wins
            if (index.HasValue)
            {
                if (index.Value >= 0 && index.Value < parameters.Count)
                {
                    return parameters[index.Value];
                }
                throw new ArgumentException($"Parameter index {index.Value} out of range (0..{parameters.Count - 1})");
            }

            // No name given: only unambiguous when a single param exists
            if (string.IsNullOrEmpty(name))
            {
                if (parameters.Count == 1)
                {
                    return parameters[0];
                }
                throw new ArgumentException($"Parameter name required; available: {DescribeParams(parameters)}");
            }

            // Exact name, exact nickname, then contains matches
            foreach (var p in parameters)
                if (string.Equals(p.Name, name, StringComparison.OrdinalIgnoreCase)) return p;
            foreach (var p in parameters)
                if (string.Equals(p.NickName, name, StringComparison.OrdinalIgnoreCase)) return p;
            foreach (var p in parameters)
                if (p.Name.IndexOf(name, StringComparison.OrdinalIgnoreCase) >= 0) return p;
            foreach (var p in parameters)
                if (p.NickName.IndexOf(name, StringComparison.OrdinalIgnoreCase) >= 0) return p;

            throw new ArgumentException(
                $"{(isInput ? "Input" : "Output")} parameter '{name}' not found on {obj.NickName}; available: {DescribeParams(parameters)}");
        }

        private static string DescribeParams(IList<IGH_Param> parameters)
        {
            return string.Join(", ", parameters.Select((p, i) => $"[{i}] {p.Name} ({p.NickName})"));
        }

        /// <summary>
        /// All wire connections in the document as
        /// {sourceId, sourceParam, targetId, targetParam} records.
        /// </summary>
        public static List<object> BuildConnectionList(GH_Document doc)
        {
            var connections = new List<object>();
            foreach (var obj in doc.Objects)
            {
                IEnumerable<IGH_Param> inputs;
                if (obj is IGH_Component component)
                {
                    inputs = component.Params.Input;
                }
                else if (obj is IGH_Param param)
                {
                    inputs = new[] { param };
                }
                else
                {
                    continue;
                }

                foreach (var input in inputs)
                {
                    foreach (var source in input.Sources)
                    {
                        var sourceOwner = source.Attributes?.GetTopLevel?.DocObject ?? (IGH_DocumentObject)source;
                        connections.Add(new Dictionary<string, object>
                        {
                            { "sourceId", sourceOwner.InstanceGuid.ToString() },
                            { "sourceParam", source.Name },
                            { "targetId", obj.InstanceGuid.ToString() },
                            { "targetParam", input.Name }
                        });
                    }
                }
            }
            return connections;
        }

        /// <summary>
        /// Serialize a single goo item per PROTOCOL.md:
        /// meshes -> {vertices, faces}; planes -> {origin, xAxis, yAxis};
        /// transforms -> 16-float row-major array; primitives as-is;
        /// points/vectors -> [x,y,z]; everything else -> {type, text}.
        /// </summary>
        public static object SerializeGoo(IGH_Goo goo)
        {
            if (goo == null) return null;

            switch (goo)
            {
                case GH_Mesh gm:
                    return SerializeMesh(gm.Value);
                case GH_Plane gp:
                    {
                        var pl = gp.Value;
                        return new Dictionary<string, object>
                        {
                            { "origin", new[] { pl.Origin.X, pl.Origin.Y, pl.Origin.Z } },
                            { "xAxis", new[] { pl.XAxis.X, pl.XAxis.Y, pl.XAxis.Z } },
                            { "yAxis", new[] { pl.YAxis.X, pl.YAxis.Y, pl.YAxis.Z } }
                        };
                    }
                case GH_Transform gt:
                    {
                        var t = gt.Value;
                        return new[]
                        {
                            t.M00, t.M01, t.M02, t.M03,
                            t.M10, t.M11, t.M12, t.M13,
                            t.M20, t.M21, t.M22, t.M23,
                            t.M30, t.M31, t.M32, t.M33
                        };
                    }
                case GH_Point pt:
                    return new[] { pt.Value.X, pt.Value.Y, pt.Value.Z };
                case GH_Vector v:
                    return new[] { v.Value.X, v.Value.Y, v.Value.Z };
                case GH_Number n:
                    return n.Value;
                case GH_Integer i:
                    return i.Value;
                case GH_Boolean b:
                    return b.Value;
                case GH_String s:
                    return s.Value;
                case GH_Guid g:
                    return g.Value.ToString();
                default:
                    // Breps, surfaces, curves, Wasp python objects, wrappers...
                    return new Dictionary<string, object>
                    {
                        { "type", goo.TypeName },
                        { "text", goo.ToString() }
                    };
            }
        }

        public static object SerializeMesh(Rhino.Geometry.Mesh mesh)
        {
            if (mesh == null) return null;

            var vertices = new List<double[]>(mesh.Vertices.Count);
            foreach (var v in mesh.Vertices)
            {
                vertices.Add(new double[] { v.X, v.Y, v.Z });
            }

            var faces = new List<int[]>(mesh.Faces.Count);
            foreach (var f in mesh.Faces)
            {
                faces.Add(f.IsQuad
                    ? new[] { f.A, f.B, f.C, f.D }
                    : new[] { f.A, f.B, f.C });
            }

            return new Dictionary<string, object>
            {
                { "vertices", vertices },
                { "faces", faces }
            };
        }

        /// <summary>
        /// Find or create a (possibly nested, "::"-separated) layer path.
        /// Returns the layer index.
        /// </summary>
        public static int EnsureLayer(RhinoDoc rdoc, string fullPath)
        {
            if (string.IsNullOrWhiteSpace(fullPath))
            {
                return rdoc.Layers.CurrentLayerIndex;
            }

            int existing = rdoc.Layers.FindByFullPath(fullPath, -1);
            if (existing >= 0)
            {
                return existing;
            }

            string[] parts = fullPath.Split(new[] { "::" }, StringSplitOptions.RemoveEmptyEntries);
            Guid parentId = Guid.Empty;
            int index = -1;
            string current = null;

            foreach (var part in parts)
            {
                current = current == null ? part : current + "::" + part;
                int found = rdoc.Layers.FindByFullPath(current, -1);
                if (found >= 0)
                {
                    index = found;
                    parentId = rdoc.Layers[found].Id;
                    continue;
                }

                var layer = new Layer { Name = part };
                if (parentId != Guid.Empty)
                {
                    layer.ParentLayerId = parentId;
                }
                index = rdoc.Layers.Add(layer);
                if (index < 0)
                {
                    throw new InvalidOperationException($"Failed to create layer '{current}'");
                }
                parentId = rdoc.Layers[index].Id;
            }

            return index;
        }
    }
}
