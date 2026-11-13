"""Build the installer: dist/MyCat-<version>-setup.exe

    python tools/build_exe.py            build it
    python tools/build_exe.py --stage    only the folder it unpacks (build/MyCat), with MyCat.exe
    python tools/build_exe.py --test     build, then install into a temporary folder, let that
                                         copy check itself, and uninstall it again

Nothing is downloaded or installed to do this:

- the Python that goes inside is copied from the one running this script (only what the
  app needs: no add-on packages, no tests, no IDLE). Its programs and libraries are taken
  as they are, with their makers' signatures intact: the cat runs on that pythonw.exe;
- MyCat.exe (which only starts it) and the setup program are compiled with csc.exe, the
  C# compiler that is part of Windows (.NET Framework 4);
- the setup program carries everything as an ordinary zip at its own end, the way
  self-extracting archives do, so a zip program or an antivirus program can look inside.

The person who gets the installer needs none of this.
"""
from __future__ import annotations

import compileall
import json
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from workcat import APP_NAME, __version__, tray  # noqa: E402

BUILD = ROOT / "build"
STAGE = BUILD / APP_NAME
DIST = ROOT / "dist"
SOURCES = ROOT / "tools" / "installer"
PYTHON = Path(sys.base_prefix)
TAG = f"{sys.version_info.major}{sys.version_info.minor}"  # 314

# What of Python is left behind: add-on packages, its own tests, IDLE, installers, docs.
LIB_SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", "site-packages", "test", "tests", "idle_test", "idlelib", "ensurepip", "turtledemo", "turtle.py", "pydoc_data", "venv")
DLL_SKIP = shutil.ignore_patterns("python.cat", "*_test*.pyd", "_remote_debugging.pyd", "xxlimited*.pyd")
TCL_SKIP = shutil.ignore_patterns("tzdata", "demos", "nmake", "*.lib")
REFERENCES = ("System.dll", "System.Core.dll", "System.Windows.Forms.dll", "System.Drawing.dll", "System.IO.Compression.dll", "System.IO.Compression.FileSystem.dll")

ABOUT = f"""{APP_NAME} {__version__}

A desk cat that keeps you company while you work. Start it with {APP_NAME}.exe.
To remove it: Windows Settings, Apps, Installed apps, {APP_NAME}, Uninstall.

What is in this folder
  {APP_NAME}.exe   starts the cat (and removes it, when you ask Windows to uninstall)
  app\\           the cat itself: Python source you can read, original work
  runtime\\       the Python interpreter it runs on, with Tcl/Tk for its windows, exactly
                 as published and signed by the Python Software Foundation.
                 Its licence is runtime\\LICENSE.txt; Tcl/Tk's is in runtime\\tcl\\tcl8.6\\license.terms.

While the cat runs, Task Manager lists it as "Python" (pythonw.exe from the runtime folder).
What the cat remembers is not kept here but in %LOCALAPPDATA%\\{APP_NAME}.
"""


def compiler() -> Path:
    """csc.exe of .NET Framework 4: every Windows 10 and 11 has it."""
    base = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Microsoft.NET" / "Framework64"
    found = sorted(base.glob("v4.*/csc.exe"))
    if not found:
        raise SystemExit(f"No C# compiler under {base}. It is part of the .NET Framework that Windows includes.")
    return found[-1]


def stage() -> None:
    """Put together the folder the installer unpacks: MyCat.exe, app, runtime."""
    shutil.rmtree(STAGE, ignore_errors=True)
    runtime = STAGE / "runtime"
    runtime.mkdir(parents=True)
    for name in (f"python{TAG}.dll", "python3.dll", "vcruntime140.dll", "vcruntime140_1.dll", "pythonw.exe", "LICENSE.txt"):
        if (PYTHON / name).is_file():
            shutil.copy2(PYTHON / name, runtime / name)
    if not (runtime / f"python{TAG}.dll").is_file():
        raise SystemExit(f"python{TAG}.dll is not in {PYTHON}: this Python cannot be packed.")
    shutil.copytree(PYTHON / "DLLs", runtime / "DLLs", ignore=DLL_SKIP)
    shutil.copytree(PYTHON / "Lib", runtime / "Lib", ignore=LIB_SKIP)
    shutil.copytree(PYTHON / "tcl", runtime / "tcl", ignore=TCL_SKIP)
    # This file seals the packed Python off: it looks nowhere else for modules, not in the
    # registry, not in environment variables, not in another Python on the same computer.
    (runtime / f"python{TAG}._pth").write_text("Lib\nDLLs\n..\\app\n", encoding="ascii")

    app = STAGE / "app"
    (app / "workcat" / "lang").mkdir(parents=True)
    shutil.copy2(ROOT / f"{APP_NAME}.pyw", app / f"{APP_NAME}.pyw")
    for path in sorted((ROOT / "workcat").glob("*.py")):
        shutil.copy2(path, app / "workcat" / path.name)
    for path in sorted((ROOT / "workcat" / "lang").glob("*.json")):
        shutil.copy2(path, app / "workcat" / "lang" / path.name)
    (STAGE / "ABOUT.txt").write_text(ABOUT.replace("\n", "\r\n"), encoding="utf-8-sig")
    # Compiled once here, so the cat's very first start on someone's computer is not a slow
    # one. "Unchecked hash": the compiled files are simply used, whatever dates the files get
    # when the installer unpacks them.
    for folder in (runtime / "Lib", app):
        compileall.compile_dir(str(folder), quiet=2, workers=1, invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)


