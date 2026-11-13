// The setup program: one window, one button.
//
// The whole of MyCat travels at the end of this file as an ordinary zip, the way
// self-extracting archives are made: any zip program, and any antivirus program, can open
// this file and see every file that is in it. Installing means unpacking that zip into
// the user's own programs folder, making the shortcuts and the "Installed apps" entry,
// and starting the cat. No administrator rights, no questions.
//
//   MyCat-x.y.z-setup.exe                   the window
//   ... /S                                  install without a window
//   ... /D=C:\some\folder                   install there instead of the usual place
//   ... /nostart                            do not start the cat afterwards
//   ... /nodesktop  /noautostart            as if that box in the window were not ticked
//   ... /L=ru                               show the window in en, ru or uz, whatever Windows is in
//   ... /scale=1.5                          lay the window out as a screen set to 150 % shows it
//   ... /test                               files only: no shortcuts, no registry entries,
//                                           and a cat that is running is left alone
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

class Options
{
    public bool Silent, NoStart, Test;
    public bool Desktop = true, Autostart = true;
    public float Scale;
    public string Folder = Common.ProgramFolder;

    public static Options Parse(string[] args)
    {
        Options o = new Options();
        bool noDesktop = false, noAutostart = false;
        foreach (string arg in args)
        {
            if (String.Equals(arg, "/S", StringComparison.OrdinalIgnoreCase)) o.Silent = true;
            else if (String.Equals(arg, "/nostart", StringComparison.OrdinalIgnoreCase)) o.NoStart = true;
            else if (String.Equals(arg, "/test", StringComparison.OrdinalIgnoreCase)) o.Test = true;
            else if (String.Equals(arg, "/nodesktop", StringComparison.OrdinalIgnoreCase)) noDesktop = true;
            else if (String.Equals(arg, "/noautostart", StringComparison.OrdinalIgnoreCase)) noAutostart = true;
            else if (arg.StartsWith("/L=", StringComparison.OrdinalIgnoreCase)) Words.Use(arg.Substring(3));
            else if (arg.StartsWith("/scale=", StringComparison.OrdinalIgnoreCase)) Single.TryParse(arg.Substring(7), NumberStyles.Float, CultureInfo.InvariantCulture, out o.Scale);
            else if (arg.StartsWith("/D=", StringComparison.OrdinalIgnoreCase)) o.Folder = Path.GetFullPath(arg.Substring(3).Trim('"'));
        }
        // A first installation starts with both boxes ticked; an update keeps what was chosen
        // then, also when the version that is there still has the app's earlier name.
        if (!o.Test && (File.Exists(Path.Combine(o.Folder, Common.Marker)) || File.Exists(Path.Combine(Common.OldProgramFolder, Common.Marker))))
        {
            o.Desktop = File.Exists(Common.DesktopLink) || File.Exists(Common.OldDesktopLink);
            o.Autostart = Common.RunValue() != null;
        }
        if (noDesktop) o.Desktop = false;
        if (noAutostart) o.Autostart = false;
        return o;
    }
}

