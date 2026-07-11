using System;
using System.Collections.Generic;
using System.Linq;
using GH_MCP_Wasp.Models;
using GH_MCP_Wasp.Utils;
using Grasshopper.Kernel;
using Grasshopper.Kernel.Parameters;
using Grasshopper.Kernel.Special;
using Rhino;

namespace GH_MCP_Wasp.Commands
{
    /// <summary>
    /// Baseline component commands (add_component, set_component_value,
    /// get_component_info, get_all_components, search_components,
    /// get_component_parameters). Semantics forked from GH_MCP; threading
    /// upgraded to UiSync.OnUi (TaskCompletionSource + 30 s timeout).
    /// </summary>
    public static class ComponentCommandHandler
    {
        public static object AddComponent(Command command)
        {
            string type = command.GetParameter<string>("type");
            double x = command.GetParameter<double>("x");
            double y = command.GetParameter<double>("y");

            if (string.IsNullOrEmpty(type))
            {
                throw new ArgumentException("Component type is required");
            }

            string normalizedType = FuzzyMatcher.GetClosestComponentName(type);

            return UiSync.OnUi<object>(() =>
            {
                var doc = CanvasUtils.RequireDocument();

                IGH_DocumentObject component = null;

                switch (normalizedType.ToLowerInvariant())
                {
                    // plane components
                    case "xy plane":
                        component = CreateComponentByName("XY Plane");
                        break;
                    case "xz plane":
                        component = CreateComponentByName("XZ Plane");
                        break;
                    case "yz plane":
                        component = CreateComponentByName("YZ Plane");
                        break;
                    case "plane 3pt":
                        component = CreateComponentByName("Plane 3Pt");
                        break;

                    // primitives
                    case "box":
                        component = CreateComponentByName("Box");
                        break;
                    case "sphere":
                        component = CreateComponentByName("Sphere");
                        break;
                    case "cylinder":
                        component = CreateComponentByName("Cylinder");
                        break;
                    case "cone":
                        component = CreateComponentByName("Cone");
                        break;
                    case "circle":
                        component = CreateComponentByName("Circle");
                        break;
                    case "rectangle":
                        component = CreateComponentByName("Rectangle");
                        break;
                    case "line":
                        component = CreateComponentByName("Line");
                        break;

                    // parameter objects
                    case "point":
                    case "pt":
                    case "pointparam":
                    case "param_point":
                        component = new Param_Point();
                        break;
                    case "curve":
                    case "crv":
                    case "curveparam":
                    case "param_curve":
                        component = new Param_Curve();
                        break;
                    case "circleparam":
                    case "param_circle":
                        component = new Param_Circle();
                        break;
                    case "lineparam":
                    case "param_line":
                        component = new Param_Line();
                        break;
                    case "mesh":
                    case "meshparam":
                    case "param_mesh":
                        component = new Param_Mesh();
                        break;
                    case "geometry":
                    case "geo":
                    case "geometryparam":
                    case "param_geometry":
                        component = new Param_Geometry();
                        break;
                    case "brep":
                    case "brepparam":
                    case "param_brep":
                        component = new Param_Brep();
                        break;
                    case "panel":
                    case "gh_panel":
                        component = new GH_Panel();
                        break;
                    // v0.2: floating Plane param, target of set_plane_values.
                    case "plane":
                    case "planeparam":
                    case "param_plane":
                        component = new Param_Plane();
                        break;
                    // v0.2: Boolean Toggle, target of set_toggle.
                    case "boolean toggle":
                    case "booleantoggle":
                    case "bool toggle":
                    case "toggle":
                    case "gh_booleantoggle":
                        component = new GH_BooleanToggle();
                        break;
                    case "slider":
                    case "numberslider":
                    case "number slider":
                    case "gh_numberslider":
                        var slider = new GH_NumberSlider();
                        slider.SetInitCode("0.0 < 0.5 < 1.0");
                        component = slider;
                        break;
                    case "number":
                    case "num":
                    case "integer":
                    case "int":
                    case "param_number":
                    case "param_integer":
                        component = new Param_Number();
                        break;
                    case "construct point":
                    case "constructpoint":
                    case "pt xyz":
                    case "xyz":
                        var pointProxy = Grasshopper.Instances.ComponentServer.ObjectProxies
                            .FirstOrDefault(p => p.Desc.Name.Equals("Construct Point", StringComparison.OrdinalIgnoreCase));
                        if (pointProxy != null)
                        {
                            component = pointProxy.CreateInstance();
                        }
                        else
                        {
                            throw new ArgumentException("Construct Point component not found");
                        }
                        break;
                    default:
                        // v0.5 resolution order (PROTOCOL.md "add_component
                        // nickname matching + ambiguity errors"): exact GUID
                        // -> exact name -> exact nickname -> unique fuzzy
                        // name, all case-insensitive. More than one proxy
                        // matching at the winning tier is a typed ambiguity
                        // error carrying the candidates (closes
                        // live-regression finding #1, "Square").
                        if (Guid.TryParse(type, out Guid componentGuid))
                        {
                            component = Grasshopper.Instances.ComponentServer.EmitObject(componentGuid);
                            if (component == null)
                            {
                                throw new ArgumentException($"No component found for GUID: {type}");
                            }
                            break;
                        }

                        var winners = ResolveProxiesByName(type);
                        if (winners.Count > 1)
                        {
                            // Returned verbatim by the registry: the additive
                            // "candidates" array rides next to "error".
                            return (object)Response.CreateError(
                                $"ambiguous_component_type: {type}",
                                winners.Select(p => (object)new Dictionary<string, object>
                                {
                                    { "name", p.Desc.Name },
                                    { "nickname", p.Desc.NickName },
                                    { "guid", p.Guid.ToString() },
                                    { "category", p.Desc.Category }
                                }).ToList());
                        }
                        if (winners.Count == 1)
                        {
                            component = winners[0].CreateInstance();
                        }

                        if (component == null)
                        {
                            var possibleMatches = Grasshopper.Instances.ComponentServer.ObjectProxies
                                .Where(p => p.Desc.Name.IndexOf(type, StringComparison.OrdinalIgnoreCase) >= 0)
                                .Select(p => p.Desc.Name)
                                .Take(10)
                                .ToList();

                            var errorMessage = $"Unknown component type: {type}";
                            if (possibleMatches.Any())
                            {
                                errorMessage += $". Possible matches: {string.Join(", ", possibleMatches)}";
                            }

                            throw new ArgumentException(errorMessage);
                        }
                        break;
                }

                if (component.Attributes == null)
                {
                    component.CreateAttributes();
                }

                component.Attributes.Pivot = new System.Drawing.PointF((float)x, (float)y);

                doc.AddObject(component, false);
                CanvasUtils.MaybeExpire(command, doc);

                return new
                {
                    id = component.InstanceGuid.ToString(),
                    type = component.GetType().Name,
                    name = component.NickName,
                    x = component.Attributes.Pivot.X,
                    y = component.Attributes.Pivot.Y
                };
            });
        }

