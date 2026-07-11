using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using GH_MCP_Wasp.Models;
using GH_MCP_Wasp.Utils;
using Grasshopper.Kernel;
using Grasshopper.Kernel.Data;
using Grasshopper.Kernel.Parameters;
using Grasshopper.Kernel.Special;
using Grasshopper.Kernel.Types;
using Newtonsoft.Json;
using Rhino;
using Rhino.DocObjects;
using Rhino.Geometry;

namespace GH_MCP_Wasp.Commands
{
    /// <summary>
    /// New wasp-mcp commands per PROTOCOL.md v0.1:
    /// add_user_object, connect_by_name, set_slider, set_panel,
    /// set_geometry_ref, get_component_output, get_canvas_state,
    /// expire_solution, bake_component_output.
    /// v0.2 additions: set_plane_values, set_toggle, delete_components.
    /// v0.3 additions: wait_for_idle; "solve" flag (default true) on every
    /// mutating command; set_panel "split_lines" (default true).
    /// v0.4 additions: add_group, add_scribble, set_nickname (canvas
    /// organization — all visual-only, no solution expiry); create_cluster
    /// (exploratory, answers not_supported_yet).
    /// </summary>
    public static class WaspCommandHandler
    {
        // ------------------------------------------------------------------
        // add_user_object
        // ------------------------------------------------------------------
        public static object AddUserObject(Command command)
        {
            string path = command.GetParameter<string>("path");
            double x = command.GetParameter<double>("x");
            double y = command.GetParameter<double>("y");

            if (string.IsNullOrEmpty(path))
            {
                throw new ArgumentException("UserObject path is required");
            }
            if (!File.Exists(path))
            {
                throw new FileNotFoundException($"UserObject file not found: {path}");
            }

            return UiSync.OnUi<object>(() =>
            {
                var doc = CanvasUtils.RequireDocument();

                var userObject = new GH_UserObject(path);
                IGH_DocumentObject instance = userObject.InstantiateObject();
                if (instance == null)
                {
                    throw new InvalidOperationException($"Failed to instantiate user object from {path}");
                }

                if (instance.Attributes == null)
                {
                    instance.CreateAttributes();
                }
                instance.Attributes.Pivot = new System.Drawing.PointF((float)x, (float)y);

                if (!doc.AddObject(instance, false))
                {
                    throw new InvalidOperationException($"Failed to add user object to document: {path}");
                }

                instance.Attributes.ExpireLayout();
                CanvasUtils.MaybeExpire(command, doc);

                var inputs = new List<object>();
                var outputs = new List<object>();

                if (instance is IGH_Component component)
                {
                    for (int i = 0; i < component.Params.Input.Count; i++)
                    {
                        inputs.Add(DescribeParam(component.Params.Input[i], i));
                    }
                    for (int i = 0; i < component.Params.Output.Count; i++)
                    {
                        outputs.Add(DescribeParam(component.Params.Output[i], i));
                    }
                }
                else if (instance is IGH_Param param)
                {
                    // A floating param acts as its own single output.
                    outputs.Add(DescribeParam(param, 0));
                }

                return new Dictionary<string, object>
                {
                    { "id", instance.InstanceGuid.ToString() },
                    { "name", instance.Name },
                    { "nickname", instance.NickName },
                    { "inputs", inputs },
                    { "outputs", outputs }
                };
            });
        }

        private static object DescribeParam(IGH_Param param, int index)
        {
            return new Dictionary<string, object>
            {
                { "name", param.Name },
                { "nickname", param.NickName },
                { "index", index },
                { "typeName", param.TypeName }
            };
        }

        // ------------------------------------------------------------------
        // connect_by_name
        // ------------------------------------------------------------------
        public static object ConnectByName(Command command)
        {
            string sourceId = command.GetParameter<string>("sourceId");
            string targetId = command.GetParameter<string>("targetId");

            if (string.IsNullOrEmpty(sourceId) || string.IsNullOrEmpty(targetId))
            {
                throw new ArgumentException("sourceId and targetId are required");
            }

            // sourceParam/targetParam may be null when indices are provided
            // (e.g. implicit outputs of Panel / Number Slider).
            string sourceParam = command.HasParameter("sourceParam")
                ? command.GetParameter<string>("sourceParam") : null;
            string targetParam = command.HasParameter("targetParam")
                ? command.GetParameter<string>("targetParam") : null;

            int? sourceIndex = command.HasParameter("sourceIndex")
                ? (int?)command.GetParameter<int>("sourceIndex") : null;
            int? targetIndex = command.HasParameter("targetIndex")
                ? (int?)command.GetParameter<int>("targetIndex") : null;

