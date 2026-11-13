"""Which kind of work a program is, and what to call it.

A "place" is where you are working: a program ("excel"), or, inside a browser, a
well-known site ("site:youtube"). Sites are recognised from the tab's title, which is
compared with the list below and then thrown away: only the site's name is kept.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass

from .i18n import N_

CATEGORY_NAMES = {
    "code": N_("Coding"),
    "office": N_("Office & documents"),
    "design": N_("Design & media making"),
    "study": N_("Study & reading"),
    "comms": N_("Calls & chat"),
    "ai": N_("AI tools"),
    "browser": N_("Browsing"),
    "media": N_("Music & video"),
    "social": N_("Social"),
    "game": N_("Games"),
    "other": N_("Other"),
    "system": N_("Windows"),
}
CATEGORIES = tuple(CATEGORY_NAMES)

_APPS = {
    "code": "code code-insiders cursor windsurf zed devenv pycharm64 pycharm idea64 webstorm64 clion64 rider64 goland64 phpstorm64 "
    "rustrover64 datagrip64 dataspell64 studio64 sublime_text notepad++ atom eclipse netbeans64 rstudio spyder jupyterlab "
    "windowsterminal wt powershell pwsh cmd conhost mintty git-bash gitkraken githubdesktop sourcetree postman insomnia "
    "dbeaver ssms pgadmin4 mysqlworkbench heidisql unity unityhub unrealeditor godot matlab octave-gui vim nvim-qt gvim emacs "
    "docker~desktop putty winscp filezilla wireshark fiddler anaconda-navigator",
    "office": "winword excel powerpnt outlook olk hxoutlook onenote msaccess mspub visio winproj soffice swriter scalc simpress "
    "wps et wpp notion obsidian evernote thunderbird acrobat acrord32 foxitpdfreader foxitreader pdfxedit 1cv8 1cv8c 1cv8s "
    "trello todoist ticktick notepad wordpad calculatorapp calc onedrive lync powerbi pbidesktop tableau quickbooks",
    "design": "photoshop illustrator indesign afterfx lightroom lightroomclassic acad blender figma sketchup coreldrw gimp-2.10 "
    "gimp-3.0 gimp inkscape krita mspaint paintdotnet resolve vegas capcut obs64 audacity fl64 fl ableton 3dsmax maya "
    "revit archicad sldworks fusion360 zbrush clipstudiopaint aseprite canva affinityphoto affinitydesigner premiere xd "
    "davinciresolve shotcut kdenlive openshot-qt handbrake reaper cubase studio~one bridge animate rhino cinema~4d",
    "study": "anki zotero mendeley calibre kindle sumatrapdf duolingo mathematica geogebra okular ebook-viewer wolframalpha",
    "comms": "teams ms-teams zoom slack discord telegram whatsapp skype viber webexmta ciscocollabhost signal wechat lark feishu "
    "mattermost element zalo line imo dingtalk",
    "ai": "claude chatgpt copilot lmstudio ollama~app gpt4all msty jan",
    "browser": "chrome msedge firefox opera opera_gx brave vivaldi browser arc iexplore chromium librewolf waterfox thorium zen "
    "duckduckgo",
    "media": "spotify vlc wmplayer mediaplayer mpc-hc64 mpc-hc mpc-be64 potplayermini64 potplayer64 kmplayer itunes applemusic "
    "musicbee foobar2000 aimp winamp netflix yandexmusic video.ui stremio plex tidal deezer amazonmusic mpv music.ui "
    "microsoft.media.player",
    "game": "steam steamwebhelper epicgameslauncher battle.net riotclientux leagueclientux valorant cs2 dota2 minecraft "
    "minecraftlauncher robloxplayerbeta gta5 fortniteclient-win64-shipping genshinimpact eldenring gog~galaxy origin eadesktop",
    "system": "explorer searchhost searchapp startmenuexperiencehost shellexperiencehost lockapp applicationframehost "
    "textinputhost taskmgr systemsettings dwm ctfmon snippingtool screenclippinghost credentialuibroker consent python "
    "pythonw py pyw workcat pickerhost openwith rundll32 mmc regedit control msiexec setup dllhost sihost logonui "
    "shellhost widgets widgetboard taskhostw backgroundtaskhost runtimebroker searchui screensketch lockscreen "
    "useroobebroker securityhealthsystray smartscreen",
}
# '~' stands for a space inside a program's name
EXE_CATEGORY = {stem.replace("~", " "): category for category, stems in _APPS.items() for stem in stems.split()}

# Short names people actually say, for the commonest programs.
KNOWN_NAMES = {
    "code": "VS Code", "winword": "Word", "excel": "Excel", "powerpnt": "PowerPoint", "outlook": "Outlook", "olk": "Outlook",
    "onenote": "OneNote", "chrome": "Chrome", "msedge": "Edge", "firefox": "Firefox", "opera": "Opera", "brave": "Brave",
    "explorer": "File Explorer", "windowsterminal": "Terminal", "wt": "Terminal", "cmd": "Command Prompt", "powershell": "PowerShell",
    "pwsh": "PowerShell", "ms-teams": "Teams", "teams": "Teams", "acrord32": "Acrobat Reader", "acrobat": "Acrobat",
    "1cv8": "1C:Enterprise", "1cv8c": "1C:Enterprise", "1cv8s": "1C:Enterprise", "devenv": "Visual Studio",
    "pycharm64": "PyCharm", "idea64": "IntelliJ IDEA", "notepad++": "Notepad++", "notepad": "Notepad", "mspaint": "Paint",
    "obs64": "OBS", "fl64": "FL Studio", "soffice": "LibreOffice", "vlc": "VLC", "wmplayer": "Media Player",
    "photoshop": "Photoshop", "illustrator": "Illustrator", "afterfx": "After Effects", "resolve": "DaVinci Resolve",
    "acad": "AutoCAD", "sldworks": "SolidWorks", "calculatorapp": "Calculator", "telegram": "Telegram", "whatsapp": "WhatsApp",
}

# File descriptions that say nothing about which program it is.
_VAGUE = {"", "electron", "chromium", "application", "launcher", "host process for windows services"}

BROWSERS = frozenset(stem for stem, category in EXE_CATEGORY.items() if category == "browser")


@dataclass(frozen=True)
class Site:
    key: str
    name: str
    category: str
    url: str
    marks: tuple  # what a segment of the tab title must equal


def _sites() -> list:
    rows = [
        ("youtube music", "YouTube Music", "media", "https://music.youtube.com"),
        ("youtube", "YouTube", "media", "https://www.youtube.com"),
        ("netflix", "Netflix", "media", "https://www.netflix.com"),
        ("twitch", "Twitch", "media", "https://www.twitch.tv"),
        ("spotify", "Spotify", "media", "https://open.spotify.com"),
        ("soundcloud", "SoundCloud", "media", "https://soundcloud.com"),
        ("gmail", "Gmail", "office", "https://mail.google.com"),
        ("outlook", "Outlook", "office", "https://outlook.office.com"),
        ("google calendar", "Google Calendar", "office", "https://calendar.google.com"),
        ("google docs", "Google Docs", "office", "https://docs.google.com/document"),
        ("google sheets", "Google Sheets", "office", "https://docs.google.com/spreadsheets"),
        ("google slides", "Google Slides", "office", "https://docs.google.com/presentation"),
        ("google drive", "Google Drive", "office", "https://drive.google.com"),
        ("notion", "Notion", "office", "https://www.notion.so"),
        ("trello", "Trello", "office", "https://trello.com"),
        ("jira", "Jira", "office", ""),
        ("confluence", "Confluence", "office", ""),
        ("github", "GitHub", "code", "https://github.com"),
        ("gitlab", "GitLab", "code", "https://gitlab.com"),
        ("stack overflow", "Stack Overflow", "code", "https://stackoverflow.com"),
        ("colab", "Google Colab", "code", "https://colab.research.google.com"),
        ("jupyterlab", "Jupyter", "code", ""),
        ("jupyter notebook", "Jupyter", "code", ""),
        ("kaggle", "Kaggle", "code", "https://www.kaggle.com"),
        ("hugging face", "Hugging Face", "code", "https://huggingface.co"),
        ("chatgpt", "ChatGPT", "ai", "https://chatgpt.com"),
        ("claude", "Claude", "ai", "https://claude.ai"),
        ("google gemini", "Gemini", "ai", "https://gemini.google.com"),
        ("gemini", "Gemini", "ai", "https://gemini.google.com"),
        ("perplexity", "Perplexity", "ai", "https://www.perplexity.ai"),
        ("figma", "Figma", "design", "https://www.figma.com"),
        ("canva", "Canva", "design", "https://www.canva.com"),
        ("miro", "Miro", "design", "https://miro.com"),
        ("behance", "Behance", "design", "https://www.behance.net"),
        ("dribbble", "Dribbble", "design", "https://dribbble.com"),
        ("pinterest", "Pinterest", "design", "https://www.pinterest.com"),
        ("wikipedia", "Wikipedia", "study", "https://www.wikipedia.org"),
        ("coursera", "Coursera", "study", "https://www.coursera.org"),
        ("udemy", "Udemy", "study", "https://www.udemy.com"),
        ("khan academy", "Khan Academy", "study", "https://www.khanacademy.org"),
        ("duolingo", "Duolingo", "study", "https://www.duolingo.com"),
        ("overleaf", "Overleaf", "study", "https://www.overleaf.com"),
        ("google scholar", "Google Scholar", "study", "https://scholar.google.com"),
        ("google translate", "Google Translate", "study", "https://translate.google.com"),
        ("whatsapp", "WhatsApp", "comms", "https://web.whatsapp.com"),
        ("telegram web", "Telegram", "comms", "https://web.telegram.org"),
        ("telegram", "Telegram", "comms", "https://web.telegram.org"),
        ("slack", "Slack", "comms", "https://app.slack.com"),
        ("discord", "Discord", "comms", "https://discord.com/app"),
        ("microsoft teams", "Teams", "comms", "https://teams.microsoft.com"),
        ("google meet", "Google Meet", "comms", "https://meet.google.com"),
        ("meet", "Google Meet", "comms", "https://meet.google.com"),
        ("zoom", "Zoom", "comms", "https://zoom.us"),
        ("linkedin", "LinkedIn", "social", "https://www.linkedin.com"),
        ("facebook", "Facebook", "social", "https://www.facebook.com"),
        ("instagram", "Instagram", "social", "https://www.instagram.com"),
        ("x", "X", "social", "https://x.com"),
        ("twitter", "X", "social", "https://x.com"),
        ("reddit", "Reddit", "social", "https://www.reddit.com"),
        ("tiktok", "TikTok", "social", "https://www.tiktok.com"),
    ]
    by_key: dict = {}
    for mark, name, category, url in rows:
        key = "site:" + name.lower().replace(" ", "")
        site = by_key.get(key)
        by_key[key] = Site(key, name, category, url, (site.marks if site else ()) + (mark,))
    return list(by_key.values())


SITES = _sites()
SITE_BY_KEY = {site.key: site for site in SITES}
_MARKS = {mark: site for site in SITES for mark in site.marks}

_SPLIT = re.compile(r"\s+[-–—|·/:]\s+|\s+[-–—|·]$|^[-–—|·]\s+")
_COUNTER = re.compile(r"^[\(\[]\d+\+?[\)\]]\s*|^[•●*]\s*")


def site_of_title(title: str):
    """The well-known site a browser tab shows, judged by its title, or None.

    Sites put their name in a segment of its own ("Video - YouTube - Chrome"), so only a
    whole segment counts: a page that merely mentions YouTube is not YouTube.
    """
    if not title:
        return None
    segments = [_COUNTER.sub("", part).strip().lower().replace("​", "") for part in _SPLIT.split(title)]
    segments = [part for part in segments if part]
    for part in reversed(segments[-4:]):  # the site's name sits near the end, before the browser's
        site = _MARKS.get(part) or _with_tab_count(part)
        if site:
            return site
    if segments:
        return _MARKS.get(segments[0])
    return None


def _with_tab_count(segment: str):
    """Edge writes "YouTube and 3 more pages" (in the system's language) when a window
    has several tabs: the site's name, then words with a number in them."""
    for mark, site in _MARKS.items():
        if segment.startswith(mark + " ") and any(ch.isdigit() for ch in segment[len(mark):]):
            return site
    return None


def stem_of(path: str) -> str:
    name = os.path.basename(path).lower()
    return name[:-4] if name.endswith(".exe") else name


_COPY = re.compile(r"[\s_.\-]*\d+(\.\d+)*$")  # "telegram_2", "python3.14": a copy or a version


def base_stem(stem: str) -> str:
    """The stem as the lists know it: itself, or without a trailing copy/version number."""
    if stem in EXE_CATEGORY:
        return stem
    plain = _COPY.sub("", stem)
    return plain if plain in EXE_CATEGORY else stem


def category_of(stem: str) -> str:
    stem = base_stem(stem)
    if stem in EXE_CATEGORY:
        return EXE_CATEGORY[stem]
    for prefix, category in (("gimp", "design"), ("pycharm", "code"), ("idea", "code"), ("adobe", "design"), ("jetbrains", "code")):
        if stem.startswith(prefix):
            return category
    return "other"


def pretty_name(stem: str, description: str = "") -> str:
    stem = base_stem(stem)
    if stem in KNOWN_NAMES:
        return KNOWN_NAMES[stem]
    text = (description or "").strip()
    if text.lower() not in _VAGUE and len(text) <= 40:
        return text
    return re.sub(r"[-_.]+", " ", stem).strip().title() or "This app"


@dataclass(frozen=True)
class Place:
    id: str
    name: str
    category: str
    path: str  # the program to start to get there
    url: str = ""  # for a site


def identify(path: str, description: str = "", title: str = "") -> Place:
    """The place for a foreground window. Pass the title only for browsers, and only if
    the person allowed site recognition."""
    stem = stem_of(path)
    category = category_of(stem)
    if category == "browser" and title:
        site = site_of_title(title)
        if site:
            return Place(site.key, site.name, site.category, path, site.url)
    return Place(stem, pretty_name(stem, description), category, path)


# --------------------------------------------------------------------------- opening things by name
#
# "Open Excel", said to the cat's AI. The AI only ever gives a name. What that name may
# start is decided here, from four fixed places: Windows' own tools (the table below),
# the programs the cat has seen you use, the shortcuts in your Start menu, and the sites
# it knows. Nothing the AI writes is run as a command or opened as a path.

# Windows' own tools, by the names people call them (English, Russian, Uzbek in both
# alphabets). '~' stands for a space inside a name.
_TOOLS = (
    ("calc.exe", "Calculator", "calculator calc калькулятор kalkulyator ҳисоблагич hisoblagich"),
    ("notepad.exe", "Notepad", "notepad блокнот bloknot"),
    ("mspaint.exe", "Paint", "paint пэйнт"),
    ("explorer.exe", "File Explorer", "explorer file~explorer files проводник файлы файллар fayllar this~pc my~computer этот~компьютер мой~компьютер"),
    ("ms-settings:", "Settings", "settings windows~settings параметры настройки~windows созламалар sozlamalar"),
    ("taskmgr.exe", "Task Manager", "task~manager диспетчер~задач"),
    ("ms-screenclip:", "Snipping Tool", "snipping~tool screenshot ножницы скриншот skrinshot"),
    ("wt.exe", "Terminal", "terminal windows~terminal терминал"),
    ("cmd.exe", "Command Prompt", "command~prompt cmd командная~строка"),
    ("control.exe", "Control Panel", "control~panel панель~управления boshqaruv~paneli бошқарув~панели"),
    ("ms-clock:", "Clock", "clock alarms часы будильник"),
    ("ms-photos:", "Photos", "photos фотографии"),
    ("ms-windows-store:", "Microsoft Store", "store microsoft~store магазин"),
    ("microsoft.windows.camera:", "Camera", "camera камера kamera"),
)
_NOT_PROGRAMS = re.compile(r"uninstall|удал|readme|read me|help|справка|documentation|документац|license|лиценз|website|web site|release notes|manual|what's new|changelog|repair|setup|install", re.I)
_ADDRESS = re.compile(r"^(?:https?://)?(?:www\.)?((?:[a-z0-9-]+\.)+[a-z]{2,})(/\S*)?$", re.I)
_shortcut_cache: dict = {}


@dataclass(frozen=True)
class Target:
    """Something that can be opened: what to call it, and where it is."""
    name: str
    kind: str  # "tool", "place", "shortcut" or "site"
    what: str  # the fixed command, the place's id, the shortcut's path, or the address


def plain_name(name: str) -> str:
    """A name as it is compared: small letters, single spaces, no signs."""
    return " ".join(re.sub(r"[^\w+#]+", " ", name.lower().replace("_", " ")).split())


def start_menu_folders() -> list:
    found = []
    for base in (os.environ.get("APPDATA"), os.environ.get("PROGRAMDATA")):
        if base:
            found.append(os.path.join(base, "Microsoft", "Windows", "Start Menu", "Programs"))
    return found


def shortcuts(folders=None, fresh: bool = False) -> dict:
    """The programs in the Start menu: plain name -> (name, path of the shortcut).
    Looked up at most once every few minutes."""
    folders = tuple(start_menu_folders() if folders is None else folders)
    cached = _shortcut_cache.get(folders)
    if cached and not fresh and time.monotonic() - cached[0] < 300:
        return cached[1]
    found: dict = {}
    for folder in folders:
        for root, _dirs, files in os.walk(folder):
            for file in files:
                name, kind = os.path.splitext(file)
                if kind.lower() not in (".lnk", ".appref-ms") or _NOT_PROGRAMS.search(name):
                    continue
                found.setdefault(plain_name(name), (name, os.path.join(root, file)))
    _shortcut_cache[folders] = (time.monotonic(), found)
    return found


def _fits(want: str, have: str) -> bool:
    """Whether a name asked for means a name there is: the same, or one made of whole
    words of the other ("chrome" and "google chrome", "microsoft excel" and "excel")."""
    if not want or not have:
        return False
    if want == have:
        return True
    a, b = set(want.split()), set(have.split())
    return (a <= b or b <= a) and max(len(word) for word in a & b) >= 3


def find_target(name: str, places: dict, links=None):
    """What a name given by the AI stands for, or None. `places` are the programs and
    sites the cat has seen (store.places()); `links` the Start menu (shortcuts())."""
    want = plain_name(name)
    if not want:
        return None
    for command, shown, names in _TOOLS:
        if want in (alias.replace("~", " ") for alias in names.split()) or want == plain_name(shown):
            return Target(shown, "tool", command)
    links = shortcuts() if links is None else links
    programs = [row for row in places.values() if not row["place"].startswith("site:") and row.get("category") != "system" and row.get("path")]
    sites = [site for site in SITES if site.url]
    for exact in (True, False):  # a name that is exactly right wins over one that only fits
        same = (lambda have: want == have) if exact else (lambda have: _fits(want, have))
        found = [row for row in programs if same(plain_name(row["name"])) or same(plain_name(row["place"]))]
        if found:
            row = max(found, key=lambda row: row.get("last_seen") or 0)
            return Target(row["name"], "place", row["place"])
        found = [key for key in links if same(key)]
        if found:
            shown, path = links[min(found, key=len)]
            return Target(shown, "shortcut", path)
        found = [site for site in sites if same(plain_name(site.name)) or any(same(mark) for mark in site.marks)]
        if found:
            return Target(found[0].name, "site", found[0].url)
    return None


def typed_address(name: str, said: str) -> str:
    """The web address in `name`, but only if the person typed that very address
    themselves in `said`. An address the AI came up with is not opened."""
    match = _ADDRESS.match(name.strip())
    if not match:
        return ""
    host, path = match.group(1).lower(), match.group(2) or ""
    low = said.lower()
    if host not in low:
        return ""
    return "https://" + host + (path if (host + path).lower() in low else "")


def openable(places: dict, most: int = 14) -> list:
    """Names the AI is told it can open: what you used most recently."""
    rows = [row for row in places.values() if row.get("category") != "system" and row.get("name")]
    rows.sort(key=lambda row: -(row.get("last_seen") or 0))
    names: list = []
    for row in rows:
        if row["name"] not in names:
            names.append(row["name"])
    return names[:most]
