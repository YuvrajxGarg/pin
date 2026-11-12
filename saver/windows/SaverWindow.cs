using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Media.Effects;
using System.Windows.Media.Imaging;
using WinFormsScreen = System.Windows.Forms.Screen;
using Rect = System.Windows.Shapes.Rectangle;
using MouseEventArgs = System.Windows.Input.MouseEventArgs;
using Point = System.Windows.Point;
using Color = System.Windows.Media.Color;
using FontFamily = System.Windows.Media.FontFamily;
using Cursors = System.Windows.Input.Cursors;
using Size = System.Windows.Size;

namespace PinterestSaver;

/// <summary>
/// One fullscreen WPF window per monitor. WPF's compositor is GPU-backed and
/// vsync-locked (CompositionTarget.Rendering fires once per refresh), which
/// keeps the scroll smooth where a GDI+ timer loop jitters. Layout happens in
/// DIPs, so tiles come out the same physical size on high-DPI laptop panels
/// and external monitors.
/// </summary>
public class SaverWindow : Window
{
    private class Tile
    {
        public required FrameworkElement Element;
        public required BitmapSource Source;
        public double Y;
        public double Height;
    }

    private class Column
    {
        public double X;
        public double Width;
        public double SpeedFactor = 1;
        public readonly List<Tile> Tiles = new();
    }

    private const double Gutter = 14;
    private const double Corner = 12;
    private const int MinImagesToStart = 8;

    [DllImport("user32.dll")]
    private static extern bool SetWindowPos(IntPtr hWnd, IntPtr insertAfter,
        int x, int y, int cx, int cy, uint flags);

    private readonly FeedLoader _loader;
    private readonly AppSettings _settings;
    private readonly bool _showClock;
    private readonly System.Drawing.Rectangle _pixelBounds;
    private readonly Canvas _canvas = new();
    private readonly List<Column> _columns = new();
    private readonly Stopwatch _stopwatch = Stopwatch.StartNew();
    /// <summary>Images currently visible in this window; the shared bag skips these.</summary>
    private readonly HashSet<BitmapSource> _onScreen = new();
    private double _lastFrame;
    private Point? _initialMouse;
    private TextBlock? _statusText;
    private TextBlock? _timeText;
    private TextBlock? _dateText;
    private string _lastClockString = "";

    public SaverWindow(WinFormsScreen screen, FeedLoader loader, AppSettings settings, bool isPrimary)
    {
        _loader = loader;
        _settings = settings;
        _showClock = settings.ShowClock && isPrimary;
        _pixelBounds = screen.Bounds;

        WindowStyle = WindowStyle.None;
        ResizeMode = ResizeMode.NoResize;
        WindowStartupLocation = WindowStartupLocation.Manual;
        ShowInTaskbar = false;
        Topmost = true;
        Cursor = Cursors.None;
        Background = new SolidColorBrush(Color.FromRgb(15, 15, 15));
        // Rough pre-show position so the window opens on the right monitor;
        // OnSourceInitialized snaps it to exact pixel bounds.
        Left = _pixelBounds.X;
        Top = _pixelBounds.Y;
        Width = 100;
        Height = 100;
        Content = _canvas;

        KeyDown += (_, _) => System.Windows.Application.Current.Shutdown();
        MouseDown += (_, _) => System.Windows.Application.Current.Shutdown();
        MouseMove += OnAnyMouseMove;
        CompositionTarget.Rendering += OnRendering;
        Closed += (_, _) => CompositionTarget.Rendering -= OnRendering;
    }

    protected override void OnSourceInitialized(EventArgs e)
    {
        base.OnSourceInitialized(e);
        const uint SWP_SHOWWINDOW = 0x0040;
        var hwnd = new WindowInteropHelper(this).Handle;
        SetWindowPos(hwnd, new IntPtr(-1) /* HWND_TOPMOST */,
            _pixelBounds.X, _pixelBounds.Y, _pixelBounds.Width, _pixelBounds.Height,
            SWP_SHOWWINDOW);
    }

    private void OnAnyMouseMove(object? sender, MouseEventArgs e)
    {
        var p = e.GetPosition(this);
        if (_initialMouse == null) { _initialMouse = p; return; }
        if (Math.Abs(p.X - _initialMouse.Value.X) + Math.Abs(p.Y - _initialMouse.Value.Y) > 12)
            System.Windows.Application.Current.Shutdown();
    }

    // MARK: render loop (fires once per display refresh)

    private void OnRendering(object? sender, EventArgs e)
    {
        var now = _stopwatch.Elapsed.TotalSeconds;
        var dt = Math.Clamp(now - _lastFrame, 0, 0.2);
        _lastFrame = now;

        var w = _canvas.ActualWidth;
        var h = _canvas.ActualHeight;
        if (w < 10 || h < 10) return;

        if (_columns.Count == 0)
        {
            if (_loader.Count >= RequiredImagesToStart(w, h))
            {
                HideStatus();
                BuildColumns(w, h);
            }
            else
            {
                ShowStatus(w, h);
            }
        }

        var baseSpeed = _settings.Speed;
        foreach (var col in _columns)
        {
            var dy = baseSpeed * col.SpeedFactor * dt;
            foreach (var t in col.Tiles)
            {
                t.Y -= dy;
                Canvas.SetTop(t.Element, t.Y);
            }
            while (col.Tiles.Count > 0 && col.Tiles[0].Y + col.Tiles[0].Height < -40)
            {
                _onScreen.Remove(col.Tiles[0].Source);
                _canvas.Children.Remove(col.Tiles[0].Element);
                col.Tiles.RemoveAt(0);
            }
            Refill(col, h);
        }

        if (_showClock) UpdateClock(h);
    }

