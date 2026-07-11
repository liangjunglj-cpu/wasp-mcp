using System;
using System.Collections.Generic;
using GH_MCP_Wasp.Models;
using Newtonsoft.Json.Linq;
using Rhino.Geometry;

namespace GH_MCP_Wasp.Commands
{
    /// <summary>
    /// Baseline geometry commands (forked unchanged from GH_MCP).
    /// These are pure computations; they never touch GH_Document.
    /// </summary>
    public static class GeometryCommandHandler
    {
        public static object CreatePoint(Command command)
        {
            double x = command.GetParameter<double>("x");
            double y = command.GetParameter<double>("y");
            double z = command.GetParameter<double>("z");

            Point3d point = new Point3d(x, y, z);

            return new
            {
                id = Guid.NewGuid().ToString(),
                x = point.X,
                y = point.Y,
                z = point.Z
            };
        }

        public static object CreateCurve(Command command)
        {
            var pointsData = command.GetParameter<JArray>("points");

            if (pointsData == null || pointsData.Count < 2)
            {
                throw new ArgumentException("At least 2 points are required to create a curve");
            }

            List<Point3d> points = new List<Point3d>();
            foreach (var pointData in pointsData)
            {
                double x = pointData["x"].Value<double>();
                double y = pointData["y"].Value<double>();
                double z = pointData["z"]?.Value<double>() ?? 0.0;

                points.Add(new Point3d(x, y, z));
            }

            Curve curve;
            if (points.Count == 2)
            {
                curve = new LineCurve(points[0], points[1]);
            }
            else
            {
                curve = Curve.CreateInterpolatedCurve(points, 3);
            }

            return new
            {
                id = Guid.NewGuid().ToString(),
                pointCount = points.Count,
                length = curve.GetLength()
            };
        }

        public static object CreateCircle(Command command)
        {
            var centerData = command.GetParameter<JObject>("center");
            double radius = command.GetParameter<double>("radius");

            if (centerData == null)
            {
                throw new ArgumentException("Center point is required");
            }

            if (radius <= 0)
            {
                throw new ArgumentException("Radius must be greater than 0");
            }

            double x = centerData["x"].Value<double>();
            double y = centerData["y"].Value<double>();
            double z = centerData["z"]?.Value<double>() ?? 0.0;

            Point3d center = new Point3d(x, y, z);
            Circle circle = new Circle(center, radius);

            return new
            {
                id = Guid.NewGuid().ToString(),
                center = new { x = center.X, y = center.Y, z = center.Z },
                radius = circle.Radius,
                circumference = circle.Circumference
            };
        }
    }
}
