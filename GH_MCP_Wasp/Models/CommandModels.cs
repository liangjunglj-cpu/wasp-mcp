using System;
using System.Collections.Generic;
using Newtonsoft.Json;

namespace GH_MCP_Wasp.Models
{
    /// <summary>
    /// Command sent from the Python MCP server to Grasshopper.
    /// Wire shape: {"type": "<command>", "parameters": {...}}
    /// </summary>
    public class Command
    {
        [JsonProperty("type")]
        public string Type { get; set; }

        [JsonProperty("parameters")]
        public Dictionary<string, object> Parameters { get; set; }

        /// <summary>
        /// Optional shared secret (top-level "token", PROTOCOL.md v0.5).
        /// Checked by the TCP layer before dispatch when the WaspMCP
        /// component's Token input is non-empty. Never logged.
        /// </summary>
        [JsonProperty("token")]
        public string Token { get; set; }

        public Command(string type, Dictionary<string, object> parameters = null)
        {
            Type = type;
            Parameters = parameters ?? new Dictionary<string, object>();
        }

        /// <summary>
        /// Get a typed parameter value. Returns default(T) when absent or unconvertible.
        /// </summary>
        public T GetParameter<T>(string name)
        {
            if (Parameters != null && Parameters.TryGetValue(name, out object value) && value != null)
            {
                if (value is T typedValue)
                {
                    return typedValue;
                }

                try
                {
                    return (T)Convert.ChangeType(value, typeof(T));
                }
                catch
                {
                    if (value is Newtonsoft.Json.Linq.JObject jObject)
                    {
                        try { return jObject.ToObject<T>(); } catch { }
                    }
                    if (value is Newtonsoft.Json.Linq.JArray jArray)
                    {
                        try { return jArray.ToObject<T>(); } catch { }
                    }
                }
            }
            return default;
        }

        /// <summary>
        /// True when the parameter is present and non-null.
        /// </summary>
        public bool HasParameter(string name)
        {
            return Parameters != null
                && Parameters.TryGetValue(name, out object value)
                && value != null
                && !(value is Newtonsoft.Json.Linq.JValue jv && jv.Type == Newtonsoft.Json.Linq.JTokenType.Null);
        }
    }

    /// <summary>
    /// Response sent back to the Python MCP server.
    /// Wire shape (per PROTOCOL.md): {"success": true, "result": {...}} or
    /// {"success": false, "error": "..."}
    /// </summary>
    public class Response
    {
        [JsonProperty("success")]
        public bool Success { get; set; }

        [JsonProperty("result", NullValueHandling = NullValueHandling.Ignore)]
        public object Result { get; set; }

        [JsonProperty("error", NullValueHandling = NullValueHandling.Ignore)]
        public string Error { get; set; }

        /// <summary>
        /// Additive array riding next to "error" (PROTOCOL.md v0.5
        /// "ambiguous_component_type"): the proxies that tied at the winning
        /// resolution tier, each {"name","nickname","guid","category"}.
        /// Omitted from the wire when null.
        /// </summary>
        [JsonProperty("candidates", NullValueHandling = NullValueHandling.Ignore)]
        public object Candidates { get; set; }

        public static Response Ok(object result = null)
        {
            return new Response { Success = true, Result = result };
        }

        public static Response CreateError(string errorMessage, object candidates = null)
        {
            return new Response { Success = false, Result = null, Error = errorMessage, Candidates = candidates };
        }
    }
}
