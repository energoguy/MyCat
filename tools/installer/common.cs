// Shared by MyCat.exe and the setup program: where things live, the few sentences
// both show (English, Russian, Uzbek), and the small jobs both do.
//
// Written for the C# compiler that ships with Windows (csc.exe of .NET Framework 4),
// so nothing has to be installed to build it. That compiler knows C# 5: no string
// interpolation, no "?." and no expression-bodied members here.
//
// Both programs are kept plain on purpose. They do what an installer is expected to do
// and nothing an antivirus program has reason to distrust: shortcuts are made through
// Windows' own shortcut interface, a running cat is asked to leave through its window,
// and no other program on the computer is looked at.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Text;
using Microsoft.Win32;

[ComImport, Guid("00021401-0000-0000-C000-000000000046")]
class ShellLink { }

// Windows' interface for shortcut (.lnk) files. The order of the methods is the interface.
[ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("000214F9-0000-0000-C000-000000000046")]
interface IShellLinkW
{
    void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder file, int max, IntPtr data, uint flags);
    void GetIDList(out IntPtr list);
    void SetIDList(IntPtr list);
    void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder text, int max);
    void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string text);
    void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder folder, int max);
    void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string folder);
    void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder arguments, int max);
    void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string arguments);
    void GetHotkey(out short key);
    void SetHotkey(short key);
    void GetShowCmd(out int show);
    void SetShowCmd(int show);
    void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder path, int max, out int index);
    void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string path, int index);
    void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string path, uint reserved);
    void Resolve(IntPtr window, uint flags);
    void SetPath([MarshalAs(UnmanagedType.LPWStr)] string file);
}

static class Common
{
    public const string Name = "MyCat";
    // Up to 0.6 the app was called WorkCat. What a version of that name left on the computer
    // (its program folder, shortcuts, entries in Windows' lists, its data folder) is found
    // under this name and taken over or cleared away.
    public const string OldName = "WorkCat";
    public const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
    public const string UninstallKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\MyCat";
    public const string OldUninstallKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\WorkCat";
    public const string Marker = "installed.txt";  // written by the setup program: this folder is ours to remove
    // How a running cat is found. Nobody sees these names, and they were kept when the app
    // got its new name, so that a cat of any version is found and can be asked to leave.
    const string CatWindow = "WorkCatTray";  // every running cat keeps one hidden window of this kind, for its icon near the clock
    const string Instance = "WorkCat";  // ... and this is its title when the cat uses the usual data folder