        /// <summary>
        /// v0.5 add_component name resolution: returns ALL proxies matching
        /// at the winning tier — exact name, then exact nickname, then fuzzy
        /// (substring) name, all case-insensitive. An empty list means no
        /// match at any tier; more than one entry means the query is
        /// ambiguous at its winning tier. Non-obsolete proxies are preferred;
        /// obsolete ones are consulted only when no current proxy matches at
        /// any tier (so retired duplicates never create false ambiguity, but
        /// a name that only survives as an obsolete proxy still resolves —
        /// preserving pre-v0.5 behavior for currently-working names).
        /// </summary>
        private static List<IGH_ObjectProxy> ResolveProxiesByName(string query)
        {
            var all = Grasshopper.Instances.ComponentServer.ObjectProxies;

            var winners = MatchProxyTiers(all.Where(p => !p.Obsolete), query);
            if (winners.Count == 0)
            {
                winners = MatchProxyTiers(all.Where(p => p.Obsolete), query);
            }
            return winners;
        }

        private static List<IGH_ObjectProxy> MatchProxyTiers(IEnumerable<IGH_ObjectProxy> proxies, string query)
        {
            var pool = proxies.ToList();

            // Tier: exact name.
            var matches = pool
                .Where(p => p.Desc.Name.Equals(query, StringComparison.OrdinalIgnoreCase))
                .ToList();
            if (matches.Count > 0) return matches;

            // Tier: exact nickname.
            matches = pool
                .Where(p => p.Desc.NickName != null &&
                            p.Desc.NickName.Equals(query, StringComparison.OrdinalIgnoreCase))
                .ToList();
            if (matches.Count > 0) return matches;

            // Tier: fuzzy (substring) name — must be unique to win; the
            // caller turns multiple hits into ambiguous_component_type.
            return pool
                .Where(p => p.Desc.Name.IndexOf(query, StringComparison.OrdinalIgnoreCase) >= 0)
                .ToList();
        }