            return UiSync.OnUi<object>(() =>
            {
                var doc = CanvasUtils.RequireDocument();

                var sourceObj = CanvasUtils.RequireObject(doc, sourceId);
                var targetObj = CanvasUtils.RequireObject(doc, targetId);

                IGH_Param source = CanvasUtils.ResolveParam(sourceObj, sourceParam, sourceIndex, isInput: false);
                IGH_Param target = CanvasUtils.ResolveParam(targetObj, targetParam, targetIndex, isInput: true);

                // Append (do NOT replace): Wasp workflows routinely merge
                // multiple part outputs into one input.
                target.AddSource(source);

                CanvasUtils.MaybeExpire(command, doc, targetObj);

                return new Dictionary<string, object> { { "connected", true } };
            });
        }

        // ------------------------------------------------------------------
        // set_slider
        // ------------------------------------------------------------------
        public static object SetSlider(Command command)
        {
            string idStr = command.GetParameter<string>("id");
            double value = command.GetParameter<double>("value");
            bool hasMin = command.HasParameter("min");
            bool hasMax = command.HasParameter("max");
            double min = hasMin ? command.GetParameter<double>("min") : 0.0;
            double max = hasMax ? command.GetParameter<double>("max") : 0.0;

            return UiSync.OnUi<object>(() =>
            {
                var doc = CanvasUtils.RequireDocument();
                var obj = CanvasUtils.RequireObject(doc, idStr);

                if (!(obj is GH_NumberSlider slider))
                {
                    throw new ArgumentException($"Component {idStr} is not a Number Slider (found {obj.GetType().Name})");
                }

                // Set Maximum first when raising the range above the current max,
                // otherwise the new Minimum gets clamped by the old Maximum.
                if (hasMax && (!hasMin || (decimal)min > slider.Slider.Maximum))
                {
                    slider.Slider.Maximum = (decimal)max;
                    if (hasMin) slider.Slider.Minimum = (decimal)min;
                }
                else
                {
                    if (hasMin) slider.Slider.Minimum = (decimal)min;
                    if (hasMax) slider.Slider.Maximum = (decimal)max;
                }

                slider.SetSliderValue((decimal)value);
                CanvasUtils.MaybeExpire(command, doc, slider);

                return new Dictionary<string, object>
                {
                    { "id", slider.InstanceGuid.ToString() },
                    { "value", (double)slider.CurrentValue },
                    { "min", (double)slider.Slider.Minimum },
                    { "max", (double)slider.Slider.Maximum }
                };
            });
        }

        // ------------------------------------------------------------------
        // set_panel
        // ------------------------------------------------------------------
        public static object SetPanel(Command command)
        {
            string idStr = command.GetParameter<string>("id");
            string text = command.GetParameter<string>("text") ?? string.Empty;

            // v0.3: split_lines (default TRUE — deliberate default change vs
            // v0.1, per PROTOCOL "set_panel line splitting"): each text line
            // becomes a separate data item. GH_Panel.Properties.Multiline is
            // the inverse switch — CollectVolatileData_Custom splits UserText
            // into one GH_String per line when Multiline == false, and emits
            // the whole text as ONE item when Multiline == true (the "Multiline
            // Data" context-menu toggle; default true for a new GH_Panel).
            bool splitLines = !command.HasParameter("split_lines")
                || command.GetParameter<bool>("split_lines");

            return UiSync.OnUi<object>(() =>
            {
                var doc = CanvasUtils.RequireDocument();
                var obj = CanvasUtils.RequireObject(doc, idStr);

                if (!(obj is GH_Panel panel))
                {
                    throw new ArgumentException($"Component {idStr} is not a Panel (found {obj.GetType().Name})");
                }

                panel.Properties.Multiline = !splitLines;
                panel.SetUserText(text);
                CanvasUtils.MaybeExpire(command, doc, panel);

                return new Dictionary<string, object>
                {
                    { "id", panel.InstanceGuid.ToString() },
                    { "text", text },
                    { "splitLines", splitLines }
                };
            });
        }

        // ------------------------------------------------------------------
        // set_geometry_ref
        // ------------------------------------------------------------------
        public static object SetGeometryRef(Command command)
        {
            string idStr = command.GetParameter<string>("id");
            var objectIds = command.GetParameter<List<string>>("objectIds");

            if (objectIds == null || objectIds.Count == 0)
            {
                throw new ArgumentException("objectIds is required and must be non-empty");
            }

