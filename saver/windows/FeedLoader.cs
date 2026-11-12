using System.IO;
using System.Net;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Windows.Media.Imaging;

namespace PinterestSaver;

/// <summary>
/// Fetches pin image URLs from a Pinterest RSS feed or, with a session
/// cookie, the personal home feed; downloads them into a per-source disk
/// cache and exposes the decoded images as a growing pool.
/// </summary>
public class FeedLoader
{
    private const string UserAgent =
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36";

    private static readonly Regex PinImageRegex = new(
        @"https://i\.pinimg\.com/(?:[0-9]+x|originals)/[A-Za-z0-9/_\-]+\.(?:jpg|jpeg|png|gif|webp)",
        RegexOptions.Compiled);

    private readonly HttpClient _http;
    private readonly object _lock = new();
    private readonly List<BitmapSource> _pool = new();
    // Shuffle bag: deals every pooled image once per cycle across all
    // columns/monitors so the same pin can't appear twice at once.
    private readonly List<BitmapSource> _bag = new();
    private readonly Random _rng = new();
    private readonly HashSet<string> _seen = new();
    // Cache files already turned into pool images this session.
    private readonly HashSet<string> _deliveredFiles = new();
    private readonly SemaphoreSlim _downloadSlots = new(6);
    private readonly string _cacheRoot;
    private string _cacheDir;
    private string _status = "Loading pins…";
    private HashSet<string> _hidden = new(StringComparer.OrdinalIgnoreCase);