static class Setup
{
    [STAThread]
    static int Main(string[] args)
    {
        Options options = Options.Parse(args);
        if (options.Silent)
        {
            try { Install(options, null); return 0; }
            catch (Exception error)
            {
                try { File.WriteAllText(Path.Combine(Path.GetTempPath(), Common.Name + "-setup-error.txt"), error.ToString()); } catch (Exception) { }
                return 1;
            }
        }
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new Window(options));
        return 0;
    }

    public static Stream Resource(string name)
    {
        return Assembly.GetExecutingAssembly().GetManifestResourceStream(name);
    }

    // Take a folder of an older version away. Its files may need a moment to be let go of.
    static void Clear(string path)
    {
        for (int attempt = 0; Directory.Exists(path); attempt++)
        {
            try { Directory.Delete(path, true); }
            catch (Exception)
            {
                if (attempt >= 20) throw;
                Thread.Sleep(250);
            }
        }
    }

    // The app was called WorkCat up to 0.6. An installation of that name is cleared away:
    // its program folder (only one the setup program made), its shortcuts and its entries
    // in Windows' lists. What the cat remembers is not touched here: the cat takes its
    // data folder over itself, the first time it starts under the new name.
    static void ClearOldName()
    {
        string old = Common.OldProgramFolder;
        bool ours = File.Exists(Path.Combine(old, Common.Marker));
        if (ours)
        {
            Common.StopCats(false, old);
            try { Clear(old); } catch (Exception) { }  // a file that will not go: the rest still gets installed
        }
        foreach (string link in new[] { Common.OldStartMenuLink, Common.OldDesktopLink })
        {
            try
            {
                if (!File.Exists(link)) continue;
                string target = Common.LinkTarget(link);
                if (Common.Inside(target, old) || !File.Exists(target)) File.Delete(link);  // ours, or leading nowhere now
            }
            catch (Exception) { }
        }
        try
        {
            using (RegistryKey entry = Registry.CurrentUser.OpenSubKey(Common.OldUninstallKey))
            {
                string place = entry == null ? null : entry.GetValue("InstallLocation") as string;
                if (place != null && String.Equals(place.TrimEnd('\\'), old.TrimEnd('\\'), StringComparison.OrdinalIgnoreCase))
                    Registry.CurrentUser.DeleteSubKeyTree(Common.OldUninstallKey, false);
            }
            // The entry that starts the cat with Windows is left as it is: the cat itself puts
            // it under the new name the first time it starts (and until then it tells the
            // setup program, and the cat, that starting with Windows was wanted).
        }
        catch (Exception) { }
    }

    // Everything the installation does, in order. `progress` gets 0..100.
    public static void Install(Options options, Action<int> progress)
    {
        string folder = options.Folder;
        Common.StopCats(!options.Test, folder);  // the cat that is running now steps aside: the new one takes its place
        if (!options.Test) ClearOldName();
        // Parts of an older version that the new one may no longer have.
        foreach (string old in new[] { "app", "runtime" })
            Clear(Path.Combine(folder, old));
        Directory.CreateDirectory(folder);

        long written = 0;
        using (FileStream self = new FileStream(Application.ExecutablePath, FileMode.Open, FileAccess.Read, FileShare.Read))
        using (ZipArchive zip = new ZipArchive(self, ZipArchiveMode.Read))
        {
            int done = 0;
            foreach (ZipArchiveEntry entry in zip.Entries)
            {
                string target = Path.GetFullPath(Path.Combine(folder, entry.FullName));
                if (!Common.Inside(target, folder)) throw new InvalidDataException(entry.FullName);  // never write outside our folder
                if (entry.FullName.EndsWith("/"))
                {
                    Directory.CreateDirectory(target);
                }
                else
                {
                    Directory.CreateDirectory(Path.GetDirectoryName(target));
                    entry.ExtractToFile(target, true);
                    written += entry.Length;
                }
                done++;
                if (progress != null) progress(done * 100 / zip.Entries.Count);
            }
        }
        File.WriteAllText(Path.Combine(folder, Common.Marker), Build.Version + "\r\n");

        string exe = Path.Combine(folder, Common.Name + ".exe");
        if (!options.Test)
        {
            Common.MakeLink(Common.StartMenuLink, exe, folder);
            if (options.Desktop) Common.MakeLink(Common.DesktopLink, exe, folder);
            else if (File.Exists(Common.DesktopLink) && Common.Inside(Common.LinkTarget(Common.DesktopLink), folder)) File.Delete(Common.DesktopLink);
            using (RegistryKey entry = Registry.CurrentUser.CreateSubKey(Common.UninstallKey))
            {
                entry.SetValue("DisplayName", Common.Name);
                entry.SetValue("DisplayVersion", Build.Version);
                entry.SetValue("Publisher", Common.Name);
                entry.SetValue("DisplayIcon", exe + ",0");
                entry.SetValue("InstallLocation", folder);
                entry.SetValue("UninstallString", "\"" + exe + "\" --uninstall");
                entry.SetValue("QuietUninstallString", "\"" + exe + "\" --uninstall /S");
                entry.SetValue("EstimatedSize", (int)(written / 1024), RegistryValueKind.DWord);
                entry.SetValue("NoModify", 1, RegistryValueKind.DWord);
                entry.SetValue("NoRepair", 1, RegistryValueKind.DWord);
            }
        }
        if (!options.NoStart)
        {
            // Whether the cat starts with Windows is the cat's own setting: it is told what was ticked here.
            ProcessStartInfo start = new ProcessStartInfo(exe, options.Test ? "" : "--autostart " + (options.Autostart ? "on" : "off"));
            start.WorkingDirectory = folder;
            start.UseShellExecute = false;
            Process.Start(start).Dispose();
        }
    }
}