            return UiSync.OnUi<object>(() =>
            {
                var doc = CanvasUtils.RequireDocument();
                var obj = CanvasUtils.RequireObject(doc, idStr);

                var rdoc = RhinoDoc.ActiveDoc;
                if (rdoc == null)
                {
                    throw new InvalidOperationException("No active Rhino document");
                }

                // Build referenced geometric goo for each Rhino object id:
                // duplicate the doc geometry into the goo, then stamp
                // ReferenceID so Grasshopper treats it as referenced geometry
                // that stays linked to the Rhino object.
                var goos = new List<IGH_GeometricGoo>();
                foreach (var oidStr in objectIds)
                {
                    if (!Guid.TryParse(oidStr, out Guid oid))
                    {
                        throw new ArgumentException($"Invalid Rhino object GUID: {oidStr}");
                    }
                    RhinoObject rhObj = rdoc.Objects.FindId(oid);
                    if (rhObj == null)
                    {
                        throw new ArgumentException($"Rhino object not found: {oidStr}");
                    }

                    var goo = GH_Convert.ToGeometricGoo(rhObj.Geometry.Duplicate());
                    if (goo == null)
                    {
                        throw new ArgumentException($"Unsupported geometry type on object {oidStr}: {rhObj.Geometry.GetType().Name}");
                    }
                    goo.ReferenceID = rhObj.Id;
                    goos.Add(goo);
                }

                // Assign as PersistentData on the param (replacing existing).
                IGH_Param targetParam = obj as IGH_Param;
                if (targetParam == null)
                {
                    throw new ArgumentException(
                        $"Component {idStr} is not a geometry parameter component (found {obj.GetType().Name}); " +
                        "set_geometry_ref targets floating Geometry/Mesh/Brep/Curve params");
                }

                switch (targetParam)
                {
                    case Param_Geometry pGeo:
                        pGeo.PersistentData.Clear();
                        foreach (var goo in goos) pGeo.PersistentData.Append(goo);
                        break;
                    case Param_Mesh pMesh:
                        pMesh.PersistentData.Clear();
                        foreach (var goo in goos) pMesh.PersistentData.Append(CoerceGoo<GH_Mesh>(goo));
                        break;
                    case Param_Brep pBrep:
                        pBrep.PersistentData.Clear();
                        foreach (var goo in goos) pBrep.PersistentData.Append(CoerceGoo<GH_Brep>(goo));
                        break;
                    case Param_Curve pCurve:
                        pCurve.PersistentData.Clear();
                        foreach (var goo in goos) pCurve.PersistentData.Append(CoerceGoo<GH_Curve>(goo));
                        break;
                    case Param_Surface pSurf:
                        pSurf.PersistentData.Clear();
                        foreach (var goo in goos) pSurf.PersistentData.Append(CoerceGoo<GH_Surface>(goo));
                        break;
                    case Param_Point pPoint:
                        pPoint.PersistentData.Clear();
                        foreach (var goo in goos) pPoint.PersistentData.Append(CoerceGoo<GH_Point>(goo));
                        break;
                    case Param_GenericObject pGen:
                        pGen.PersistentData.Clear();
                        foreach (var goo in goos) pGen.PersistentData.Append(goo);
                        break;
                    default:
                        throw new ArgumentException(
                            $"Unsupported parameter type for set_geometry_ref: {targetParam.GetType().Name}");
                }

                CanvasUtils.MaybeExpire(command, doc, obj);

                return new Dictionary<string, object>
                {
                    { "id", obj.InstanceGuid.ToString() },
                    { "count", goos.Count }
                };
            });
        }

        private static TGoo CoerceGoo<TGoo>(IGH_GeometricGoo goo) where TGoo : class, IGH_Goo, new()
        {
            if (goo is TGoo direct)
            {
                return direct;
            }
            var converted = new TGoo();
            if (converted.CastFrom(goo))
            {
                return converted;
            }
            throw new ArgumentException($"Cannot convert {goo.TypeName} to {typeof(TGoo).Name}");
        }

        // ------------------------------------------------------------------
        // get_component_output
        // ------------------------------------------------------------------
        public static object GetComponentOutput(Command command)
        {
            string idStr = command.GetParameter<string>("id");
            string paramName = command.HasParameter("param")
                ? command.GetParameter<string>("param") : null;
            int maxItems = command.HasParameter("maxItems")
                ? command.GetParameter<int>("maxItems") : 1000;
            if (maxItems <= 0) maxItems = 1000;

