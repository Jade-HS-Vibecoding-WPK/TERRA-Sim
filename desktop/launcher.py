"""TERRA-Sim als Desktop-App.

Doppelklick auf ``TERRA-Sim.exe``:

1. Ein kleines Startfenster zeigt „TERRA-Sim startet …“.
2. Das Programm startet sich selbst noch einmal mit ``--server PORT`` im Hintergrund –
   der Streamlit-Server, nur auf diesem Rechner erreichbar (127.0.0.1).
3. Sobald der Server antwortet, öffnet sich ein eigenes App-Fenster: Microsoft Edge oder
   Google Chrome im App-Modus (ohne Adressleiste, mit eigenem Profil). Gibt es beide nicht,
   öffnet sich der Standard-Browser, und das Startfenster bleibt zum Beenden stehen.
4. Schließt man das App-Fenster, endet auch der Server.

Zwischenspeicher (``.cache``), Fenster-Profil und Protokolle liegen im Benutzerordner:
``%LOCALAPPDATA%\\TERRA-Sim`` unter Windows, sonst ``~/.terra-sim``.

Aus dem Quellcode lässt sich derselbe Ablauf mit ``python desktop/launcher.py`` starten.
Weitere Aufrufe:

* ``--server PORT``     nur den Server starten
* ``--selftest DATEI``  prüfen, ob im fertigen Programm alles enthalten ist (Release-Workflow)
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

APP_NAME = "TERRA-Sim"
FROZEN = getattr(sys, "frozen", False)
NO_CONSOLE = 0x08000000 if os.name == "nt" else 0          # subprocess.CREATE_NO_WINDOW
START_TIMEOUT_S = 180
GREEN, DARK, LIGHT = "#1f7a4d", "#10291d", "#f1f8f3"


# --------------------------------------------------------------------------
# Ordner
# --------------------------------------------------------------------------

def bundle_dir() -> Path:
    """Wo app.py, assets/ und .streamlit/ liegen (im fertigen Programm: sys._MEIPASS)."""
    return Path(sys._MEIPASS) if FROZEN else Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """Beschreibbarer Ordner des Benutzers für Zwischenspeicher, Profil und Protokolle."""
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        path = Path(os.environ["LOCALAPPDATA"]) / APP_NAME
    else:
        path = Path.home() / ".terra-sim"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _log_to(name: str):
    """Fensterprogramme haben keine Konsole: Ausgaben in eine Protokolldatei umleiten."""
    if sys.stdout is None or sys.stderr is None:
        log = open(data_dir() / name, "a", encoding="utf-8", buffering=1)
        sys.stdout, sys.stderr = sys.stdout or log, sys.stderr or log


# --------------------------------------------------------------------------
# Server (läuft im zweiten Prozess)
# --------------------------------------------------------------------------

def run_server(port: int):
    """Wie ``streamlit run app.py`` – mit dem Benutzerordner als Arbeitsordner."""
    _log_to("server.log")
    root, home = bundle_dir(), data_dir()
    os.chdir(home)                                          # .cache/ landet im Benutzerordner
    config = home / ".streamlit" / "config.toml"            # Farbschema der App
    config.parent.mkdir(exist_ok=True)
    shutil.copyfile(root / ".streamlit" / "config.toml", config)
    sys.path.insert(0, str(root))

    from streamlit.web import cli
    sys.argv = ["streamlit", "run", str(root / "app.py"),
                "--server.port", str(port), "--server.address", "127.0.0.1",
                "--server.headless", "true", "--server.fileWatcherType", "none",
                "--global.developmentMode", "false", "--browser.gatherUsageStats", "false"]
    sys.exit(cli.main())


def healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=1) as response:
            return response.read().strip() == b"ok"
    except OSError:
        return False


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def running_instance() -> int | None:
    """Port einer schon laufenden TERRA-Sim-Instanz (dann nur ein weiteres Fenster öffnen)."""
    try:
        port = json.loads((data_dir() / "instance.json").read_text(encoding="utf-8"))["port"]
        return port if healthy(port) else None
    except (OSError, ValueError, KeyError):
        return None


# --------------------------------------------------------------------------
# App-Fenster
# --------------------------------------------------------------------------

def find_app_browser() -> str | None:
    """Edge oder Chrome – beide können eine Seite als eigenes App-Fenster zeigen."""
    candidates = []
    for env in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            candidates += [Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                           Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"]
    for name in ("msedge", "microsoft-edge", "google-chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    return next((str(c) for c in candidates if c.exists()), None)


def _child_pids(pid: int) -> list[int]:
    """Prozesse, die ``pid`` gestartet hat (Windows-Prozessliste über die Toolhelp-Schnittstelle)."""
    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.Process32FirstW.argtypes = k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = k32.CreateToolhelp32Snapshot(0x2, 0)               # TH32CS_SNAPPROCESS
    entry, children = Entry(), []
    entry.dwSize = ctypes.sizeof(Entry)
    more = k32.Process32FirstW(snapshot, ctypes.byref(entry))
    while more:
        if entry.th32ParentProcessID == pid:
            children.append(int(entry.th32ProcessID))
        more = k32.Process32NextW(snapshot, ctypes.byref(entry))
    k32.CloseHandle(snapshot)
    return children


def _alive(pid: int) -> bool:
    """Läuft der Prozess noch? (Windows)"""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = k32.OpenProcess(0x00100000 | 0x1000, False, pid)    # SYNCHRONIZE | QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        return k32.WaitForSingleObject(handle, 0) == 0x102        # WAIT_TIMEOUT = läuft noch
    finally:
        k32.CloseHandle(handle)


class AppWindow:
    """Das App-Fenster als Prozess, den man beobachten kann.

    Edge beendet den gestarteten Prozess nach einer halben Sekunde und übergibt an einen
    eigenen Browser-Prozess (Kindprozess). Dem folgen wir. Findet sich kein Kindprozess,
    hat der Browser an ein schon offenes Fenster übergeben – dann „unbekannt“.
    """

    def __init__(self, process: subprocess.Popen):
        self.process, self.pid, self.started = process, None, time.time()

    def state(self) -> str:
        """``starting`` | ``open`` | ``closed`` | ``unknown``"""
        if self.pid is None:
            if self.process.poll() is None:
                if time.time() - self.started < 3:
                    return "starting"
                self.pid = self.process.pid                         # der Browser bleibt selbst der Prozess
                return "open"
            children = _child_pids(self.process.pid)
            if not children:
                return "unknown"
            self.pid = children[0]
        if self.pid == self.process.pid:
            return "open" if self.process.poll() is None else "closed"
        return "open" if _alive(self.pid) else "closed"


def open_window(url: str) -> AppWindow | None:
    """App-Fenster öffnen. Rückgabe: das beobachtbare Fenster (oder None beim Standard-Browser)."""
    if os.environ.get("TERRA_SIM_NO_WINDOW"):               # für Tests
        return None
    browser = find_app_browser()
    if browser:
        return AppWindow(subprocess.Popen([browser, f"--app={url}", f"--user-data-dir={data_dir() / 'fenster'}",
                                           "--no-first-run", "--no-default-browser-check",
                                           "--window-size=1440,920"]))
    webbrowser.open(url)
    return None


class StartWindow:
    """Kleines Fenster: Start-Fortschritt, Fehler, „Beenden“."""

    def __init__(self, on_quit):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.geometry("460x230")
        self.root.resizable(False, False)
        self.root.configure(bg=LIGHT)
        try:
            self.root.iconbitmap(str(bundle_dir() / "icon.ico"))
        except tk.TclError:
            pass
        header = tk.Frame(self.root, bg=GREEN, height=70)
        header.pack(fill="x")
        tk.Label(header, text="TERRA-Sim", bg=GREEN, fg="white", font=("Segoe UI", 20, "bold")).pack(
            side="left", padx=20, pady=14)
        self.status = tk.Label(self.root, text="TERRA-Sim startet …", bg=LIGHT, fg=DARK, font=("Segoe UI", 11),
                               wraplength=420, justify="left")
        self.status.pack(anchor="w", padx=20, pady=(16, 8))
        self.bar = ttk.Progressbar(self.root, mode="indeterminate", length=420)
        self.bar.pack(padx=20)
        self.bar.start(12)
        buttons = tk.Frame(self.root, bg=LIGHT)
        buttons.pack(fill="x", padx=20, pady=16)
        tk.Button(buttons, text="Beenden", command=on_quit, relief="flat", bg="#e2f3e6", fg=DARK,
                  padx=14).pack(side="right")
        self.open_button = tk.Button(buttons, text="Im Browser öffnen", relief="flat", bg=GREEN, fg="white", padx=14)
        self.root.protocol("WM_DELETE_WINDOW", on_quit)

    def say(self, text: str):
        self.status.configure(text=text)

    def running_in_browser(self, url: str):
        self.bar.stop()
        self.bar.pack_forget()
        self.say(f"TERRA-Sim läuft im Browser:\n{url}\n\nDieses Fenster offen lassen – „Beenden“ stoppt TERRA-Sim.")
        self.open_button.configure(command=lambda: webbrowser.open(url))
        self.open_button.pack(side="right", padx=8)
        self.root.deiconify()

    def error(self, text: str):
        self.bar.stop()
        self.say(text)
        self.root.deiconify()


def main():
    args = sys.argv[1:]
    if args[:1] == ["--server"]:
        run_server(int(args[1]))
        return
    if args[:1] == ["--selftest"]:
        sys.exit(selftest(Path(args[1])))
    _log_to("terra-sim.log")

    port = running_instance()
    if port:                                                # läuft schon: nur ein weiteres Fenster
        if open_window(f"http://127.0.0.1:{port}") is None:
            webbrowser.open(f"http://127.0.0.1:{port}")
        return

    port = free_port()
    url = f"http://127.0.0.1:{port}"
    log_path = data_dir() / "server.log"
    log = open(log_path, "w", encoding="utf-8")
    me = [sys.executable] if FROZEN else [sys.executable, str(Path(__file__).resolve())]
    server = subprocess.Popen([*me, "--server", str(port)], stdout=log, stderr=subprocess.STDOUT,
                              creationflags=NO_CONSOLE)
    instance = data_dir() / "instance.json"
    instance.write_text(json.dumps({"port": port, "pid": server.pid}), encoding="utf-8")
    state = {"started": time.time(), "opened": None, "browser": None}

    def quit_app():
        if server.poll() is None:
            server.terminate()
        instance.unlink(missing_ok=True)
        window.root.destroy()

    window = StartWindow(quit_app)

    def poll():
        if server.poll() is not None:
            window.error(f"TERRA-Sim konnte nicht starten.\nProtokoll: {log_path}")
            return
        if state["opened"] is None:
            if healthy(port):
                state["browser"], state["opened"] = open_window(url), time.time()
                if state["browser"] is None:
                    window.running_in_browser(url)
                else:
                    window.root.withdraw()
            elif time.time() - state["started"] > START_TIMEOUT_S:
                window.error(f"TERRA-Sim antwortet nicht.\nProtokoll: {log_path}")
                return
            else:
                window.say(f"TERRA-Sim startet … ({time.time() - state['started']:.0f} s)\n"
                           "Beim ersten Start kann das etwas dauern.")
        elif state["browser"] is not None:
            app_state = state["browser"].state()
            if app_state == "closed":
                quit_app()                                  # App-Fenster geschlossen -> Ende
                return
            if app_state == "unknown":
                # Der Browser hat an ein schon offenes Fenster übergeben – wann es geschlossen
                # wird, wissen wir nicht: Startfenster mit „Beenden“ zeigen.
                state["browser"] = None
                window.running_in_browser(url)
        window.root.after(500, poll)

    window.root.after(200, poll)
    window.root.mainloop()


# --------------------------------------------------------------------------
# Selbsttest (Release-Workflow)
# --------------------------------------------------------------------------

def selftest(report: Path) -> int:
    """Ist im fertigen Programm alles enthalten? Schreibt einen Bericht, Rückgabe 0 = in Ordnung."""
    _log_to("selftest.log")
    root = bundle_dir()
    sys.path.insert(0, str(root))
    os.chdir(data_dir())
    lines, ok = [], True

    def check(name, action):
        nonlocal ok
        try:
            action()
            lines.append(f"ok      {name}")
        except Exception as error:                          # alles melden, nicht beim ersten Fehler aufhören
            ok = False
            lines.append(f"FEHLER  {name}: {error!r}")

    for path in ("app.py", "icon.ico", "assets/icon.svg", "assets/style.css", ".streamlit/config.toml",
                 "modules/viewer_webgpu/frontend/index.html", "modules/viewer_webgpu/frontend/viewer.js"):
        check(path, lambda p=path: (root / p).stat())
    for module in ("streamlit", "streamlit_folium", "folium", "geopandas", "pyproj", "shapely", "scipy", "osmnx",
                   "meteostat", "pydeck", "plotly", "trimesh", "ezdxf", "PIL", "requests", "tkinter"):
        check(module, lambda m=module: __import__(m))
    for page in ("setup", "overview", "climate", "model3d", "flood", "rain", "wind", "earthquake", "tornado",
                 "kaiju", "alien", "literature", "navigation"):
        check(f"views.{page}", lambda p=page: __import__(f"views.{p}"))
    check("Streamlit-Oberfläche", lambda: (Path(__import__("streamlit").__file__).parent / "static"
                                           / "index.html").stat())
    check("Koordinaten (pyproj)", lambda: __import__("pyproj").Transformer.from_crs("EPSG:4326", "EPSG:25832"))
    check("Quellen und Rechenwege", lambda: __import__("modules.methods", fromlist=["check"]).check() == [] or 1 / 0)
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    main()