// The one button, in the cat's own amber, with round corners.
class MainButton : Button
{
    static readonly Color Usual = Color.FromArgb(0xFF, 0xCF, 0x4A), Hot = Color.FromArgb(0xFF, 0xDB, 0x70), Down = Color.FromArgb(0xF3, 0xC0, 0x36), Edge = Color.FromArgb(0xE3, 0xB0, 0x24);
    bool hot, down;
    public int Radius = 8;

    public MainButton()
    {
        SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer, true);
    }

    protected override void OnMouseEnter(EventArgs e) { hot = true; Invalidate(); base.OnMouseEnter(e); }
    protected override void OnMouseLeave(EventArgs e) { hot = false; down = false; Invalidate(); base.OnMouseLeave(e); }
    protected override void OnMouseDown(MouseEventArgs e) { down = true; Invalidate(); base.OnMouseDown(e); }
    protected override void OnMouseUp(MouseEventArgs e) { down = false; Invalidate(); base.OnMouseUp(e); }
    protected override void OnEnabledChanged(EventArgs e) { Invalidate(); base.OnEnabledChanged(e); }

    protected override void OnPaint(PaintEventArgs e)
    {
        Graphics g = e.Graphics;
        Color back = Parent == null ? Color.White : Parent.BackColor;
        g.Clear(back);
        g.SmoothingMode = SmoothingMode.AntiAlias;
        Rectangle box = new Rectangle(0, 0, Width - 1, Height - 1);
        int d = Math.Min(Radius * 2, Math.Min(box.Width, box.Height));
        using (GraphicsPath shape = new GraphicsPath())
        {
            shape.AddArc(box.X, box.Y, d, d, 180, 90);
            shape.AddArc(box.Right - d, box.Y, d, d, 270, 90);
            shape.AddArc(box.Right - d, box.Bottom - d, d, d, 0, 90);
            shape.AddArc(box.X, box.Bottom - d, d, d, 90, 90);
            shape.CloseFigure();
            Color fill = !Enabled ? Blend(Usual, back, 0.6f) : down ? Down : hot ? Hot : Usual;
            using (SolidBrush brush = new SolidBrush(fill)) g.FillPath(brush, shape);
            using (Pen pen = new Pen(Enabled ? Edge : Blend(Edge, back, 0.6f))) g.DrawPath(pen, shape);
        }
        Color ink = Enabled ? Color.FromArgb(0x2B, 0x2E, 0x3B) : Color.FromArgb(0xB3, 0xAE, 0xA1);
        TextRenderer.DrawText(g, Text, Font, ClientRectangle, ink, TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine);
    }

    static Color Blend(Color a, Color b, float share)
    {
        return Color.FromArgb((int)(a.R + (b.R - a.R) * share), (int)(a.G + (b.G - a.G) * share), (int)(a.B + (b.B - a.B) * share));
    }
}