            return UiSync.OnUi<object>(() =>
            {
                var doc = CanvasUtils.RequireDocument();

                if (IsSolutionRunning(doc))
                {
                    // Exact error string per PROTOCOL.md - passed through
                    // verbatim by the registry.
                    return (object)Response.CreateError("solution_running");
                }

                var obj = CanvasUtils.RequireObject(doc, idStr);
                IGH_Param param = CanvasUtils.ResolveParam(obj, paramName, null, isInput: false);

                // Expired-but-not-yet-solved param: a scheduled solution hasn't
                // fired yet. Returning its (empty) data would be stale-data-as-
                // success, so report solution_running and let the client retry.
                if (param.Phase == GH_SolutionPhase.Blank)
                {
                    return (object)Response.CreateError("solution_running");
                }

                var data = param.VolatileData;
                var items = new List<object>();
                bool truncated = false;

                foreach (var path in data.Paths)
                {
                    var branch = data.get_Branch(path);
                    if (branch == null) continue;
                    foreach (var item in branch)
                    {
                        if (items.Count >= maxItems)
                        {
                            truncated = true;
                            break;
                        }
                        items.Add(CanvasUtils.SerializeGoo(item as IGH_Goo));
                    }
                    if (truncated) break;
                }

                var result = new Dictionary<string, object>
                {
                    { "dataType", param.TypeName },
                    { "branchCount", data.PathCount },
                    { "items", items }
                };
                if (truncated)
                {
                    result["truncated"] = true;
                }
                return (object)result;
            });
        }

        // ------------------------------------------------------------------
        // get_canvas_state
        // ------------------------------------------------------------------
        public static object GetCanvasState(Command command)
        {
            return UiSync.OnUi<object>(() =>
            {
                var doc = CanvasUtils.RequireDocument();

                var components = new List<object>();
                foreach (var obj in doc.Objects)
                {
                    var runtimeMessages = new List<object>();
                    if (obj is IGH_ActiveObject active)
                    {
                        CollectMessages(active, GH_RuntimeMessageLevel.Error, "error", runtimeMessages);
                        CollectMessages(active, GH_RuntimeMessageLevel.Warning, "warning", runtimeMessages);
                        CollectMessages(active, GH_RuntimeMessageLevel.Remark, "remark", runtimeMessages);
                    }

                    float px = obj.Attributes != null ? obj.Attributes.Pivot.X : 0f;
                    float py = obj.Attributes != null ? obj.Attributes.Pivot.Y : 0f;

                    components.Add(new Dictionary<string, object>
                    {
                        { "id", obj.InstanceGuid.ToString() },
                        { "name", obj.Name },
                        { "nickname", obj.NickName },
                        { "position", new[] { (double)px, (double)py } },
                        { "runtimeMessages", runtimeMessages }
                    });
                }

                return new Dictionary<string, object>
                {
                    { "components", components },
                    { "connections", CanvasUtils.BuildConnectionList(doc) },
                    { "solutionState", IsSolutionRunning(doc) ? "running" : "idle" },
                    // Additive as of v0.2: lets clients detect bridge capability
                    // without probing (PROTOCOL.md "v0.2 commands").
                    { "version", WaspMCPInfo.BridgeVersion }
                };
            });
        }

        private static void CollectMessages(IGH_ActiveObject obj, GH_RuntimeMessageLevel level, string label, List<object> sink)
        {
            var messages = obj.RuntimeMessages(level);
            if (messages == null) return;
            foreach (var text in messages)
            {
                sink.Add(new Dictionary<string, object>
                {
                    { "level", label },
                    { "text", text }
                });
            }
        }

        private static bool IsSolutionRunning(GH_Document doc)
        {
            return doc.SolutionDepth > 0 || doc.SolutionState == GH_ProcessStep.Process;
        }

        // ------------------------------------------------------------------
        // expire_solution
        // ------------------------------------------------------------------
        public static object ExpireSolution(Command command)
        {
            List<string> ids = command.HasParameter("ids")
                ? command.GetParameter<List<string>>("ids") : null;

            return UiSync.OnUi<object>(() =>
            {
                var doc = CanvasUtils.RequireDocument();

                if (ids == null || ids.Count == 0)
                {
                    // Recompute the whole document.
                    doc.ScheduleSolution(10, d =>
                    {
                        foreach (var obj in d.Objects.OfType<IGH_ActiveObject>())
                        {
                            obj.ExpireSolution(false);
                        }
                    });
                }
                else
                {
                    // Validate ids up front so bad requests fail loudly.
                    var targets = ids.Select(i => CanvasUtils.RequireObject(doc, i)).ToList();
                    doc.ScheduleSolution(10, d =>
                    {
                        foreach (var target in targets)
                        {
                            if (target is IGH_ActiveObject active)
                            {
                                active.ExpireSolution(false);
                            }
                        }
                    });
                }

                // Returns immediately; the solution runs on the UI thread
                // after the scheduled delay.
                return new Dictionary<string, object> { { "scheduled", true } };
            });
        }