def version_file(title: str, about: str) -> Path:
    """What Windows shows under a program's Properties, Details: name, version, what it is."""
    numbers = ".".join((__version__.split(".") + ["0", "0", "0"])[:4])
    path = BUILD / (title.replace(" ", "") + ".version.cs")
    path.write_text(
        "using System.Reflection;\n"
        f'[assembly: AssemblyTitle("{title}")]\n'
        f'[assembly: AssemblyDescription("{about}")]\n'
        f'[assembly: AssemblyProduct("{APP_NAME}")]\n'
        f'[assembly: AssemblyCompany("{APP_NAME}")]\n'
        f'[assembly: AssemblyCopyright("{APP_NAME}, free to use and share")]\n'
        f'[assembly: AssemblyVersion("{numbers}")]\n'
        f'[assembly: AssemblyFileVersion("{numbers}")]\n'
        f'[assembly: AssemblyInformationalVersion("{__version__}")]\n'
        f'static class Build {{ public const string Version = "{__version__}"; }}\n',
        encoding="utf-8-sig",
    )
    return path


def compile_cs(out: Path, sources: list, icon: Path, manifest: Path, resources=()) -> None:
    command = [str(compiler()), "/nologo", "/target:winexe", "/platform:x64", "/optimize+", "/codepage:65001", "/warn:4", f"/out:{out}", f"/win32icon:{icon}", f"/win32manifest:{manifest}"]
    command += [f"/reference:{name}" for name in REFERENCES]
    command += [f"/resource:{path},{name}" for path, name in resources]
    command += [str(source) for source in sources]
    done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if done.returncode or done.stdout.strip():
        print(done.stdout.strip())
    if done.returncode:
        raise SystemExit(f"{out.name} did not compile.")


def icon() -> Path:
    BUILD.mkdir(parents=True, exist_ok=True)
    return tray.write_icon(BUILD / "workcat.ico", "grey", sizes=(16, 32, 48, 64, 128, 256))


def host() -> Path:
    """MyCat.exe: the small program that starts the cat on the Python next to it."""
    out = STAGE / f"{APP_NAME}.exe"
    compile_cs(out, [SOURCES / "host.cs", SOURCES / "common.cs", version_file(APP_NAME, "A cat for your desktop")], icon(), SOURCES / "host.manifest")
    return out


def setup() -> Path:
    """The setup program, with everything in the staged folder added at its end as a zip.

    Python's zipfile, asked to append to a file that is not a zip, writes an archive whose
    table of contents counts from the start of the whole file. That makes the finished
    .exe a valid zip as it stands (a self-extracting archive): the setup program opens
    itself as one, and so can 7-Zip or an antivirus program."""
    DIST.mkdir(parents=True, exist_ok=True)
    out = DIST / f"{APP_NAME}-{__version__}-setup.exe"
    compile_cs(
        out,
        [SOURCES / "setup.cs", SOURCES / "common.cs", version_file(f"{APP_NAME} Setup", f"Installs {APP_NAME}, a cat for your desktop")],
        icon(),
        SOURCES / "setup.manifest",
        resources=[(icon(), "workcat.ico")],
    )
    with zipfile.ZipFile(out, "a", zipfile.ZIP_DEFLATED, compresslevel=9) as parcel:
        for path in sorted(STAGE.rglob("*")):
            if path.is_file():
                parcel.write(path, path.relative_to(STAGE).as_posix())
    with zipfile.ZipFile(out) as parcel:  # read back the way anybody else would
        broken = parcel.testzip()
        if broken:
            raise SystemExit(f"the installer's contents do not read back: {broken}")
    return out


def size(path: Path) -> str:
    total = path.stat().st_size if path.is_file() else sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    return f"{total / (1 << 20):.1f} MB"