class Window : Form
{
    static readonly Color Paper = Color.FromArgb(0xFF, 0xFE, 0xFB), Ink = Color.FromArgb(0x2B, 0x2E, 0x3B), Faint = Color.FromArgb(0x7B, 0x7F, 0x8D);
    static readonly Color Track = Color.FromArgb(0xEC, 0xE8, 0xDC), Amber = Color.FromArgb(0xFF, 0xCF, 0x4A);

    readonly Options options;
    readonly float k;  // how much larger than usual this screen shows things: 1 at 100 %, 1.5 at 150 %
    readonly CheckBox desktop, autostart;
    readonly MainButton go;
    readonly Panel track, fill;
    readonly Label status;

    int S(float n) { return (int)Math.Round(n * k); }

    // Every size and place in this window is worked out here, from the size its words
    // really have on this screen. Nothing is left to Windows' own resizing of windows for
    // screens with larger text: that is what once hid the button on such a screen.
    public Window(Options options)
    {
        this.options = options;
        using (Graphics screen = Graphics.FromHwnd(IntPtr.Zero))
            k = options.Scale >= 0.5f && options.Scale <= 4f ? options.Scale : Math.Max(1f, screen.DpiX / 96f);
        AutoScaleMode = AutoScaleMode.None;
        Text = Common.Name;
        Font = new Font("Segoe UI", 13.5f * k, GraphicsUnit.Pixel);
        Font small = new Font("Segoe UI", 12.5f * k, GraphicsUnit.Pixel);
        Font head = new Font("Segoe UI", 22f * k, FontStyle.Bold, GraphicsUnit.Pixel);
        Font bold = new Font("Segoe UI Semibold", 14f * k, GraphicsUnit.Pixel);
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Paper;
        ForeColor = Ink;
        try { Icon = new Icon(Setup.Resource("workcat.ico"), new Size(S(32), S(32))); } catch (Exception) { }

        int pad = S(28), width = S(540), art = S(96);
        int y = pad;
        PictureBox cat = new PictureBox();
        cat.Location = new Point(pad, y);
        cat.Size = new Size(art, art);
        cat.Image = Cat(art);
        Controls.Add(cat);

        int left = pad + art + S(22), room = width - left - pad;
        Label title = Say(Words.Get("headline"), head, Ink, left, y - S(4), room);
        Label body = Say(Words.Get("body"), Font, Ink, left, title.Bottom + S(6), room);
        y = Math.Max(cat.Bottom, body.Bottom) + S(22);

        desktop = Tick(Words.Get("desktop"), options.Desktop, pad, y, width - 2 * pad);
        y = desktop.Bottom + S(6);
        autostart = Tick(Words.Get("autostart"), options.Autostart, pad, y, width - 2 * pad);
        y = autostart.Bottom + S(14);
        Label where = Say(Words.Get("where"), small, Faint, pad, y, width - 2 * pad);
        y = where.Bottom + S(22);

        go = new MainButton();
        go.Text = Words.Get("install");
        go.Font = bold;
        go.Radius = S(8);
        Size need = TextRenderer.MeasureText(go.Text, bold);
        go.Size = new Size(Math.Max(S(150), need.Width + S(56)), S(42));
        go.Location = new Point(width - pad - go.Width, y);
        go.Click += Start;
        Controls.Add(go);
        AcceptButton = go;

        int beside = go.Left - pad - S(24);
        track = new Panel();
        track.BackColor = Track;
        track.Location = new Point(pad, y + S(8));
        track.Size = new Size(beside, S(6));
        track.Visible = false;
        fill = new Panel();
        fill.BackColor = Amber;
        fill.Location = new Point(0, 0);
        fill.Size = new Size(0, track.Height);
        track.Controls.Add(fill);
        Controls.Add(track);
        status = new Label();
        status.Font = small;
        status.ForeColor = Faint;
        status.BackColor = Paper;
        status.AutoSize = false;
        status.Location = new Point(pad - S(2), track.Bottom + S(5));
        status.Size = new Size(beside, S(22));
        Controls.Add(status);

        ClientSize = new Size(width, go.Bottom + pad);
    }