        // ------------------------------------------------------------------
        // wait_for_idle (v0.3)
        // ------------------------------------------------------------------
        public static object WaitForIdle(Command command)
        {
            int timeoutMs = command.HasParameter("timeoutMs")
                ? command.GetParameter<int>("timeoutMs") : 30000;
            if (timeoutMs <= 0) timeoutMs = 30000;
            if (timeoutMs > 120000) timeoutMs = 120000;

            // Fetch the document reference OFF-thread (validator F5): a UI
            // hop here would time out whenever a long solve occupies the UI
            // thread — precisely the case this command exists to wait out.
            // Instances.ActiveCanvas / ActiveCanvas.Document are property
            // reads of already-published references; reading them from the
            // TCP worker is safe. The polling loop below only READS
            // SolutionDepth/SolutionState.
            GH_Document doc = Grasshopper.Instances.ActiveCanvas?.Document;
            if (doc == null)
            {
                return (object)Response.CreateError("No active Grasshopper document");
            }

            var stopwatch = System.Diagnostics.Stopwatch.StartNew();
            int consecutiveIdleReads = 0;
            while (true)
            {
                if (!IsSolutionRunning(doc))
                {
                    // Require two idle reads 100 ms apart: a solution queued
                    // via ScheduleSolution(10) but not yet started reads as
                    // idle, and a single sample would race that window.
                    consecutiveIdleReads++;
                    if (consecutiveIdleReads >= 2)
                    {
                        return new Dictionary<string, object>
                        {
                            { "idle", true },
                            { "waitedMs", (int)stopwatch.ElapsedMilliseconds }
                        };
                    }
                }
                else
                {
                    consecutiveIdleReads = 0;
                }

                if (stopwatch.ElapsedMilliseconds >= timeoutMs)
                {
                    // Exact error string per PROTOCOL.md (client matches it).
                    return (object)Response.CreateError("wait_timeout");
                }

                System.Threading.Thread.Sleep(100);
            }
        }

        // ------------------------------------------------------------------
        // bake_component_output
        // ------------------------------------------------------------------
        public static object BakeComponentOutput(Command command)
        {
            string idStr = command.GetParameter<string>("id");
            string paramName = command.HasParameter("param")
                ? command.GetParameter<string>("param") : null;
            string layerPath = command.HasParameter("layer")
                ? command.GetParameter<string>("layer") : null;

            return UiSync.OnUi<object>(() =>
            {
                var doc = CanvasUtils.RequireDocument();

                if (IsSolutionRunning(doc))
                {
                    return (object)Response.CreateError("solution_running");
                }

                var obj = CanvasUtils.RequireObject(doc, idStr);
                IGH_Param param = CanvasUtils.ResolveParam(obj, paramName, null, isInput: false);

                // Same stale-data guard as get_component_output.
                if (param.Phase == GH_SolutionPhase.Blank)
                {
                    return (object)Response.CreateError("solution_running");
                }

                var rdoc = RhinoDoc.ActiveDoc;
                if (rdoc == null)
                {
                    throw new InvalidOperationException("No active Rhino document");
                }

                int layerIndex = CanvasUtils.EnsureLayer(rdoc, layerPath);
                var attributes = rdoc.CreateDefaultAttributes();
                attributes.LayerIndex = layerIndex;

                var bakedIds = new List<string>();
                foreach (var item in param.VolatileData.AllData(true))
                {
                    if (item == null) continue;

                    if (item is IGH_BakeAwareData bakeAware)
                    {
                        if (bakeAware.BakeGeometry(rdoc, attributes, out Guid bakedId) && bakedId != Guid.Empty)
                        {
                            bakedIds.Add(bakedId.ToString());
                        }
                    }
                    else if (item is IGH_GeometricGoo geoGoo)
                    {
                        var geometry = GH_Convert.ToGeometryBase(geoGooRaw(geoGoo));
                        if (geometry != null)
                        {
                            Guid addedId = rdoc.Objects.Add(geometry, attributes);
                            if (addedId != Guid.Empty)
                            {
                                bakedIds.Add(addedId.ToString());
                            }
                        }
                    }
                }

                rdoc.Views.Redraw();

                return new Dictionary<string, object>
                {
                    { "bakedIds", bakedIds }
                };
            });
        }

        private static object geoGooRaw(IGH_GeometricGoo goo)
        {
            return goo.ScriptVariable() ?? goo;
        }

        // ------------------------------------------------------------------
        // set_plane_values (v0.2)
        // ------------------------------------------------------------------

        /// <summary>Wire shape of one plane in set_plane_values.</summary>
        private class PlaneDto
        {
            [JsonProperty("origin")]
            public double[] Origin { get; set; }

            [JsonProperty("xAxis")]
            public double[] XAxis { get; set; }

            [JsonProperty("yAxis")]
            public double[] YAxis { get; set; }
        }

