// MyCat.exe: the program people start.
//
// It holds nothing of the app itself. Next to it are two folders: "runtime", the Python
// interpreter exactly as its makers publish and sign it, and "app", the cat's own
// source. This program starts the one with the other and steps aside, so no Python has
// to be installed on the computer, and what runs is a program Windows already knows.
//
//   MyCat.exe [arguments for the app]
//   MyCat.exe --wait ...                 stay until the cat has left, and leave with its result
//   MyCat.exe --uninstall [/S] [/wipe]   remove the program; /S asks nothing,
//                                        /wipe also deletes what the cat remembers
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

static class Launcher
{
    [DllImport("user32")]
    static extern bool AllowSetForegroundWindow(uint process);

    [STAThread]
    static int Main(string[] args)
    {
        string exe = Assembly.GetExecutingAssembly().Location;
        string root = Path.GetDirectoryName(exe);
        if (args.Length > 0 && args[0] == "--uninstall") return Uninstall.Ask(exe, root, args);
        if (args.Length > 0 && args[0] == "--remove") return Uninstall.Remove(args);

        string python = Path.Combine(root, "runtime", "pythonw.exe");
        string script = Path.Combine(root, "app", Common.Name + ".pyw");
        if (!File.Exists(python) || !File.Exists(script))
        {
            MessageBox.Show(Words.Get("broken"), Common.Name, MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return 2;
        }
        Environment.SetEnvironmentVariable("WORKCAT_EXE", exe);  // how the app knows what to start with Windows (the variable kept its name)

        bool wait = false;
        List<string> words = new List<string>();
        words.Add(Common.Quote(script));
        foreach (string arg in args)
        {
            if (arg == "--wait") { wait = true; continue; }
            if (arg == "--check") wait = true;  // a self-check is of use only with its result
            words.Add(Common.Quote(arg));
        }
        ProcessStartInfo start = new ProcessStartInfo(python, String.Join(" ", words.ToArray()));
        start.UseShellExecute = false;
        start.WorkingDirectory = root;
        using (Process cat = Process.Start(start))
        {
            // Whoever started us may bring a window to the front; the cat inherits that,
            // so its first window, or the window of a cat already running, can come up.
            AllowSetForegroundWindow((uint)cat.Id);
            if (!wait) return 0;
            cat.WaitForExit();
            return cat.ExitCode;
        }
    }
}

static class Uninstall
{
    // MyCat.exe --uninstall: ask, take away the shortcuts and the entries in Windows'
    // lists, and hand the folder itself to a copy of this program outside it.
    public static int Ask(string exe, string root, string[] args)
    {
        bool silent = Array.IndexOf(args, "/S") >= 0;
        bool wipe = Array.IndexOf(args, "/wipe") >= 0;
        // Only a folder the setup program made is removed: never some folder this file was copied into.
        if (!Ours(root))
        {
            if (!silent) MessageBox.Show(Words.Get("not installed"), Common.Name, MessageBoxButtons.OK, MessageBoxIcon.Information);
            return 1;
        }
        if (!silent && MessageBox.Show(Words.Get("remove?"), Common.Name, MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes)
            return 1;

        Common.StopCats(false, root);
        bool usual = Common.Inside(root + "\\x", Common.ProgramFolder);  // the usual place, not a copy made for a test
        // What the cat remembers is in the data folder; one that a version of the earlier
        // name left behind, and that the cat has not taken over yet, belongs to it as well.
        string[] memory = { Common.DataFolder, Common.OldDataFolder };
        long kept = 0;
        foreach (string place in memory) if (Directory.Exists(place)) kept += Common.SizeOf(place);
        if (usual && !silent && (Directory.Exists(memory[0]) || Directory.Exists(memory[1])))
        {
            string question = String.Format(Words.Get("memory?"), Common.Size(kept));
            wipe = MessageBox.Show(question, Common.Name, MessageBoxButtons.YesNo, MessageBoxIcon.Question, MessageBoxDefaultButton.Button2) == DialogResult.Yes;
        }

        // Shortcuts and registry entries are removed only if they point at this copy.
        foreach (string link in new[] { Common.StartMenuLink, Common.DesktopLink })
        {
            try { if (File.Exists(link) && Common.Inside(Common.LinkTarget(link), root)) File.Delete(link); } catch (Exception) { }
        }
        try
        {
            using (RegistryKey run = Registry.CurrentUser.OpenSubKey(Common.RunKey, true))
            {
                foreach (string name in new[] { Common.Name, Common.OldName })
                {
                    string value = run == null ? null : run.GetValue(name) as string;
                    if (value != null && value.IndexOf(root, StringComparison.OrdinalIgnoreCase) >= 0) run.DeleteValue(name, false);
                }
            }
            using (RegistryKey entry = Registry.CurrentUser.OpenSubKey(Common.UninstallKey))
            {
                string place = entry == null ? null : entry.GetValue("InstallLocation") as string;
                if (place != null && String.Equals(place.TrimEnd('\\'), root.TrimEnd('\\'), StringComparison.OrdinalIgnoreCase))
                    Registry.CurrentUser.DeleteSubKeyTree(Common.UninstallKey, false);
            }
        }
        catch (Exception) { }

        if (wipe && usual)
        {
            foreach (string place in memory)
            {
                try { if (Directory.Exists(place)) Directory.Delete(place, true); } catch (Exception) { }
            }
        }

        // A program cannot remove the folder it is running from. So a copy of this file
        // is put into the temporary folder, and that copy removes the folder once we are gone.
        string copy = Path.Combine(Path.GetTempPath(), Common.Name + "-remove.exe");
        File.Copy(exe, copy, true);
        string words = "--remove " + Common.Quote(root) + " " + Process.GetCurrentProcess().Id + (silent ? " /S" : "");
        ProcessStartInfo start = new ProcessStartInfo(copy, words);
        start.UseShellExecute = false;
        start.WorkingDirectory = Path.GetTempPath();
        Process.Start(start).Dispose();
        return 0;
    }

    static bool Ours(string root)
    {
        return File.Exists(Path.Combine(root, Common.Marker)) && Directory.Exists(Path.Combine(root, "runtime"));
    }

    // (the copy in the temporary folder)  --remove <folder> <number of the program that asked> [/S]
    public static int Remove(string[] args)
    {
        if (args.Length < 3) return 1;
        string root = args[1];
        bool silent = Array.IndexOf(args, "/S") >= 0;
        if (!Ours(root)) return 1;
        int asker;
        if (Int32.TryParse(args[2], out asker))
        {
            try { using (Process waited = Process.GetProcessById(asker)) { waited.WaitForExit(15000); } }
            catch (Exception) { }  // it has left already
        }
        for (int attempt = 0; attempt < 40 && Directory.Exists(root); attempt++)
        {
            try { Directory.Delete(root, true); }
            catch (Exception) { Thread.Sleep(250); }  // a file is still letting go
        }
        if (!silent) MessageBox.Show(Words.Get("removed"), Common.Name, MessageBoxButtons.OK, MessageBoxIcon.Information);
        return Directory.Exists(root) ? 1 : 0;
    }
}
