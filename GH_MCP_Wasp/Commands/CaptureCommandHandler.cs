using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Linq;
using GH_MCP_Wasp.Models;
using GH_MCP_Wasp.Utils;
using Grasshopper.GUI.Canvas;
using Rhino;
using Rhino.Display;

namespace GH_MCP_Wasp.Commands
{
    /// <summary>
    /// v0.5 vision commands per PROTOCOL.md:
    /// capture_viewport — named Rhino viewport (default active) to base64 PNG,
    /// optional width/height (clamped to 1920x1080) and zoomExtents.
    /// capture_canvas — Grasshopper canvas snapshot via the canvas hi-res
    /// image API (GH_Canvas.GenerateHiResImageTile), optional region/zoom,
    /// total output clamped to 4 megapixels.
    /// Both run on the UI thread via UiSync.OnUi like every other handler.
    /// </summary>
    public static class CaptureCommandHandler
    {
        // PROTOCOL.md v0.5: hard cap for capture_viewport — clamp, don't error.
        private const int MaxViewportWidth = 1920;
        private const int MaxViewportHeight = 1080;

        // PROTOCOL.md v0.5: capture_canvas total output pixel budget.
        private const double MaxCanvasPixels = 4_000_000;

        // ------------------------------------------------------------------
        // capture_viewport (v0.5)
        // ------------------------------------------------------------------
        public static object CaptureViewport(Command command)
        {
            string viewportName = command.HasParameter("viewport")
                ? command.GetParameter<string>("viewport") : null;
            int? width = command.HasParameter("width")
                ? (int?)command.GetParameter<int>("width") : null;
            int? height = command.HasParameter("height")
                ? (int?)command.GetParameter<int>("height") : null;
            bool zoomExtents = command.HasParameter("zoomExtents")
                && command.GetParameter<bool>("zoomExtents");

            return UiSync.OnUi<object>(() =>
            {
                var rdoc = RhinoDoc.ActiveDoc;
                if (rdoc == null)
                {
                    throw new InvalidOperationException("No active Rhino document");
                }

                RhinoView view;
                if (string.IsNullOrEmpty(viewportName))
                {
                    view = rdoc.Views.ActiveView;
                    if (view == null)
                    {
                        throw new InvalidOperationException("No active Rhino view");
                    }
                }
                else
                {
                    // Case-insensitive lookup by main viewport name.
                    view = rdoc.Views.Find(viewportName, false);
                    if (view == null)
                    {
                        var available = rdoc.Views
                            .Select(v => v.ActiveViewport.Name)
                            .ToList();
                        throw new ArgumentException(
                            $"Viewport '{viewportName}' not found; available: {string.Join(", ", available)}");
                    }
                }

                if (zoomExtents)
                {
                    // Deliberately NOT restoring the camera afterwards
                    // (PROTOCOL.md v0.5): callers wanting a fixed view manage
                    // the camera themselves.
                    view.ActiveViewport.ZoomExtents();
                    view.Redraw();
                }

                // Default to the viewport's current pixel size; clamp
                // (never error) to the 1920x1080 hard cap.
                Size current = view.ActiveViewport.Size;
                int w = Clamp(width ?? current.Width, 1, MaxViewportWidth);
                int h = Clamp(height ?? current.Height, 1, MaxViewportHeight);

                using (Bitmap bitmap = view.CaptureToBitmap(new Size(w, h)))
                {
                    if (bitmap == null)
                    {
                        throw new InvalidOperationException(
                            $"Capture of viewport '{view.ActiveViewport.Name}' failed");
                    }

                    return new Dictionary<string, object>
                    {
                        { "imageBase64", ToPngBase64(bitmap) },
                        { "viewport", view.ActiveViewport.Name },
                        { "width", bitmap.Width },
                        { "height", bitmap.Height }
                    };
                }
            });
        }

        // ------------------------------------------------------------------
        // capture_canvas (v0.5)
        // ------------------------------------------------------------------
        public static object CaptureCanvas(Command command)
        {
            double zoom = command.HasParameter("zoom")
                ? command.GetParameter<double>("zoom") : 1.0;
            var region = command.HasParameter("region")
                ? command.GetParameter<List<double>>("region") : null;

            if (double.IsNaN(zoom) || double.IsInfinity(zoom) || zoom <= 0.0)
            {
                throw new ArgumentException($"zoom must be a positive number: {zoom}");
            }
            if (region != null && region.Count != 4)
            {
                throw new ArgumentException("region must be [x, y, w, h] in canvas coordinates");
            }

            return UiSync.OnUi<object>(() =>
            {
                var canvas = Grasshopper.Instances.ActiveCanvas;
                if (canvas == null)
                {
                    throw new InvalidOperationException("No active Grasshopper canvas");
                }
                var doc = CanvasUtils.RequireDocument();

                RectangleF rect;
                if (region != null)
                {
                    rect = new RectangleF(
                        (float)region[0], (float)region[1],
                        (float)region[2], (float)region[3]);
                }
                else
                {
                    // null region = full document bounds, padded slightly so
                    // edge components aren't clipped at the border.
                    rect = doc.BoundingBox(false);
                    rect.Inflate(10f, 10f);
                }

                if (rect.Width <= 0f || rect.Height <= 0f)
                {
                    throw new ArgumentException(
                        region != null
                            ? "region width/height must be positive"
                            : "document bounds are empty; nothing to capture");
                }

                // Clamp total output to <= 4 MP: floor() keeps the guarantee
                // exact after the sqrt scale-down.
                double requested = (double)rect.Width * zoom * (double)rect.Height * zoom;
                double scale = zoom;
                if (requested > MaxCanvasPixels)
                {
                    scale *= Math.Sqrt(MaxCanvasPixels / requested);
                }
                int outW = Math.Max(1, (int)Math.Floor(rect.Width * scale));
                int outH = Math.Max(1, (int)Math.Floor(rect.Height * scale));

                // Grasshopper's hi-res image API: describe the wanted
                // projection with a GH_Viewport, then let the canvas render
                // that tile off-screen.
                var viewport = new GH_Viewport
                {
                    Width = outW,
                    Height = outH,
                    Zoom = (float)scale,
                    MidPoint = new PointF(
                        rect.X + rect.Width * 0.5f,
                        rect.Y + rect.Height * 0.5f)
                };
                viewport.ComputeProjection();

                using (Bitmap bitmap = canvas.GenerateHiResImageTile(viewport, GH_Skin.canvas_back))
                {
                    if (bitmap == null)
                    {
                        throw new InvalidOperationException("Canvas capture failed");
                    }

                    return new Dictionary<string, object>
                    {
                        { "imageBase64", ToPngBase64(bitmap) },
                        { "width", bitmap.Width },
                        { "height", bitmap.Height }
                    };
                }
            });
        }

        // ------------------------------------------------------------------
        // helpers
        // ------------------------------------------------------------------
        private static int Clamp(int value, int min, int max)
        {
            return value < min ? min : (value > max ? max : value);
        }

        private static string ToPngBase64(Bitmap bitmap)
        {
            using (var stream = new MemoryStream())
            {
                bitmap.Save(stream, ImageFormat.Png);
                return Convert.ToBase64String(stream.ToArray());
            }
        }
    }
}