        public static object SetPlaneValues(Command command)
        {
            string idStr = command.GetParameter<string>("id");
            var planeDtos = command.GetParameter<List<PlaneDto>>("planes");

            if (planeDtos == null || planeDtos.Count == 0)
            {
                throw new ArgumentException("planes is required and must be non-empty");
            }

            // Validate and build off the UI thread: bad input fails before
            // any canvas work is queued.
            var planes = new List<Plane>(planeDtos.Count);
            for (int i = 0; i < planeDtos.Count; i++)
            {
                planes.Add(BuildPlane(planeDtos[i], i));
            }

            return UiSync.OnUi<object>(() =>
            {
                var doc = CanvasUtils.RequireDocument();
                var obj = CanvasUtils.RequireObject(doc, idStr);

                if (!(obj is GH_PersistentParam<GH_Plane> planeParam))
                {
                    throw new ArgumentException(
                        $"Component {idStr} is not a Plane parameter (found {obj.GetType().Name}); " +
                        "set_plane_values targets floating Plane params (add_component type \"Plane\")");
                }

                planeParam.PersistentData.Clear();
                foreach (var plane in planes)
                {
                    planeParam.PersistentData.Append(new GH_Plane(plane));
                }

                CanvasUtils.MaybeExpire(command, doc, planeParam);

                return new Dictionary<string, object>
                {
                    { "count", planes.Count }
                };
            });
        }

        private static Plane BuildPlane(PlaneDto dto, int index)
        {
            double[] o = RequireTriplet(dto?.Origin, "origin", index);
            double[] xv = RequireTriplet(dto?.XAxis, "xAxis", index);
            double[] yv = RequireTriplet(dto?.YAxis, "yAxis", index);

            var xAxis = new Vector3d(xv[0], xv[1], xv[2]);
            var yAxis = new Vector3d(yv[0], yv[1], yv[2]);

            if (xAxis.IsTiny() || yAxis.IsTiny())
            {
                throw new ArgumentException($"planes[{index}]: xAxis/yAxis must be non-zero vectors");
            }
            if (Vector3d.CrossProduct(xAxis, yAxis).IsTiny())
            {
                throw new ArgumentException($"planes[{index}]: xAxis and yAxis are parallel; cannot define a plane");
            }

            // Plane(origin, xaxis, yaxis) orthonormalizes: X = unitized xaxis,
            // Y = component of yaxis perpendicular to X, Z = X x Y.
            var plane = new Plane(new Point3d(o[0], o[1], o[2]), xAxis, yAxis);
            if (!plane.IsValid)
            {
                throw new ArgumentException($"planes[{index}]: resulting plane is invalid");
            }
            return plane;
        }

        private static double[] RequireTriplet(double[] values, string key, int index)
        {
            if (values == null || values.Length != 3)
            {
                throw new ArgumentException(
                    $"planes[{index}].{key} must be a 3-float array [x,y,z]");
            }
            return values;
        }

        // ------------------------------------------------------------------
        // set_toggle (v0.2)
        // ------------------------------------------------------------------
        public static object SetToggle(Command command)
        {
            string idStr = command.GetParameter<string>("id");
            if (!command.HasParameter("value"))
            {
                throw new ArgumentException("value is required (true or false)");
            }
            bool value = command.GetParameter<bool>("value");

            return UiSync.OnUi<object>(() =>
            {
                var doc = CanvasUtils.RequireDocument();
                var obj = CanvasUtils.RequireObject(doc, idStr);

                if (!(obj is GH_BooleanToggle toggle))
                {
                    throw new ArgumentException(
                        $"Component {idStr} is not a Boolean Toggle (found {obj.GetType().Name})");
                }

                toggle.Value = value;
                CanvasUtils.MaybeExpire(command, doc, toggle);

                return new Dictionary<string, object>
                {
                    { "id", toggle.InstanceGuid.ToString() },
                    { "value", toggle.Value }
                };
            });
        }

        // ------------------------------------------------------------------
        // delete_components (v0.2)
        // ------------------------------------------------------------------
        public static object DeleteComponents(Command command)
        {
            var ids = command.GetParameter<List<string>>("ids");
            if (ids == null || ids.Count == 0)
            {
                throw new ArgumentException("ids is required and must be non-empty");
            }

