using WinForms = System.Windows.Forms;

namespace PinterestSaver;

/// <summary>
/// Windows screensaver entry point. Windows launches the .scr with:
///   /s          — run fullscreen
///   /c[:hwnd]   — show the configuration dialog
///   /p hwnd     — render a tiny preview into the given window (not supported)
/// </summary>
internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        var mode = args.Length > 0 ? args[0].ToLowerInvariant() : "/s";

        if (mode.StartsWith("/c"))
        {
            WinForms.Application.EnableVisualStyles();
            WinForms.Application.SetCompatibleTextRenderingDefault(false);
            WinForms.Application.SetHighDpiMode(WinForms.HighDpiMode.PerMonitorV2);
            WinForms.Application.Run(new SettingsForm());
            return;
        }
        if (mode.StartsWith("/p"))
            return; // no mini-preview; the Settings dialog preview stays black

        var settings = AppSettings.Load();
        var loader = new FeedLoader();
        loader.Start(settings);

        var app = new System.Windows.Application
        {
            ShutdownMode = System.Windows.ShutdownMode.OnExplicitShutdown
        };
        foreach (var screen in WinForms.Screen.AllScreens)
            new SaverWindow(screen, loader, settings, screen.Primary).Show();
        app.Run();
    }
}
