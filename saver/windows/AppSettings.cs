using System.Collections.Generic;
using System.IO;
using System.Text.Json;

namespace PinterestSaver;

public class AppSettings
{
    public const string DefaultFeed = "https://www.pinterest.com/pinterest/feed.rss";

    public string Feed { get; set; } = DefaultFeed;
    /// <summary>_pinterest_sess cookie; when set, the personal home feed is shown.</summary>
    public string SessionCookie { get; set; } = "";
    public double Speed { get; set; } = 26.0;
    public bool ShowClock { get; set; } = true;
    /// <summary>Target tile width in DIPs; bigger = fewer, larger columns.</summary>
    public double TileSize { get; set; } = 320.0;
    public bool Clock24h { get; set; } = false;
    /// <summary>Cache file names hidden in the Pin app; never shown or re-downloaded.</summary>
    public List<string> HiddenPins { get; set; } = new();

    private static string SettingsPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
        "PinterestSaver", "settings.json");

    public static AppSettings Load()
    {
        try
        {
            if (File.Exists(SettingsPath))
            {
                var loaded = JsonSerializer.Deserialize<AppSettings>(File.ReadAllText(SettingsPath));
                if (loaded != null) return loaded;
            }
        }
        catch { /* fall through to defaults */ }
        return new AppSettings();
    }

    public void Save()
    {
        var dir = Path.GetDirectoryName(SettingsPath)!;
        Directory.CreateDirectory(dir);
        File.WriteAllText(SettingsPath, JsonSerializer.Serialize(
            this, new JsonSerializerOptions { WriteIndented = true }));
    }
}