            return UiSync.OnUi<object>(() =>
            {
                var doc = CanvasUtils.RequireDocument();

                var results = new List<object>();
                var toRemove = new List<IGH_DocumentObject>();

                foreach (var idStr in ids)
                {
                    if (!Guid.TryParse(idStr, out Guid id))
                    {
                        results.Add(DeleteEntry(idStr, false, "invalid id format"));
                        continue;
                    }

                    var obj = doc.FindObject(id, true);
                    if (obj == null)
                    {
                        results.Add(DeleteEntry(idStr, false, "not found"));
                        continue;
                    }

                    // Never remove the bridge component itself: doing so from a
                    // command it is serving would sever the MCP connection.
                    if (obj is WaspMCPComponent)
                    {
                        results.Add(DeleteEntry(idStr, false, "cannot delete bridge"));
                        continue;
                    }

                    if (toRemove.Contains(obj))
                    {
                        results.Add(DeleteEntry(idStr, false, "duplicate id in request"));
                        continue;
                    }

                    toRemove.Add(obj);
                    results.Add(DeleteEntry(idStr, true, null));
                }

                if (toRemove.Count > 0)
                {
                    doc.RemoveObjects(toRemove, false);
                    doc.ScheduleSolution(10);
                }

                return new Dictionary<string, object>
                {
                    { "deleted", toRemove.Count },
                    { "results", results }
                };
            });
        }

        private static Dictionary<string, object> DeleteEntry(string id, bool deleted, string error)
        {
            var entry = new Dictionary<string, object>
            {
                { "id", id },
                { "deleted", deleted }
            };
            if (error != null)
            {
                entry["error"] = error;
            }
            return entry;
        }

        // ------------------------------------------------------------------
        // add_group (v0.4)
        // ------------------------------------------------------------------

        /// <summary>
        /// Color channel order for add_group: [R, G, B] or [R, G, B, A]
        /// (alpha LAST — matches the PROTOCOL example [190, 220, 190, 120],
        /// a pale green at low opacity). When alpha is omitted the group
        /// uses 150, Grasshopper's own default group transparency, so an
        /// RGB-only color still reads as a tint behind the components
        /// rather than a solid block. Reported as "colorOrder": "RGBA" in
        /// the result.
        /// </summary>
        private static System.Drawing.Color? ParseGroupColor(List<double> channels)
        {
            if (channels == null)
            {
                return null;
            }
            if (channels.Count != 3 && channels.Count != 4)
            {
                throw new ArgumentException(
                    "color must be [r,g,b] or [r,g,b,a] (channel order RGBA, 0-255)");
            }
            var c = new int[4];
            for (int i = 0; i < channels.Count; i++)
            {
                int v = (int)Math.Round(channels[i]);
                if (v < 0 || v > 255)
                {
                    throw new ArgumentException(
                        $"color channel {i} out of range 0-255: {channels[i]}");
                }
                c[i] = v;
            }
            int alpha = channels.Count == 4 ? c[3] : 150;
            return System.Drawing.Color.FromArgb(alpha, c[0], c[1], c[2]);
        }

        public static object AddGroup(Command command)
        {
            var ids = command.GetParameter<List<string>>("ids");
            string name = command.HasParameter("name")
                ? command.GetParameter<string>("name") : null;
            var colorChannels = command.HasParameter("color")
                ? command.GetParameter<List<double>>("color") : null;

            if (ids == null || ids.Count == 0)
            {
                throw new ArgumentException("ids is required and must be non-empty");
            }

            // Validate off the UI thread: bad color fails before canvas work.
            System.Drawing.Color? colour = ParseGroupColor(colorChannels);

            return UiSync.OnUi<object>(() =>
            {
                var doc = CanvasUtils.RequireDocument();

                // Per-id validation: missing/bad ids get error entries, the
                // group is still created from the ids that DO exist.
                var results = new List<object>();
                var members = new List<Guid>();
                foreach (var idStr in ids)
                {
                    if (!Guid.TryParse(idStr, out Guid id))
                    {
                        results.Add(GroupEntry(idStr, false, "invalid id format"));
                        continue;
                    }
                    if (doc.FindObject(id, true) == null)
                    {
                        results.Add(GroupEntry(idStr, false, "not found"));
                        continue;
                    }
                    if (members.Contains(id))
                    {
                        results.Add(GroupEntry(idStr, false, "duplicate id in request"));
                        continue;
                    }
                    members.Add(id);
                    results.Add(GroupEntry(idStr, true, null));
                }

                if (members.Count == 0)
                {
                    throw new ArgumentException(
                        "none of the given ids exist on the canvas");
                }

                var group = new GH_Group();
                if (!string.IsNullOrEmpty(name))
                {
                    group.NickName = name;
                }
                if (colour.HasValue)
                {
                    group.Colour = colour.Value;
                }
                group.CreateAttributes();
                foreach (var id in members)
                {
                    // GH supports nesting/overlap: an id already grouped
                    // elsewhere is fine (PROTOCOL.md add_group).
                    group.AddObject(id);
                }

                if (!doc.AddObject(group, false))
                {
                    throw new InvalidOperationException("Failed to add group to document");
                }

                // Groups are visual-only: layout + repaint, NEVER a solution
                // expiry (regardless of any solve flag).
                group.Attributes.ExpireLayout();
                Grasshopper.Instances.RedrawCanvas();

                return new Dictionary<string, object>
                {
                    { "groupId", group.InstanceGuid.ToString() },
                    { "name", group.NickName },
                    { "grouped", members.Count },
                    { "colorOrder", "RGBA" },
                    { "results", results }
                };
            });
        }