        public static object SetComponentValue(Command command)
        {
            string idStr = command.GetParameter<string>("id");
            string value = command.GetParameter<string>("value");

            if (string.IsNullOrEmpty(idStr))
            {
                throw new ArgumentException("Component ID is required");
            }

            return UiSync.OnUi<object>(() =>
            {
                var doc = CanvasUtils.RequireDocument();
                var component = CanvasUtils.RequireObject(doc, idStr);

                if (component is GH_Panel panel)
                {
                    panel.SetUserText(value ?? string.Empty);
                }
                else if (component is GH_NumberSlider slider)
                {
                    if (double.TryParse(value, out double doubleValue))
                    {
                        slider.SetSliderValue((decimal)doubleValue);
                    }
                    else
                    {
                        throw new ArgumentException("Invalid slider value format");
                    }
                }
                else if (component is IGH_Component ghComponent)
                {
                    if (ghComponent.Params.Input.Count > 0)
                    {
                        var param = ghComponent.Params.Input[0];
                        if (param is Param_String stringParam)
                        {
                            stringParam.PersistentData.Clear();
                            stringParam.PersistentData.Append(new Grasshopper.Kernel.Types.GH_String(value));
                        }
                        else if (param is Param_Number numberParam)
                        {
                            if (double.TryParse(value, out double doubleValue))
                            {
                                numberParam.PersistentData.Clear();
                                numberParam.PersistentData.Append(new Grasshopper.Kernel.Types.GH_Number(doubleValue));
                            }
                            else
                            {
                                throw new ArgumentException("Invalid number value format");
                            }
                        }
                        else
                        {
                            throw new ArgumentException($"Cannot set value for parameter type {param.GetType().Name}");
                        }
                    }
                    else
                    {
                        throw new ArgumentException("Component has no input parameters");
                    }
                }
                else
                {
                    throw new ArgumentException($"Cannot set value for component type {component.GetType().Name}");
                }

                CanvasUtils.MaybeExpire(command, doc, component);

                return new
                {
                    id = component.InstanceGuid.ToString(),
                    type = component.GetType().Name,
                    value = value
                };
            });
        }

        public static object GetComponentInfo(Command command)
        {
            // Baseline python client sends "componentId"; PROTOCOL passthrough may send "id".
            string idStr = command.GetParameter<string>("id");
            if (string.IsNullOrEmpty(idStr))
            {
                idStr = command.GetParameter<string>("componentId");
            }

            if (string.IsNullOrEmpty(idStr))
            {
                throw new ArgumentException("Component ID is required");
            }