    [DllImport("user32", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern IntPtr FindWindowEx(IntPtr parent, IntPtr after, string kind, string title);

    [DllImport("user32", CharSet = CharSet.Unicode)]
    static extern int GetWindowText(IntPtr window, StringBuilder text, int max);

    [DllImport("user32")]
    static extern uint GetWindowThreadProcessId(IntPtr window, out uint process);

    [DllImport("user32", CharSet = CharSet.Unicode)]
    static extern uint RegisterWindowMessage(string name);

    [DllImport("user32")]
    static extern bool PostMessage(IntPtr window, uint message, IntPtr w, IntPtr l);

    static string Local { get { return Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData); } }

    // The program goes where per-user programs go: no administrator rights needed.
    public static string ProgramFolder { get { return Path.Combine(Local, "Programs", Name); } }
    public static string OldProgramFolder { get { return Path.Combine(Local, "Programs", OldName); } }

    // What the cat remembers lives apart from the program, so an update keeps it. The cat
    // itself gives a folder of the earlier name the new one, the first time it starts.
    public static string DataFolder { get { return Path.Combine(Local, Name); } }
    public static string OldDataFolder { get { return Path.Combine(Local, OldName); } }

    public static string StartMenuLink { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), Name + ".lnk"); } }
    public static string OldStartMenuLink { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), OldName + ".lnk"); } }

    public static string DesktopLink { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), Name + ".lnk"); } }
    public static string OldDesktopLink { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), OldName + ".lnk"); } }

    public static bool Inside(string path, string folder)
    {
        if (String.IsNullOrEmpty(path) || String.IsNullOrEmpty(folder)) return false;
        string full = Path.GetFullPath(path);
        string root = Path.GetFullPath(folder).TrimEnd('\\') + "\\";
        return full.StartsWith(root, StringComparison.OrdinalIgnoreCase);
    }

    // Ask running cats to leave, so their files can be replaced or removed.
    //   usual   the cat that uses the usual data folder, wherever it was started from
    //           (an older version unpacked from a zip is in no folder of ours)
    //   folder  any cat that runs from this folder
    // A cat is found by its own hidden window, asked through it, and given a few seconds
    // to save what it has. Only one that does not answer (a version too old to know the
    // question) is ended.
    public static void StopCats(bool usual, string folder)
    {
        uint leave = RegisterWindowMessage("WorkCatQuit");
        List<Process> asked = new List<Process>();
        IntPtr window = IntPtr.Zero;
        while ((window = FindWindowEx(IntPtr.Zero, window, CatWindow, null)) != IntPtr.Zero)
        {
            uint owner;
            GetWindowThreadProcessId(window, out owner);
            if (owner == 0) continue;
            StringBuilder title = new StringBuilder(64);
            GetWindowText(window, title, title.Capacity);
            Process cat = null;
            try
            {
                cat = Process.GetProcessById((int)owner);
                bool wanted = usual && title.ToString() == Instance;
                if (!wanted && folder != null) wanted = Inside(cat.MainModule.FileName, folder);
                if (!wanted) { cat.Dispose(); continue; }
                if (leave != 0) PostMessage(window, leave, IntPtr.Zero, IntPtr.Zero);
                asked.Add(cat);
            }
            catch (Exception) { if (cat != null) cat.Dispose(); }  // it left meanwhile
        }
        foreach (Process cat in asked)
        {
            try
            {
                if (!cat.WaitForExit(5000))
                {
                    cat.Kill();
                    cat.WaitForExit(5000);
                }
            }
            catch (Exception) { }
            finally { cat.Dispose(); }
        }
    }

    // What Windows starts for us when it starts (under the app's name, or its earlier one), or null.
    public static string RunValue()
    {
        try
        {
            using (RegistryKey run = Registry.CurrentUser.OpenSubKey(RunKey))
            {
                if (run == null) return null;
                return (run.GetValue(Name) ?? run.GetValue(OldName)) as string;
            }
        }
        catch (Exception) { return null; }
    }

    public static void MakeLink(string link, string target, string folder)
    {
        IShellLinkW shortcut = (IShellLinkW)new ShellLink();
        try
        {
            shortcut.SetPath(target);
            shortcut.SetWorkingDirectory(folder);
            shortcut.SetIconLocation(target, 0);
            shortcut.SetDescription(Words.Get("headline"));
            ((IPersistFile)shortcut).Save(link, true);
        }
        finally { Marshal.FinalReleaseComObject(shortcut); }
    }

    public static string LinkTarget(string link)
    {
        try
        {
            IShellLinkW shortcut = (IShellLinkW)new ShellLink();
            try
            {
                ((IPersistFile)shortcut).Load(link, 0);
                StringBuilder target = new StringBuilder(520);
                shortcut.GetPath(target, target.Capacity, IntPtr.Zero, 0);
                return target.ToString();
            }
            finally { Marshal.FinalReleaseComObject(shortcut); }
        }
        catch (Exception) { return ""; }
    }

    // One argument as a program expects it on its command line.
    public static string Quote(string argument)
    {
        if (argument.Length > 0 && argument.IndexOfAny(new[] { ' ', '\t', '"' }) < 0) return argument;
        StringBuilder quoted = new StringBuilder("\"");
        int slashes = 0;
        foreach (char c in argument)
        {
            if (c == '\\') { slashes++; continue; }
            if (c == '"') { quoted.Append('\\', slashes * 2 + 1); quoted.Append('"'); slashes = 0; continue; }
            quoted.Append('\\', slashes);
            slashes = 0;
            quoted.Append(c);
        }
        quoted.Append('\\', slashes * 2);
        quoted.Append('"');
        return quoted.ToString();
    }

    public static long SizeOf(string folder)
    {
        long total = 0;
        try
        {
            foreach (string file in Directory.GetFiles(folder, "*", SearchOption.AllDirectories))
            {
                try { total += new FileInfo(file).Length; } catch (Exception) { }
            }
        }
        catch (Exception) { }
        return total;
    }

    public static string Size(long bytes)
    {
        if (bytes >= 1L << 30) return (bytes / (double)(1L << 30)).ToString("0.0", CultureInfo.InvariantCulture) + " GB";
        return (bytes / (double)(1L << 20)).ToString("0", CultureInfo.InvariantCulture) + " MB";
    }
}

