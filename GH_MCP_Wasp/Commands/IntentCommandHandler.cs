using System;
using System.Collections.Generic;
using System.Threading;
using GH_MCP_Wasp.Models;
using GH_MCP_Wasp.Utils;
using Newtonsoft.Json.Linq;
using Rhino;

namespace GH_MCP_Wasp.Commands
{
    /// <summary>
    /// Baseline high-level intent commands (kept for compatibility, not
    /// extended for Wasp — see PROTOCOL.md non-goals).
    /// </summary>
    public class IntentCommandHandler
    {
        private static readonly Dictionary<string, string> _componentIdMap = new Dictionary<string, string>();

        public static object CreatePattern(Command command)
        {
            if (!command.Parameters.TryGetValue("description", out object descriptionObj) || descriptionObj == null)
            {
                throw new ArgumentException("Missing required parameter: description");
            }
            string description = descriptionObj.ToString();

            string patternName = IntentRecognizer.RecognizeIntent(description);
            if (string.IsNullOrEmpty(patternName))
            {
                throw new ArgumentException($"Could not recognize intent from description: {description}");
            }

            RhinoApp.WriteLine($"WaspMCP: Recognized intent: {patternName}");

            var (components, connections) = IntentRecognizer.GetPatternDetails(patternName);
            if (components.Count == 0)
            {
                throw new ArgumentException($"Pattern '{patternName}' has no components defined");
            }

            _componentIdMap.Clear();

            foreach (var component in components)
            {
                try
                {
                    var addCommand = new Command(
                        "add_component",
                        new Dictionary<string, object>
                        {
                            { "type", component.Type },
                            { "x", component.X },
                            { "y", component.Y }
                        }
                    );

                    if (component.Settings != null)
                    {
                        foreach (var setting in component.Settings)
                        {
                            addCommand.Parameters[setting.Key] = setting.Value;
                        }
                    }

                    var result = ComponentCommandHandler.AddComponent(addCommand);
                    var id = result == null ? null : JObject.FromObject(result)["id"]?.ToString();
                    if (!string.IsNullOrEmpty(id))
                    {
                        _componentIdMap[component.Id] = id;
                        RhinoApp.WriteLine($"WaspMCP: Created component {component.Type} with ID {id}");
                    }
                    else
                    {
                        RhinoApp.WriteLine($"WaspMCP: Failed to create component {component.Type}");
                    }
                }
                catch (Exception ex)
                {
                    RhinoApp.WriteLine($"WaspMCP: Error creating component {component.Type}: {ex.Message}");
                }

                Thread.Sleep(100);
            }

            foreach (var connection in connections)
            {
                try
                {
                    if (!_componentIdMap.TryGetValue(connection.SourceId, out string sourceId) ||
                        !_componentIdMap.TryGetValue(connection.TargetId, out string targetId))
                    {
                        RhinoApp.WriteLine($"WaspMCP: Could not find component IDs for connection {connection.SourceId} -> {connection.TargetId}");
                        continue;
                    }

                    var connectCommand = new Command(
                        "connect_components",
                        new Dictionary<string, object>
                        {
                            { "sourceId", sourceId },
                            { "sourceParam", connection.SourceParam },
                            { "targetId", targetId },
                            { "targetParam", connection.TargetParam }
                        }
                    );

                    ConnectionCommandHandler.ConnectComponents(connectCommand);
                }
                catch (Exception ex)
                {
                    RhinoApp.WriteLine($"WaspMCP: Error creating connection: {ex.Message}");
                }

                Thread.Sleep(100);
            }

            return new
            {
                Pattern = patternName,
                ComponentCount = components.Count,
                ConnectionCount = connections.Count
            };
        }

        public static object GetAvailablePatterns(Command command)
        {
            IntentRecognizer.Initialize();

            var patterns = new List<string>();
            if (command.Parameters.TryGetValue("query", out object queryObj) && queryObj != null)
            {
                string query = queryObj.ToString();
                string patternName = IntentRecognizer.RecognizeIntent(query);
                if (!string.IsNullOrEmpty(patternName))
                {
                    patterns.Add(patternName);
                }
            }

            return patterns;
        }
    }
}
