namespace PinterestSaver;

/// <summary>Config dialog shown for the /c screensaver switch.</summary>
public class SettingsForm : Form
{
    private readonly TextBox _feed = new() { Width = 400 };
    private readonly TextBox _cookie = new() { Width = 400 };
    private readonly TrackBar _speed = new() { Minimum = 8, Maximum = 80, Width = 400, TickFrequency = 8 };
    private readonly TrackBar _tileSize = new() { Minimum = 220, Maximum = 480, Width = 400, TickFrequency = 20 };
    private readonly CheckBox _clock = new() { Text = "Show clock", AutoSize = true };

    public SettingsForm()
    {
        Text = "Pin Options";
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        AutoSize = true;
        AutoSizeMode = AutoSizeMode.GrowAndShrink;

        var settings = AppSettings.Load();
        _feed.Text = settings.Feed;
        _cookie.Text = settings.SessionCookie;
        _speed.Value = Math.Clamp((int)settings.Speed, _speed.Minimum, _speed.Maximum);
        _tileSize.Value = Math.Clamp((int)settings.TileSize, _tileSize.Minimum, _tileSize.Maximum);
        _clock.Checked = settings.ShowClock;

        var ok = new Button { Text = "OK", DialogResult = DialogResult.OK, Width = 90 };
        var cancel = new Button { Text = "Cancel", DialogResult = DialogResult.Cancel, Width = 90 };
        ok.Click += (_, _) =>
        {
            var s = new AppSettings
            {
                Feed = _feed.Text.Trim().Length > 0 ? _feed.Text.Trim() : AppSettings.DefaultFeed,
                SessionCookie = _cookie.Text.Trim(),
                Speed = _speed.Value,
                TileSize = _tileSize.Value,
                ShowClock = _clock.Checked
            };
            s.Save();
        };
        AcceptButton = ok;
        CancelButton = cancel;

        var layout = new FlowLayoutPanel
        {
            FlowDirection = FlowDirection.TopDown,
            Padding = new Padding(16),
            AutoSize = true,
            WrapContents = false
        };
        layout.Controls.Add(Label("Pinterest feed (username, username/board, or board URL):"));
        layout.Controls.Add(_feed);
        layout.Controls.Add(Label("Personal home feed — paste your _pinterest_sess cookie (optional):"));
        layout.Controls.Add(_cookie);
        layout.Controls.Add(Label("Scroll speed:"));
        layout.Controls.Add(_speed);
        layout.Controls.Add(Label("Tile size (bigger = fewer columns):"));
        layout.Controls.Add(_tileSize);
        layout.Controls.Add(_clock);

        var buttons = new FlowLayoutPanel { FlowDirection = FlowDirection.LeftToRight, AutoSize = true };
        buttons.Controls.Add(ok);
        buttons.Controls.Add(cancel);
        layout.Controls.Add(buttons);

        Controls.Add(layout);
    }

    private static Label Label(string text) => new()
    {
        Text = text,
        AutoSize = true,
        Margin = new Padding(0, 10, 0, 2)
    };
}