    /// <summary>Don't build the grid until the pool can roughly fill the
    /// screen without repeats — a large monitor shows 40+ tiles, and starting
    /// at 8 images means the same few pins everywhere. After a 10s grace
    /// period, start with whatever arrived so a slow network never blanks
    /// the saver.</summary>
    private int RequiredImagesToStart(double w, double h)
    {
        if (_stopwatch.Elapsed.TotalSeconds > 10) return MinImagesToStart;
        var target = Math.Max(_settings.TileSize, 120);
        var count = Math.Max(2, (int)(w / target));
        var width = (w - Gutter * (count + 1)) / count;
        var tilesPerColumn = (int)(h / (width * 1.15 + Gutter)) + 2;
        return Math.Max(MinImagesToStart, Math.Min(count * tilesPerColumn, 60));
    }

    private void BuildColumns(double w, double h)
    {
        var target = Math.Max(_settings.TileSize, 120);
        var count = Math.Max(2, (int)(w / target));
        var width = (w - Gutter * (count + 1)) / count;
        for (int i = 0; i < count; i++)
        {
            var col = new Column
            {
                Width = width,
                X = Gutter + i * (width + Gutter),
                SpeedFactor = 0.85 + (i * 7919 % 100) / 100.0 * 0.3
            };
            double y = -(i * 4831 % 120);
            while (y < h + 40)
            {
                var tile = MakeTile(col, y);
                if (tile == null) break;
                col.Tiles.Add(tile);
                y += tile.Height + Gutter;
            }
            _columns.Add(col);
        }
    }

    private void Refill(Column col, double h)
    {
        var bottom = col.Tiles.Count > 0
            ? col.Tiles[^1].Y + col.Tiles[^1].Height + Gutter
            : 0;
        while (bottom < h + 40)
        {
            var tile = MakeTile(col, bottom);
            if (tile == null) break;
            col.Tiles.Add(tile);
            bottom += tile.Height + Gutter;
        }
    }

    private Tile? MakeTile(Column col, double y)
    {
        var src = _loader.NextImage(_onScreen);
        if (src == null || src.PixelWidth <= 0 || src.PixelHeight <= 0) return null;
        var height = Math.Clamp(col.Width * src.PixelHeight / src.PixelWidth,
                                col.Width * 0.55, col.Width * 2.0);

        var brush = new ImageBrush(src) { Stretch = Stretch.UniformToFill };
        brush.Freeze();
        var rect = new Rect
        {
            Width = col.Width,
            Height = height,
            RadiusX = Corner,
            RadiusY = Corner,
            Fill = brush
        };
        RenderOptions.SetBitmapScalingMode(rect, BitmapScalingMode.Linear);
        Canvas.SetLeft(rect, col.X);
        Canvas.SetTop(rect, y);
        _canvas.Children.Add(rect);
        _onScreen.Add(src);
        return new Tile { Element = rect, Source = src, Y = y, Height = height };
    }

    // MARK: status + clock overlays

    private void ShowStatus(double w, double h)
    {
        if (_statusText == null)
        {
            _statusText = new TextBlock
            {
                FontSize = 20,
                Foreground = new SolidColorBrush(Color.FromRgb(140, 140, 140))
            };
            _canvas.Children.Add(_statusText);
        }
        _statusText.Text = _loader.Status;
        _statusText.Measure(new Size(w, h));
        Canvas.SetLeft(_statusText, (w - _statusText.DesiredSize.Width) / 2);
        Canvas.SetTop(_statusText, (h - _statusText.DesiredSize.Height) / 2);
    }

    private void HideStatus()
    {
        if (_statusText != null)
        {
            _canvas.Children.Remove(_statusText);
            _statusText = null;
        }
    }

    private void UpdateClock(double h)
    {
        var now = DateTime.Now;
        var stamp = now.ToString(_settings.Clock24h ? "H:mm" : "h:mm");
        if (stamp == _lastClockString && _timeText != null) return;
        _lastClockString = stamp;

        if (_timeText == null)
        {
            var shadow = new DropShadowEffect { BlurRadius = 18, ShadowDepth = 0, Opacity = 0.8 };
            _timeText = new TextBlock
            {
                FontFamily = new FontFamily("Segoe UI Light, Segoe UI"),
                FontSize = 84,
                Foreground = new SolidColorBrush(Color.FromArgb(235, 255, 255, 255)),
                Effect = shadow
            };
            _dateText = new TextBlock
            {
                FontFamily = new FontFamily("Segoe UI"),
                FontSize = 20,
                Foreground = new SolidColorBrush(Color.FromArgb(190, 255, 255, 255)),
                Effect = shadow
            };
            _canvas.Children.Add(_timeText);
            _canvas.Children.Add(_dateText);
        }

        _timeText.Text = stamp;
        _dateText!.Text = now.ToString("ddd d MMM");
        Canvas.SetLeft(_timeText, 48);
        Canvas.SetTop(_timeText, h - 48 - 36 - 110);
        Canvas.SetLeft(_dateText, 54);
        Canvas.SetTop(_dateText, h - 48 - 30);
    }
}