    // Words in a box exactly as high as they need to be when they may be `room` wide.
    Label Say(string text, Font font, Color colour, int x, int y, int room)
    {
        Label label = new Label();
        label.UseMnemonic = false;
        label.Text = text;
        label.Font = font;
        label.ForeColor = colour;
        label.BackColor = Paper;
        label.AutoSize = false;
        Size need = label.GetPreferredSize(new Size(room, 0));
        label.Location = new Point(x, y);
        label.Size = new Size(room, need.Height + S(2));
        Controls.Add(label);
        return label;
    }

    // A tick box as wide as its words in this window's own font. (Measured in any other
    // font it comes out too narrow, and the end of the sentence is not shown.) If the
    // words are too long for one line, it gets the height for two.
    CheckBox Tick(string text, bool on, int x, int y, int room)
    {
        CheckBox box = new CheckBox();
        box.UseMnemonic = false;
        box.Font = Font;
        box.Text = text;
        box.Checked = on;
        box.BackColor = Paper;
        box.AutoSize = false;
        Size words = TextRenderer.MeasureText(text, Font);
        int width = Math.Max(words.Width + S(44), box.GetPreferredSize(Size.Empty).Width + S(16));  // the little box itself, the gap after it, and some air
        int lines = width > room ? 2 : 1;
        box.Location = new Point(x, y);
        box.Size = new Size(Math.Min(room, width), Math.Max(words.Height * lines + S(8), S(26)));
        Controls.Add(box);
        return box;
    }

    // The cat's face from the icon, enlarged without blurring: it is pixel art.
    static Bitmap Cat(int size)
    {
        Bitmap picture = new Bitmap(size, size);
        try
        {
            using (Icon icon = new Icon(Setup.Resource("workcat.ico"), new Size(48, 48)))
            using (Bitmap small = icon.ToBitmap())
            using (Graphics g = Graphics.FromImage(picture))
            {
                g.InterpolationMode = InterpolationMode.NearestNeighbor;
                g.PixelOffsetMode = PixelOffsetMode.Half;
                g.DrawImage(small, new Rectangle(0, 0, size, size));
            }
        }
        catch (Exception) { }
        return picture;
    }

    void Start(object sender, EventArgs e)
    {
        go.Enabled = false;
        desktop.Enabled = false;
        autostart.Enabled = false;
        options.Desktop = desktop.Checked;
        options.Autostart = autostart.Checked;
        track.Visible = true;
        status.Text = Words.Get("installing");

        BackgroundWorker worker = new BackgroundWorker();
        worker.WorkerReportsProgress = true;
        worker.DoWork += delegate { Setup.Install(options, delegate(int percent) { worker.ReportProgress(percent); }); };
        worker.ProgressChanged += delegate(object s, ProgressChangedEventArgs p) { fill.Width = track.Width * Math.Min(100, Math.Max(0, p.ProgressPercentage)) / 100; };
        worker.RunWorkerCompleted += delegate(object s, RunWorkerCompletedEventArgs done)
        {
            if (done.Error != null)
            {
                status.Text = "";
                MessageBox.Show(this, Words.Get("failed") + "\n\n" + done.Error.Message, Text, MessageBoxButtons.OK, MessageBoxIcon.Warning);
                go.Enabled = true;
                desktop.Enabled = true;
                autostart.Enabled = true;
                track.Visible = false;
                return;
            }
            fill.Width = track.Width;
            status.Text = Words.Get("done");
            System.Windows.Forms.Timer close = new System.Windows.Forms.Timer();
            close.Interval = 1200;
            close.Tick += delegate { close.Stop(); Close(); };
            close.Start();
        };
        worker.RunWorkerAsync();
    }
}