        private static Dictionary<string, object> GroupEntry(string id, bool grouped, string error)
        {
            var entry = new Dictionary<string, object>
            {
                { "id", id },
                { "grouped", grouped }
            };
            if (error != null)
            {
                entry["error"] = error;
            }
            return entry;
        }

        // ------------------------------------------------------------------
        // add_scribble (v0.4)
        // ------------------------------------------------------------------
        public static object AddScribble(Command command)
        {
            string text = command.GetParameter<string>("text");
            double x = command.GetParameter<double>("x");
            double y = command.GetParameter<double>("y");
            double size = command.HasParameter("size")
                ? command.GetParameter<double>("size") : 14.0;

            if (string.IsNullOrEmpty(text))
            {
                throw new ArgumentException("text is required");
            }
            if (size <= 0.0 || size > 500.0)
            {
                throw new ArgumentException($"size out of range (0, 500]: {size}");
            }

            return UiSync.OnUi<object>(() =>
            {
                var doc = CanvasUtils.RequireDocument();

                var scribble = new GH_Scribble
                {
                    Text = text
                };
                // Keep the default scribble font family, override the size.
                scribble.Font = new System.Drawing.Font(
                    scribble.Font.FontFamily, (float)size);
                scribble.CreateAttributes();
                scribble.Attributes.Pivot = new System.Drawing.PointF((float)x, (float)y);

                if (!doc.AddObject(scribble, false))
                {
                    throw new InvalidOperationException("Failed to add scribble to document");
                }

                // Visual-only, like add_group: no solution expiry.
                scribble.Attributes.ExpireLayout();
                Grasshopper.Instances.RedrawCanvas();

                return new Dictionary<string, object>
                {
                    { "id", scribble.InstanceGuid.ToString() },
                    { "text", scribble.Text },
                    { "size", size }
                };
            });
        }

        // ------------------------------------------------------------------
        // set_nickname (v0.4)
        // ------------------------------------------------------------------
        public static object SetNickname(Command command)
        {
            string idStr = command.GetParameter<string>("id");
            string nickname = command.GetParameter<string>("nickname");

            if (string.IsNullOrEmpty(nickname))
            {
                throw new ArgumentException("nickname is required");
            }

            return UiSync.OnUi<object>(() =>
            {
                var doc = CanvasUtils.RequireDocument();
                var obj = CanvasUtils.RequireObject(doc, idStr);

                obj.NickName = nickname;

                // A pure rename never changes solution data, so no
                // ExpireSolution/ScheduleSolution. The attribute layout DOES
                // depend on the label (slider/panel/param bounds grow with
                // the name), so expire the layout and repaint the canvas —
                // NickName's setter alone only raises ObjectChanged, which
                // does not repaint when no editor event is in flight.
                obj.Attributes?.ExpireLayout();
                Grasshopper.Instances.RedrawCanvas();

                return new Dictionary<string, object>
                {
                    { "id", obj.InstanceGuid.ToString() },
                    { "nickname", obj.NickName }
                };
            });
        }

        // ------------------------------------------------------------------
        // create_cluster (v0.4 — EXPLORATORY, not shipped)
        // ------------------------------------------------------------------
        public static object CreateCluster(Command command)
        {
            // PROTOCOL.md marks create_cluster exploratory ("may slip").
            // Reliable programmatic authoring needs: an inner GH_Document
            // built from serialized COPIES of the selected objects, a
            // GH_ClusterInputHook/GH_ClusterOutputHook pair per boundary
            // wire, re-wiring every outer connection onto the new cluster
            // instance, and removing the originals — each step can corrupt
            // the outer document if it half-fails, and the hook plumbing is
            // not exposed as a supported public API. Rather than ship a
            // half-working command, v0.4 answers not_supported_yet (exact
            // leading token — clients may substring-match). add_group
            // covers canvas organization.
            return Response.CreateError(
                "not_supported_yet: create_cluster is exploratory in v0.4 — "
                + "programmatic GH_Cluster authoring (inner document + "
                + "input/output hook rewiring) is not reliable enough to ship. "
                + "Use add_group to organize components.");
        }
    }
}