static class Words
{
    // English, Russian, Uzbek (Cyrillic). The cat itself asks for a language on its first start;
    // these few sentences follow the language Windows is shown in.
    static readonly Dictionary<string, string[]> All = new Dictionary<string, string[]>
    {
        { "headline", new[] { "A cat for your desktop", "Кот для рабочего стола", "Иш столингиз учун мушук" } },
        { "body", new[] {
            "It sits on the window you work in, keeps your focus timer and reminders, and learns your routine. Everything it learns stays on this computer.",
            "Он сидит на окне, в котором вы работаете, ведёт таймер фокуса и напоминания и изучает ваш распорядок. Всё, что он замечает, остаётся на этом компьютере.",
            "У сиз ишлаётган ойна устида ўтиради, фокус таймери ва эслатмаларни юритади, кун тартибингизни ўрганади. У пайқаган ҳамма нарса шу компьютерда қолади." } },
        { "desktop", new[] { "Put a shortcut on the desktop", "Создать ярлык на рабочем столе", "Иш столига ёрлиқ қўйиш" } },
        { "autostart", new[] { "Start the cat when Windows starts", "Запускать кота вместе с Windows", "Мушукни Windows билан бирга ишга тушириш" } },
        { "where", new[] {
            "It is installed for you only. No administrator rights are needed.",
            "Устанавливается только для вас. Права администратора не нужны.",
            "Фақат сиз учун ўрнатилади. Администратор ҳуқуқлари керак эмас." } },
        { "install", new[] { "Install", "Установить", "Ўрнатиш" } },
        { "installing", new[] { "Installing...", "Установка...", "Ўрнатилмоқда..." } },
        { "done", new[] { "Done. Here comes the cat.", "Готово. Кот уже идёт.", "Тайёр. Мушук келяпти." } },
        { "failed", new[] { "It could not be installed:", "Не удалось установить:", "Ўрнатиб бўлмади:" } },
        { "remove?", new[] { "Remove MyCat from this computer?", "Удалить MyCat с этого компьютера?", "MyCat бу компьютердан ўчирилсинми?" } },
        { "memory?", new[] {
            "Also delete what the cat remembers: your tasks, what it learned, and its AI ({0})?\n\nChoose No to keep them for a later installation.",
            "Удалить также то, что кот помнит: ваши задачи, его наблюдения и его ИИ ({0})?\n\nВыберите «Нет», чтобы сохранить их для следующей установки.",
            "Мушук эслаб қолган нарсалар ҳам ўчирилсинми: вазифаларингиз, кузатувлари ва сунъий интеллекти ({0})?\n\nКейинги ўрнатиш учун сақлаб қолиш учун «Йўқ»ни танланг." } },
        { "removed", new[] { "MyCat was removed.", "MyCat удалён.", "MyCat ўчирилди." } },
        { "not installed", new[] {
            "This copy was not put here by the installer. To remove it, simply delete its folder.",
            "Эта копия не была установлена установщиком. Чтобы убрать её, просто удалите папку.",
            "Бу нусха ўрнатувчи томонидан қўйилмаган. Уни олиб ташлаш учун папкасини ўчиринг." } },
        { "broken", new[] {
            "Part of MyCat is missing. Please install it again.",
            "Часть MyCat отсутствует. Пожалуйста, установите его заново.",
            "MyCat'нинг бир қисми йўқ. Илтимос, уни қайта ўрнатинг." } },
    };

    static string chosen;  // "/L=ru" on the command line: for looking at each language

    public static void Use(string language) { chosen = language.Trim().ToLowerInvariant(); }

    public static int Index
    {
        get
        {
            string two = chosen ?? CultureInfo.CurrentUICulture.TwoLetterISOLanguageName;
            return two == "ru" ? 1 : two == "uz" ? 2 : 0;
        }
    }

    public static string Get(string key) { return All[key][Index]; }
}