            return UiSync.OnUi<object>(() =>
            {
                var doc = CanvasUtils.RequireDocument();
                var component = CanvasUtils.RequireObject(doc, idStr);

                var componentInfo = new Dictionary<string, object>
                {
                    { "id", component.InstanceGuid.ToString() },
                    { "type", component.GetType().Name },
                    { "name", component.NickName },
                    { "componentName", component.Name },
                    { "description", component.Description }
                };

                if (component is IGH_Component ghComponent)
                {
                    componentInfo["inputs"] = DescribeParams(ghComponent.Params.Input);
                    componentInfo["outputs"] = DescribeParams(ghComponent.Params.Output);
                }

                if (component is GH_Panel panel)
                {
                    componentInfo["value"] = panel.UserText;
                }

                if (component is GH_NumberSlider slider)
                {
                    componentInfo["value"] = (double)slider.CurrentValue;
                    componentInfo["minimum"] = (double)slider.Slider.Minimum;
                    componentInfo["maximum"] = (double)slider.Slider.Maximum;
                }

                return componentInfo;
            });
        }

        public static object GetAllComponents(Command command)
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
                        { "name", obj.Name },
                        { "nickname", obj.NickName },
                        { "x", obj.Attributes != null ? obj.Attributes.Pivot.X : 0f },
                        { "y", obj.Attributes != null ? obj.Attributes.Pivot.Y : 0f }
                    });
                }

                return components;
            });
        }

        public static object SearchComponents(Command command)
        {
            string query = command.GetParameter<string>("query");
            if (string.IsNullOrEmpty(query))
            {
                throw new ArgumentException("Search query is required");
            }

            // ComponentServer proxy list is static metadata; no document access needed.
            var matches = Grasshopper.Instances.ComponentServer.ObjectProxies
                .Where(p => !p.Obsolete)
                .Where(p =>
                    p.Desc.Name.IndexOf(query, StringComparison.OrdinalIgnoreCase) >= 0 ||
                    (p.Desc.Description != null && p.Desc.Description.IndexOf(query, StringComparison.OrdinalIgnoreCase) >= 0))
                .OrderBy(p => p.Desc.Name.IndexOf(query, StringComparison.OrdinalIgnoreCase) < 0 ? 1 : 0)
                .ThenBy(p => p.Desc.Name.Length)
                .Take(50)
                .Select(p => new Dictionary<string, object>
                {
                    { "name", p.Desc.Name },
                    { "nickname", p.Desc.NickName },
                    { "category", p.Desc.Category },
                    { "subCategory", p.Desc.SubCategory },
                    { "description", p.Desc.Description },
                    { "guid", p.Guid.ToString() }
                })
                .ToList();

            return new Dictionary<string, object>
            {
                { "query", query },
                { "count", matches.Count },
                { "components", matches }
            };
        }

        public static object GetComponentParameters(Command command)
        {
            string componentType = command.GetParameter<string>("componentType");
            if (string.IsNullOrEmpty(componentType))
            {
                componentType = command.GetParameter<string>("type");
            }
            if (string.IsNullOrEmpty(componentType))
            {
                throw new ArgumentException("componentType is required");
            }

            string normalized = FuzzyMatcher.GetClosestComponentName(componentType);

            return UiSync.OnUi<object>(() =>
            {
                var proxy = Grasshopper.Instances.ComponentServer.ObjectProxies
                    .FirstOrDefault(p => p.Desc.Name.Equals(normalized, StringComparison.OrdinalIgnoreCase))
                    ?? Grasshopper.Instances.ComponentServer.ObjectProxies
                    .FirstOrDefault(p => p.Desc.Name.IndexOf(normalized, StringComparison.OrdinalIgnoreCase) >= 0);

                if (proxy == null)
                {
                    throw new ArgumentException($"Component type '{componentType}' not found");
                }

                var instance = proxy.CreateInstance();

                var info = new Dictionary<string, object>
                {
                    { "componentType", proxy.Desc.Name },
                    { "guid", proxy.Guid.ToString() },
                    { "description", proxy.Desc.Description }
                };

                if (instance is IGH_Component component)
                {
                    info["inputs"] = DescribeParams(component.Params.Input);
                    info["outputs"] = DescribeParams(component.Params.Output);
                }
                else if (instance is IGH_Param param)
                {
                    info["inputs"] = new List<object>();
                    info["outputs"] = new List<object>
                    {
                        new Dictionary<string, object>
                        {
                            { "name", param.Name },
                            { "nickname", param.NickName },
                            { "description", param.Description },
                            { "type", param.GetType().Name },
                            { "dataType", param.TypeName }
                        }
                    };
                }

                return info;
            });
        }

        // ------------------------------------------------------------------
        // list_component_types (v0.3)
        // ------------------------------------------------------------------
        public static object ListComponentTypes(Command command)
        {
            string filter = command.HasParameter("filter")
                ? command.GetParameter<string>("filter") : null;
            string category = command.HasParameter("category")
                ? command.GetParameter<string>("category") : null;
            int limit = command.HasParameter("limit")
                ? command.GetParameter<int>("limit") : 100;
            if (limit <= 0) limit = 100;
            if (limit > 1000) limit = 1000;

            // ComponentServer proxy metadata is static; safe off the UI thread
            // (same pattern as search_components).
            var matches = Grasshopper.Instances.ComponentServer.ObjectProxies
                .Where(p => !p.Obsolete)
                .Where(p => string.IsNullOrEmpty(category) ||
                    (p.Desc.Category != null &&
                     p.Desc.Category.IndexOf(category, StringComparison.OrdinalIgnoreCase) >= 0))
                .Where(p => string.IsNullOrEmpty(filter) ||
                    p.Desc.Name.IndexOf(filter, StringComparison.OrdinalIgnoreCase) >= 0 ||
                    (p.Desc.NickName != null &&
                     p.Desc.NickName.IndexOf(filter, StringComparison.OrdinalIgnoreCase) >= 0) ||
                    (p.Desc.Description != null &&
                     p.Desc.Description.IndexOf(filter, StringComparison.OrdinalIgnoreCase) >= 0))
                .OrderBy(p => string.IsNullOrEmpty(filter) ? 0 :
                    (p.Desc.Name.IndexOf(filter, StringComparison.OrdinalIgnoreCase) < 0 ? 1 : 0))
                .ThenBy(p => p.Desc.Name.Length)
                .ThenBy(p => p.Desc.Name, StringComparer.OrdinalIgnoreCase)
                .ToList();

            var components = matches
                .Take(limit)
                .Select(p => (object)new Dictionary<string, object>
                {
                    { "name", p.Desc.Name },
                    { "nickname", p.Desc.NickName },
                    { "category", p.Desc.Category },
                    { "subCategory", p.Desc.SubCategory },
                    { "guid", p.Guid.ToString() },
                    { "description", p.Desc.Description }
                })
                .ToList();

            return new Dictionary<string, object>
            {
                { "components", components },
                { "total", matches.Count }
            };
        }

        // ------------------------------------------------------------------
        // get_component_schema (v0.3)
        // ------------------------------------------------------------------
        public static object GetComponentSchema(Command command)
        {
            string name = command.GetParameter<string>("name");
            if (string.IsNullOrEmpty(name))
            {
                throw new ArgumentException("name is required");
            }

            // Instantiation runs on the UI thread: CreateInstance may build
            // attributes/UI resources that are not thread-safe off-thread.
            return UiSync.OnUi<object>(() =>
            {
                var proxies = Grasshopper.Instances.ComponentServer.ObjectProxies;

                IGH_ObjectProxy proxy = null;
                if (Guid.TryParse(name, out Guid guid))
                {
                    proxy = proxies.FirstOrDefault(p => p.Guid == guid);
                }
                if (proxy == null)
                {
                    proxy = proxies.FirstOrDefault(p => !p.Obsolete &&
                        p.Desc.Name.Equals(name, StringComparison.OrdinalIgnoreCase));
                }
                if (proxy == null)
                {
                    proxy = proxies
                        .Where(p => !p.Obsolete &&
                            p.Desc.Name.IndexOf(name, StringComparison.OrdinalIgnoreCase) >= 0)
                        .OrderBy(p => p.Desc.Name.Length)
                        .FirstOrDefault();
                }
                if (proxy == null)
                {
                    throw new ArgumentException($"Component type '{name}' not found");
                }

                // Instantiate IN MEMORY only — never added to any document —
                // describe, then dispose.
                IGH_DocumentObject instance = null;
                try
                {
                    instance = proxy.CreateInstance();
                    if (instance == null)
                    {
                        throw new InvalidOperationException(
                            $"Could not instantiate component '{proxy.Desc.Name}'");
                    }

                    var inputs = new List<object>();
                    var outputs = new List<object>();

                    if (instance is IGH_Component component)
                    {
                        for (int i = 0; i < component.Params.Input.Count; i++)
                        {
                            inputs.Add(DescribeSchemaParam(component.Params.Input[i], i, includeDefault: true));
                        }
                        for (int i = 0; i < component.Params.Output.Count; i++)
                        {
                            outputs.Add(DescribeSchemaParam(component.Params.Output[i], i, includeDefault: false));
                        }
                    }
                    else if (instance is IGH_Param param)
                    {
                        // A floating param acts as its own single output.
                        outputs.Add(DescribeSchemaParam(param, 0, includeDefault: true));
                    }

                    return new Dictionary<string, object>
                    {
                        { "name", proxy.Desc.Name },
                        { "nickname", proxy.Desc.NickName },
                        { "guid", proxy.Guid.ToString() },
                        { "category", proxy.Desc.Category },
                        { "subCategory", proxy.Desc.SubCategory },
                        { "description", proxy.Desc.Description },
                        { "inputs", inputs },
                        { "outputs", outputs }
                    };
                }
                finally
                {
                    (instance as IDisposable)?.Dispose();
                }
            });
        }

        private static Dictionary<string, object> DescribeSchemaParam(IGH_Param param, int index, bool includeDefault)
        {
            var descriptor = new Dictionary<string, object>
            {
                { "name", param.Name },
                { "nickname", param.NickName },
                { "index", index },
                { "typeName", param.TypeName },
                { "description", param.Description },
                { "optional", param.Optional }
            };

            if (includeDefault)
            {
                object defaultValue = TryGetDefaultValue(param);
                if (defaultValue != null)
                {
                    descriptor["defaultValue"] = defaultValue;
                }
            }

            return descriptor;
        }

        /// <summary>
        /// Cheap default-value extraction: read the param's PersistentData
        /// (GH_PersistentParam&lt;T&gt;.PersistentData, found via reflection since T
        /// varies) and serialize its items. Returns null when the param has no
        /// persistent data or is not a persistent param (e.g. sliders/panels).
        /// </summary>
        private static object TryGetDefaultValue(IGH_Param param)
        {
            try
            {
                var property = param.GetType().GetProperty("PersistentData");
                if (property == null) return null;

                var structure = property.GetValue(param, null) as Grasshopper.Kernel.Data.IGH_Structure;
                if (structure == null || structure.DataCount == 0) return null;

                var items = new List<object>();
                foreach (var goo in structure.AllData(true))
                {
                    items.Add(CanvasUtils.SerializeGoo(goo));
                    if (items.Count >= 10) break; // defaults are small; cap defensively
                }
                if (items.Count == 0) return null;
                return items.Count == 1 ? items[0] : items;
            }
            catch
            {
                return null; // defaults are best-effort only
            }
        }

        private static List<object> DescribeParams(IEnumerable<IGH_Param> parameters)
        {
            var list = new List<object>();
            foreach (var param in parameters)
            {
                list.Add(new Dictionary<string, object>
                {
                    { "name", param.Name },
                    { "nickname", param.NickName },
                    { "description", param.Description },
                    { "type", param.GetType().Name },
                    { "dataType", param.TypeName }
                });
            }
            return list;
        }

        private static IGH_DocumentObject CreateComponentByName(string name)
        {
            var obj = Grasshopper.Instances.ComponentServer.ObjectProxies
                .FirstOrDefault(p => p.Desc.Name.Equals(name, StringComparison.OrdinalIgnoreCase));

            if (obj != null)
            {
                return obj.CreateInstance();
            }

            throw new ArgumentException($"Component with name {name} not found");
        }
    }
}