    public FeedLoader()
    {
        _http = new HttpClient(new HttpClientHandler
        {
            AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate,
            UseCookies = false
        });
        _http.Timeout = TimeSpan.FromSeconds(20);
        _http.DefaultRequestHeaders.TryAddWithoutValidation("User-Agent", UserAgent);

        _cacheRoot = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "PinterestSaver", "cache");
        _cacheDir = _cacheRoot;
        Directory.CreateDirectory(_cacheRoot);
    }

    public string Status { get { lock (_lock) return _status; } }
    public int Count { get { lock (_lock) return _pool.Count; } }

    /// <summary>Deal the next image, preferring one not currently visible.</summary>
    public BitmapSource? NextImage(HashSet<BitmapSource> excluding)
    {
        lock (_lock)
        {
            if (_pool.Count == 0) return null;
            if (_bag.Count == 0)
                _bag.AddRange(_pool.OrderBy(_ => _rng.Next()));
            for (int i = 0; i < _bag.Count; i++)
            {
                if (excluding.Contains(_bag[i])) continue;
                var img = _bag[i];
                _bag.RemoveAt(i);
                return img;
            }
            // Pool smaller than visible tile count: repeats are unavoidable.
            var fallback = _bag[0];
            _bag.RemoveAt(0);
            return fallback;
        }
    }

    private void SetStatus(string s) { lock (_lock) _status = s; }

    private void Deliver(BitmapSource image, bool fresh)
    {
        lock (_lock)
        {
            _pool.Add(image);
            // Periodic refreshes keep adding pins; cap the pool so a long
            // run doesn't grow memory without bound (oldest rotate out).
            if (_pool.Count > 150)
            {
                var old = _pool[0];
                _pool.RemoveAt(0);
                _bag.Remove(old);
            }
            if (fresh)
                // New pins jump the queue: visible within the next few
                // tiles instead of after a full cycle through the pool.
                _bag.Insert(Math.Min(_rng.Next(0, 9), _bag.Count), image);
            else
                _bag.Add(image);
        }
    }

    private static string Md5Hex(string s) =>
        Convert.ToHexString(MD5.HashData(Encoding.UTF8.GetBytes(s))).ToLowerInvariant();

    /// <summary>Bare _pinterest_sess values are base64 and contain '='; only an
    /// explicit name marks an already-complete cookie string.</summary>
    public static string CookieHeader(string raw) =>
        raw.Contains("_pinterest_sess=") ? raw : "_pinterest_sess=" + raw;

    public static string? NormalizeFeedUrl(string raw)
    {
        var s = raw.Trim();
        if (s.Length == 0) return null;
        if (s.EndsWith(".rss"))
            return s.StartsWith("http") ? s : "https://" + s;

        string path = s;
        if (Uri.TryCreate(s, UriKind.Absolute, out var uri) && uri.Host.Contains("pinterest."))
            path = uri.AbsolutePath;
        var parts = path.Trim('/').Split('/', StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length == 1) return $"https://www.pinterest.com/{parts[0]}/feed.rss";
        if (parts.Length >= 2) return $"https://www.pinterest.com/{parts[0]}/{parts[1]}.rss";
        return null;
    }

    public static List<string> ExtractImageUrls(string text)
    {
        var seen = new HashSet<string>();
        var result = new List<string>();
        foreach (Match m in PinImageRegex.Matches(text.Replace("\\/", "/")))
            if (seen.Add(m.Value)) result.Add(m.Value);
        return result;
    }

    private string _cookie = "";
    private string? _feedUrl;
    private System.Threading.Timer? _refreshTimer;

    public void Start(AppSettings settings)
    {
        _cookie = settings.SessionCookie.Trim();
        _hidden = new HashSet<string>(settings.HiddenPins ?? new List<string>(), StringComparer.OrdinalIgnoreCase);
        _feedUrl = NormalizeFeedUrl(settings.Feed);
        var sourceKey = _cookie.Length > 0 ? "home" : Md5Hex(_feedUrl ?? settings.Feed);
        _cacheDir = Path.Combine(_cacheRoot, sourceKey);
        Directory.CreateDirectory(_cacheDir);

        if (_cookie.Length == 0 && _feedUrl == null)
        {
            SetStatus("Invalid feed: " + settings.Feed);
            return;
        }

        Task.Run(LoadCachedImages);
        Task.Run(async () =>
        {
            // Startup burst: each home-feed call returns a different sample,
            // so a few spaced calls seed the grid with real variety.
            await FetchOnce();
            if (_cookie.Length > 0)
            {
                for (int i = 0; i < 2; i++)
                {
                    await Task.Delay(TimeSpan.FromSeconds(6));
                    await FetchOnce();
                }
            }
        });
        // Keep new pins arriving during long runs.
        _refreshTimer = new System.Threading.Timer(_ => Task.Run(FetchOnce), null,
            TimeSpan.FromMinutes(10), TimeSpan.FromMinutes(10));
    }

    private async Task FetchOnce()
    {
        try
        {
            if (_cookie.Length > 0) await FetchHomeFeed(_cookie);
            else if (_feedUrl != null) await FetchRss(_feedUrl);
        }
        catch (Exception ex)
        {
            SetStatus("Feed error: " + ex.Message);
        }
    }

    private void LoadCachedImages()
    {
        var files = Directory.Exists(_cacheDir)
            ? Directory.GetFiles(_cacheDir, "*.img")
            : Array.Empty<string>();
        var rng = new Random();
        foreach (var file in files.Where(f => !_hidden.Contains(Path.GetFileName(f))).OrderBy(_ => rng.Next()).Take(40))
        {
            MarkDelivered(file);
            var img = DecodeImage(File.ReadAllBytes(file));
            if (img != null) Deliver(img, fresh: false);
        }
    }

    private void MarkDelivered(string file)
    {
        lock (_lock) _deliveredFiles.Add(Path.GetFileName(file));
    }

    private bool WasDelivered(string file)
    {
        lock (_lock) return _deliveredFiles.Contains(Path.GetFileName(file));
    }

    private static BitmapSource? DecodeImage(byte[] bytes)
    {
        try
        {
            using var ms = new MemoryStream(bytes);
            var bmp = new BitmapImage();
            bmp.BeginInit();
            bmp.CacheOption = BitmapCacheOption.OnLoad;
            bmp.DecodePixelWidth = 640; // plenty for a grid column; caps memory
            bmp.StreamSource = ms;
            bmp.EndInit();
            bmp.Freeze(); // usable from any thread once frozen
            return bmp;
        }
        catch { return null; }
    }

    private async Task FetchRss(string feedUrl)
    {
        var xml = await _http.GetStringAsync(feedUrl);
        var urls = ExtractImageUrls(xml);
        if (urls.Count == 0) { SetStatus("No pins found in feed"); return; }
        await DownloadAll(urls);
    }

    private HttpRequestMessage AuthedRequest(string url, string cookie, bool json)
    {
        var req = new HttpRequestMessage(HttpMethod.Get, url);
        req.Headers.TryAddWithoutValidation("Cookie", CookieHeader(cookie));
        req.Headers.TryAddWithoutValidation("Referer", "https://www.pinterest.com/");
        req.Headers.TryAddWithoutValidation("Accept", json ? "application/json" : "text/html");
        if (json)
        {
            req.Headers.TryAddWithoutValidation("X-Requested-With", "XMLHttpRequest");
            // Without this header Pinterest's resource router rejects the call.
            req.Headers.TryAddWithoutValidation("x-pinterest-pws-handler", "www/index.js");
            req.Headers.TryAddWithoutValidation("x-pinterest-source-url", "/");
            req.Headers.TryAddWithoutValidation("x-pinterest-appstate", "active");
        }
        return req;
    }

    private async Task FetchHomeFeed(string cookie)
    {
        const string options =
            "{\"options\":{\"field_set_key\":\"react_grid_pin\",\"in_nux\":false,\"prependPartner\":false},\"context\":{}}";
        var url = "https://www.pinterest.com/resource/UserHomefeedResource/get/?source_url=%2F&data="
                  + Uri.EscapeDataString(options);
        try
        {
            var resp = await _http.SendAsync(AuthedRequest(url, cookie, json: true));
            if (resp.IsSuccessStatusCode)
            {
                var urls = ExtractImageUrls(await resp.Content.ReadAsStringAsync());
                if (urls.Count > 0) { await DownloadAll(urls); return; }
            }
        }
        catch { /* fall back to homepage scrape */ }

        var htmlResp = await _http.SendAsync(
            AuthedRequest("https://www.pinterest.com/", cookie, json: false));
        var html = await htmlResp.Content.ReadAsStringAsync();
        var htmlUrls = ExtractImageUrls(html);
        if (htmlUrls.Count == 0)
            SetStatus("Couldn't load home feed — session cookie may be invalid or expired");
        else
            await DownloadAll(htmlUrls);
    }

    private async Task DownloadAll(List<string> urls)
    {
        var tasks = new List<Task>();
        foreach (var raw in urls.Take(120))
        {
            var hiRes = Regex.Replace(raw, "/(?:[0-9]+x|originals)/", "/736x/");
            bool fresh;
            lock (_lock) fresh = _seen.Add(hiRes);
            if (!fresh) continue;

            var file = Path.Combine(_cacheDir, Md5Hex(hiRes) + ".img");
            if (_hidden.Contains(Path.GetFileName(file))) continue;
            if (File.Exists(file))
            {
                // Pin from the current feed that's already on disk: it still
                // belongs in this activation's pool even though the random
                // preload pass didn't pick it.
                if (!WasDelivered(file))
                {
                    MarkDelivered(file);
                    try { File.SetLastWriteTimeUtc(file, DateTime.UtcNow); } catch { }
                    tasks.Add(Task.Run(() =>
                    {
                        var img = DecodeImage(File.ReadAllBytes(file));
                        if (img != null) Deliver(img, fresh: false);
                    }));
                }
                continue;
            }

            MarkDelivered(file);
            tasks.Add(Download(hiRes, raw != hiRes ? raw : null, file));
        }
        await Task.WhenAll(tasks);
        TrimCache();
    }

    private async Task Download(string url, string? fallback, string file)
    {
        if (!await TryDownload(url, file) && fallback != null)
            await TryDownload(fallback, file);
    }

    private async Task<bool> TryDownload(string url, string file)
    {
        await _downloadSlots.WaitAsync();
        try
        {
            var resp = await _http.GetAsync(url);
            if (!resp.IsSuccessStatusCode) return false;
            var bytes = await resp.Content.ReadAsByteArrayAsync();
            var img = DecodeImage(bytes);
            if (img == null) return false;
            try { await File.WriteAllBytesAsync(file, bytes); } catch { /* cache is best-effort */ }
            Deliver(img, fresh: true);
            return true;
        }
        catch { return false; }
        finally
        {
            _downloadSlots.Release();
        }
    }

    private void TrimCache(int keep = 200)
    {
        try
        {
            var files = new DirectoryInfo(_cacheDir).GetFiles("*.img");
            if (files.Length <= keep) return;
            foreach (var f in files.OrderBy(f => f.LastWriteTimeUtc).Take(files.Length - keep))
                f.Delete();
        }
        catch { /* best-effort */ }
    }
}
