using System;
using System.Collections.Generic;
using System.Linq;
using GH_MCP_Wasp.Models;
using GH_MCP_Wasp.Utils;
using Grasshopper.Kernel;
using Grasshopper.Kernel.Parameters;

namespace GH_MCP_Wasp.Commands
{
    /// <summary>
    /// Baseline connection commands (connect_components, get_connections,
    /// validate_connection). Semantics forked from GH_MCP; threading upgraded
    /// to UiSync.OnUi.
    /// </summary>
    public static class ConnectionCommandHandler
    {
        public static object ConnectComponents(Command command)
        {
            string sourceId = command.GetParameter<string>("sourceId");
            string targetId = command.GetParameter<string>("targetId");

            if (string.IsNullOrEmpty(sourceId))
            {
                throw new ArgumentException("Missing required parameter: sourceId");
            }
            if (string.IsNullOrEmpty(targetId))
            {
                throw new ArgumentException("Missing required parameter: targetId");
            }

            string sourceParam = null;
            if (command.HasParameter("sourceParam"))
            {
                sourceParam = FuzzyMatcher.GetClosestParameterName(command.GetParameter<string>("sourceParam"));
            }
            string targetParam = null;
            if (command.HasParameter("targetParam"))
            {
                targetParam = FuzzyMatcher.GetClosestParameterName(command.GetParameter<string>("targetParam"));
            }

            int? sourceParamIndex = command.HasParameter("sourceParamIndex")
                ? (int?)command.GetParameter<int>("sourceParamIndex") : null;
            int? targetParamIndex = command.HasParameter("targetParamIndex")
                ? (int?)command.GetParameter<int>("targetParamIndex") : null;

            return UiSync.OnUi<object>(() =>
            {
                var doc = CanvasUtils.RequireDocument();

                var sourceComponent = CanvasUtils.RequireObject(doc, sourceId);
                var targetComponent = CanvasUtils.RequireObject(doc, targetId);

                if (sourceComponent is IGH_Param sp && sp.Kind == GH_ParamKind.input)
                {
                    throw new ArgumentException("Source component cannot be an input parameter");
                }
                if (targetComponent is IGH_Param tp && tp.Kind == GH_ParamKind.output)
                {
                    throw new ArgumentException("Target component cannot be an output parameter");
                }

                IGH_Param sourceParameter = CanvasUtils.ResolveParam(sourceComponent, sourceParam, sourceParamIndex, isInput: false);
                IGH_Param targetParameter = CanvasUtils.ResolveParam(targetComponent, targetParam, targetParamIndex, isInput: true);

                if (!AreParametersCompatible(sourceParameter, targetParameter))
                {
                    throw new ArgumentException(
                        $"Parameters are not compatible: {sourceParameter.GetType().Name} cannot connect to {targetParameter.GetType().Name}");
                }

                // Baseline behavior: connect_components REPLACES existing sources.
                // (connect_by_name appends instead; see WaspCommandHandler.)
                if (targetParameter.SourceCount > 0)
                {
                    targetParameter.RemoveAllSources();
                }

                targetParameter.AddSource(sourceParameter);

                CanvasUtils.MaybeExpire(command, doc, targetComponent);

                return new
                {
                    message = "Connection created successfully",
                    sourceId = sourceComponent.InstanceGuid.ToString(),
                    targetId = targetComponent.InstanceGuid.ToString(),
                    sourceParam = sourceParameter.Name,
                    targetParam = targetParameter.Name,
                    sourceType = sourceParameter.GetType().Name,
                    targetType = targetParameter.GetType().Name
                };
            });
        }

        public static object GetConnections(Command command)
        {
            return UiSync.OnUi<object>(() =>
            {
                var doc = CanvasUtils.RequireDocument();
                return CanvasUtils.BuildConnectionList(doc);
            });
        }

        public static object ValidateConnection(Command command)
        {
            string sourceId = command.GetParameter<string>("sourceId");
            string targetId = command.GetParameter<string>("targetId");

            if (string.IsNullOrEmpty(sourceId) || string.IsNullOrEmpty(targetId))
            {
                throw new ArgumentException("sourceId and targetId are required");
            }

            string sourceParam = command.HasParameter("sourceParam")
                ? command.GetParameter<string>("sourceParam") : null;
            string targetParam = command.HasParameter("targetParam")
                ? command.GetParameter<string>("targetParam") : null;

            return UiSync.OnUi<object>(() =>
            {
                var doc = CanvasUtils.RequireDocument();

                try
                {
                    var sourceComponent = CanvasUtils.RequireObject(doc, sourceId);
                    var targetComponent = CanvasUtils.RequireObject(doc, targetId);

                    IGH_Param sourceParameter = CanvasUtils.ResolveParam(sourceComponent, sourceParam, null, isInput: false);
                    IGH_Param targetParameter = CanvasUtils.ResolveParam(targetComponent, targetParam, null, isInput: true);

                    if (sourceParameter.Kind == GH_ParamKind.input && sourceComponent is IGH_Param)
                    {
                        return new { valid = false, reason = "Source is an input parameter" };
                    }

                    bool compatible = AreParametersCompatible(sourceParameter, targetParameter);
                    return new
                    {
                        valid = compatible,
                        reason = compatible ? "Connection is valid" :
                            $"{sourceParameter.GetType().Name} cannot connect to {targetParameter.GetType().Name}",
                        sourceParam = sourceParameter.Name,
                        targetParam = targetParameter.Name
                    };
                }
                catch (ArgumentException ex)
                {
                    return new { valid = false, reason = ex.Message };
                }
            });
        }

        /// <summary>
        /// Basic compatibility check (forked from baseline, simplified).
        /// Grasshopper performs its own runtime conversion, so this errs on
        /// the side of allowing the connection.
        /// </summary>
        private static bool AreParametersCompatible(IGH_Param source, IGH_Param target)
        {
            if (source.GetType() == target.GetType())
            {
                return true;
            }

            bool isSourceNumeric = IsNumericType(source);
            bool isTargetNumeric = IsNumericType(target);
            if (isSourceNumeric && isTargetNumeric)
            {
                return true;
            }

            // Default: allow, Grasshopper decides at solve time.
            return true;
        }

        private static bool IsNumericType(IGH_Param param)
        {
            return param is Param_Integer ||
                   param is Param_Number ||
                   param is Param_Time;
        }
    }
}