def live(exe: Path, data: Path, seconds: int = 45) -> list:
    """Let the installed copy live for a while on a throwaway data folder, as it would on
    somebody's desk: its loops run, a second start only calls the first, and it leaves
    when the setup program asks. Returns what went wrong."""
    from workcat.app import instance_name

    data.mkdir(parents=True, exist_ok=True)
    quiet = {"first_run_done": True, "language": "en", "learn_routine": False, "learn_sites": False, "learn_media": False, "chatter": "off", "goals_ask": False, "recap": False, "week_note": False, "weather": False}  # (and it asks no service for the weather)
    (data / "settings.json").write_text(json.dumps(quiet), encoding="utf-8")
    name = instance_name(data)
    wrong: list = []
    cat = subprocess.Popen([str(exe), "--wait", "--data", str(data)])  # --wait: MyCat.exe stays for as long as the cat it started
    try:
        for _ in range(100):  # until it is there
            if tray._FindWindowW(tray.WINDOW_CLASS, name):
                break
            time.sleep(0.2)
        else:
            return ["the installed copy did not come up"]
        time.sleep(seconds)
        if cat.poll() is not None:
            return [f"the installed copy stopped by itself (exit {cat.returncode})"]
        again = subprocess.run([str(exe), "--wait", "--data", str(data)], timeout=30)  # as if its shortcut were clicked once more
        if again.returncode or cat.poll() is not None:
            wrong.append(f"a second start did not simply call the first (exit {again.returncode})")
        time.sleep(2)
        window = tray._FindWindowW(tray.WINDOW_CLASS, name)
        tray._PostMessageW(window, tray._RegisterWindowMessageW(tray.ASK_QUIT), 0, 0)
        try:
            code = cat.wait(timeout=10)
            if code:
                wrong.append(f"it left with exit {code}")
        except subprocess.TimeoutExpired:
            wrong.append("it did not leave when asked")
    finally:
        if cat.poll() is None:
            cat.kill()
            cat.wait(timeout=10)
    log = (data / "workcat.log").read_text(encoding="utf-8", errors="replace") if (data / "workcat.log").is_file() else ""
    bad = [line for line in log.splitlines() if " ERROR " in line or line.startswith("Traceback")]
    wrong += [f"in its log: {line}" for line in bad[:5]]
    print(f"lived {seconds} s on its own data folder: {'fine' if not wrong else 'NOT fine'}; log lines: {len(log.splitlines())}")
    return wrong


def test(installer: Path) -> int:
    """Install into a temporary folder (files only: no shortcuts, nothing in the registry),
    let that copy check itself and live for a while, then uninstall it."""
    folder = Path(tempfile.mkdtemp(prefix="workcat-install-")) / APP_NAME
    report = folder.parent / "check.json"
    print(f"installing into {folder}")
    done = subprocess.run([str(installer), "/S", "/test", "/nostart", f"/D={folder}"], timeout=180)
    exe = folder / f"{APP_NAME}.exe"
    if done.returncode or not exe.is_file():
        print("the installer failed", done.returncode)
        return 1
    files = sum(1 for p in folder.rglob("*") if p.is_file())
    print(f"installed: {files} files, {size(folder)}")
    started = time.monotonic()
    checked = subprocess.run([str(exe), "--check", str(report)], timeout=120)
    print(f"self-check: exit {checked.returncode} after {time.monotonic() - started:.1f} s")
    problems = ["no report was written"]
    if report.is_file():
        facts = json.loads(report.read_text(encoding="utf-8"))
        problems = facts.pop("problems", [])
        for key, value in facts.items():
            print(f"   {key}: {value}")
    problems += live(exe, folder.parent / "data")
    for problem in problems:
        print("   PROBLEM:", problem)
    gone = subprocess.run([str(exe), "--uninstall", "/S"], timeout=60)
    for _ in range(40):  # the folder is removed a moment after the program has left
        if not folder.exists():
            break
        time.sleep(0.5)
    print(f"uninstall: exit {gone.returncode}, folder {'removed' if not folder.exists() else 'STILL THERE'}")
    shutil.rmtree(folder.parent, ignore_errors=True)
    return 1 if problems or checked.returncode or gone.returncode or folder.exists() else 0


def main() -> int:
    stage()
    exe = host()
    print(f"{STAGE}  ({size(STAGE)}, {sum(1 for p in STAGE.rglob('*') if p.is_file())} files)")
    print(f"{exe.name}  ({exe.stat().st_size / 1024:.0f} KB)")
    if "--stage" in sys.argv:
        return 0
    installer = setup()
    print(f"{installer}  ({size(installer)})")
    return test(installer) if "--test" in sys.argv else 0


if __name__ == "__main__":
    sys.exit(main())
