"""Bildschirmfotos für die README (docs/bilder/) – steuert Microsoft Edge ohne Fenster.

Keine Zusatzpakete: Edge wird über das Chrome DevTools Protocol gesteuert, die
WebSocket-Verbindung übernimmt ``websockets`` (kommt mit Streamlit mit).

Vorher TERRA-Sim starten, dann das Skript auf diese Adresse richten::

    streamlit run app.py --server.port 8502
    python scripts/screenshots.py --url http://localhost:8502

Ablauf: Auf „Projekt anlegen“ werden die Koordinaten der Oldenburger Innenstadt eingetippt
(Bild der Karte), dann lädt das Skript ``docs/bilder/beispielprojekt.terrasim.json`` – das
Gebiet mit gut sichtbaren Szenarien – und fotografiert jede Seite: ganze Seite plus die
3D-Ansicht einzeln, dazu Ausschnitte (Wahrscheinlichkeit, Methode & Quellen, Rangliste).
Zum Schluss die Live-Demo (Desktop und Smartphone) und das Vorschaubild für den Kopf der
README. Alles landet als WebP in ``docs/bilder/``.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "bilder"
PROJECT = OUT / "beispielprojekt.terrasim.json"
DEMO_URL = "https://jade-hs-vibecoding-wpk.github.io/TERRA-Sim/"
WIDTH, HEIGHT, SCALE = 1440, 900, 1.5
LAT, LON = "53.14000", "8.21400"          # Oldenburg Innenstadt (wie in der Projektdatei)

# Seite (Link in der Seitenleiste), Dateiname, Überschrift im Kopf, hat 3D-Ansicht
PAGES = [
    ("uebersicht", "uebersicht", "Übersicht", False),
    ("klima", "klima", "Klima am Standort", False),
    ("modell", "modell", "3D-Modell & Export", True),
    ("hochwasser", "hochwasser", "Hochwasser", True),
    ("starkregen", "starkregen", "Starkregen", True),
    ("starkwind", "starkwind", "Starkwind", True),
    ("erdbeben", "erdbeben", "Erdbeben", True),
    ("tornado", "tornado", "Tornado", True),
    ("kaiju", "kaiju", "Kaiju-Angriff", True),
    ("aliens", "aliens", "Alien-Invasion", True),
    ("quellen", "quellen", "Methoden & Quellen", False),
]

IDLE = ("(document.querySelector('.stApp')?.dataset.testScriptState !== 'running')"
        " && !document.querySelector('[data-testid=\"stSpinner\"]')")
VIEWER_READY = """(() => {
  const f = document.querySelector('iframe[title*="terra_viewer"]');
  const d = f && f.contentDocument;
  const badge = d && d.getElementById('badge'), msg = d && d.getElementById('msg');
  return !!(badge && badge.textContent.length && msg && msg.style.display === 'none');
})()"""


def find_edge() -> str:
    for env in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        base = os.environ.get(env)
        for path in ((Path(base) / "Microsoft/Edge/Application/msedge.exe",
                      Path(base) / "Google/Chrome/Application/chrome.exe") if base else ()):
            if path.exists():
                return str(path)
    for name in ("msedge", "microsoft-edge", "google-chrome", "chromium"):
        if shutil.which(name):
            return shutil.which(name)
    raise SystemExit("Weder Edge noch Chrome gefunden.")


class Browser:
    """Ein Tab in Edge ohne Fenster, gesteuert über das DevTools-Protokoll."""

    async def __aenter__(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        self.profile = tempfile.mkdtemp(prefix="terra-bilder-")
        self.proc = subprocess.Popen(
            [find_edge(), "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={self.profile}",
             "--no-first-run", "--no-default-browser-check", "--hide-scrollbars", "--mute-audio",
             "--enable-unsafe-webgpu", "--ignore-gpu-blocklist", f"--window-size={WIDTH},{HEIGHT}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1) as response:
                    targets = json.load(response)
                break
            except OSError:
                await asyncio.sleep(0.2)
        page = next(t for t in targets if t["type"] == "page")
        self.ws = await connect(page["webSocketDebuggerUrl"], max_size=None)
        self.counter = 0
        await self.send("Page.enable")
        await self.viewport(WIDTH, HEIGHT)
        return self

    async def __aexit__(self, *_):
        await self.ws.close()
        self.proc.terminate()
        self.proc.wait(timeout=10)
        shutil.rmtree(self.profile, ignore_errors=True)

    async def send(self, method: str, **params):
        self.counter += 1
        await self.ws.send(json.dumps({"id": self.counter, "method": method, "params": params}))
        while True:
            message = json.loads(await self.ws.recv())
            if message.get("id") == self.counter:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return message.get("result", {})

    async def js(self, expression: str, by_value: bool = True):
        result = await self.send("Runtime.evaluate", expression=expression, awaitPromise=True,
                                 returnByValue=by_value)
        if "exceptionDetails" in result:
            raise RuntimeError(result["exceptionDetails"].get("exception", {}).get("description", "JS-Fehler"))
        return result["result"].get("value") if by_value else result["result"]

    async def wait(self, condition: str, what: str, timeout: float = 90):
        start = time.time()
        while time.time() - start < timeout:
            try:
                if await self.js(condition):
                    return
            except RuntimeError:
                pass
            await asyncio.sleep(0.5)
        raise TimeoutError(f"Zeitüberschreitung beim Warten auf: {what}")

    async def viewport(self, width: int, height: int, scale: float = SCALE, mobile: bool = False):
        await self.send("Emulation.setDeviceMetricsOverride", width=width, height=int(height),
                        deviceScaleFactor=scale, mobile=mobile)

    async def click(self, js_element: str, what: str):
        await self.wait(f"!!({js_element})", what)
        await self.js(f"({js_element}).click()")

    async def type_into(self, selector: str, text: str):
        await self.js(f"document.querySelector({json.dumps(selector)}).focus()")
        await self.send("Input.dispatchKeyEvent", type="keyDown", key="a", code="KeyA", modifiers=2,
                        windowsVirtualKeyCode=65)
        await self.send("Input.dispatchKeyEvent", type="keyUp", key="a", code="KeyA", modifiers=2,
                        windowsVirtualKeyCode=65)
        await self.send("Input.insertText", text=text)

    async def rect(self, js_element: str) -> dict:
        return await self.js(f"(() => {{ const r = ({js_element}).getBoundingClientRect();"
                             " return {x: r.x, y: r.y + window.scrollY, width: r.width, height: r.height}; })()")

    async def shot(self, name: str, clip: dict | None = None, quality: int = 86) -> bytes:
        params = {"format": "webp", "quality": quality}
        if clip:
            params["clip"] = {**clip, "scale": 1}
        data = base64.b64decode((await self.send("Page.captureScreenshot", **params))["data"])
        path = OUT / f"{name}.webp"
        path.write_bytes(data)
        print(f"  {path.name:28s} {len(data) // 1024:5d} KB")
        return data


def button(text: str) -> str:
    return f"[...document.querySelectorAll('button')].find(b => b.innerText.includes({json.dumps(text)}))"


def card_with(text: str) -> str:
    return f"[...document.querySelectorAll('[class*=\"st-key-card-\"]')].find(c => c.innerText.includes({json.dumps(text)}))"


CONTENT_HEIGHT = ("Math.ceil(document.querySelector('[data-testid=\"stMainBlockContainer\"]')"
                  ".getBoundingClientRect().bottom + 24)")
VIEWER = "document.querySelector('iframe[title*=\"terra_viewer\"]')"


async def full_page(b: Browser, name: str, max_height: int = 6000):
    """Ganze Seite: Fenster so hoch machen wie der Inhalt (höchstens ``max_height``), fotografieren."""
    await b.viewport(WIDTH, max(HEIGHT, min(await b.js(CONTENT_HEIGHT), max_height)))
    await asyncio.sleep(2.5)
    await b.shot(name)


async def reset_camera(b: Browser):
    """Knopf „Ansicht“: Die Kamera bleibt beim Seitenwechsel stehen – für jedes Bild neu ausrichten."""
    await b.js(f"{VIEWER}.contentDocument.getElementById('btn-reset').click()")
    await asyncio.sleep(1.5)


async def close_up_3d(b: Browser, name: str, width: int = 1920, closer: float = 0.48):
    """3D-Ansicht einzeln: breiteres Fenster, Kamera näher an das Modell, nur die Ansicht fotografieren."""
    await b.viewport(width, HEIGHT)
    await b.viewport(width, max(HEIGHT, await b.js(CONTENT_HEIGHT)))
    await asyncio.sleep(2.5)                                # Ansicht passt sich der neuen Größe an
    await reset_camera(b)
    await b.js(f"""(() => {{
      const t = {VIEWER}.contentWindow.terra;
      t.camera.position.sub(t.controls.target).multiplyScalar({closer}).add(t.controls.target);
      t.controls.update(); t.invalidate(10);
    }})()""")
    await asyncio.sleep(3)
    await b.shot(f"3d-{name}", await b.rect(VIEWER))


async def capture_app(b: Browser, url: str):
    print("Projekt anlegen …")
    await b.send("Page.navigate", url=url)
    await b.wait(f"!!({button('Projekt anlegen & Daten laden')})", "Startseite")
    await b.click("[...document.querySelectorAll('[role=\"tab\"]')].find(t => t.innerText.trim() === 'Koordinaten')",
                  "Reiter Koordinaten")
    await b.type_into('input[aria-label="Breite (°N)"]', LAT)
    await b.type_into('input[aria-label="Länge (°E)"]', LON)
    await b.click(button("Übernehmen"), "Übernehmen")
    await b.wait("document.body.innerText.includes('53.14000° N')", "Gebiet Oldenburg")
    await b.wait(IDLE, "App bereit")
    await b.type_into('input[aria-label="Projektname"]', "Oldenburg Innenstadt")
    await asyncio.sleep(6)                                  # Kartenkacheln laden
    await b.shot("projekt-anlegen")

    # Beispielprojekt mit den Szenarien für die Bilder öffnen
    await b.click("[...document.querySelectorAll('[role=\"tab\"]')].find(t => t.innerText.trim() === 'Projektdatei')",
                  "Reiter Projektdatei")
    upload = await b.js("document.querySelector('input[type=\"file\"]')", by_value=False)
    await b.send("DOM.setFileInputFiles", files=[str(PROJECT)], objectId=upload["objectId"])
    await b.click(button("Projekt öffnen"), "Projekt öffnen")
    await b.wait("location.pathname.endsWith('/uebersicht')", "Projekt geladen", timeout=300)

    for href, name, title, has_3d in PAGES:
        print(title)
        if not await b.js("location.pathname.endsWith('/' + %s)" % json.dumps(href)):
            await b.click(f"document.querySelector('a[href=\"{href}\"]')", f"Link {href}")
        await b.wait(f"document.querySelector('.terra-hero h1')?.innerText.trim() === {json.dumps(title)}",
                     f"Seite {title}", timeout=180)
        await b.wait(IDLE, f"{title} fertig gerechnet", timeout=180)
        if has_3d:
            await b.wait(VIEWER_READY, f"3D-Ansicht {title}", timeout=120)
            await reset_camera(b)
            await asyncio.sleep(5)                          # Menschen, Teilchen, Monster in Bewegung
        else:
            await asyncio.sleep(2)

        if name == "erdbeben":                              # Rechenweg aufklappen
            await b.click("[...document.querySelectorAll('[data-testid=\"stExpander\"] summary')]"
                          ".find(s => s.innerText.includes('Methode & Quellen'))", "Methode & Quellen")
            await asyncio.sleep(2)
        if name == "quellen":                               # Reiter Erdbeben mit Formeln zeigen
            await b.click("[...document.querySelectorAll('[role=\"tab\"]')].find(t => t.innerText.includes('Erdbeben'))",
                          "Reiter Erdbeben")
            await asyncio.sleep(1.5)

        await full_page(b, name, max_height=2600 if name == "quellen" else 6000)
        if name in ("hochwasser", "starkregen", "starkwind", "erdbeben", "tornado", "kaiju", "aliens"):
            await b.shot(f"wahrscheinlichkeit-{name}", await b.rect("document.querySelector('[class*=\"st-key-band-\"]')"))
        if name == "erdbeben":
            await b.shot("methode", await b.rect("[...document.querySelectorAll('[data-testid=\"stExpander\"]')]"
                                                 ".find(e => e.innerText.includes('Methode & Quellen'))"))
        if name == "uebersicht":
            await b.shot("rangliste", await b.rect(card_with("Wie wahrscheinlich ist was?")))
        if has_3d:                                          # zuletzt, weil es die Kamera verstellt
            await close_up_3d(b, name, closer=0.6 if name in ("tornado", "aliens") else 0.48)
        await b.viewport(WIDTH, HEIGHT)


async def capture_demo(b: Browser):
    print("Live-Demo")
    await b.viewport(WIDTH, HEIGHT)
    await b.send("Page.navigate", url=DEMO_URL + "#starkwind")
    await b.wait("document.getElementById('page-title')?.innerText.includes('Starkwind')", "Demo geladen")
    await b.wait("(() => { const d = document.getElementById('viewer').contentDocument;"
                 " return d && d.getElementById('msg').style.display === 'none'; })()", "Demo-3D", timeout=120)
    await asyncio.sleep(5)
    await b.shot("demo")
    await b.viewport(390, 844, scale=2, mobile=True)
    await b.send("Page.reload")
    await b.wait("document.getElementById('page-title')?.innerText.includes('Starkwind')", "Demo mobil")
    await asyncio.sleep(4)
    await b.shot("demo-mobil")


def compose_preview():
    """Vorschaubild für den Kopf der README: drei Ansichten auf grünem Grund."""
    from PIL import Image, ImageDraw, ImageFilter

    def load(name, width, height):
        """Auf das Seitenverhältnis zuschneiden (zu breit: mittig, zu hoch: von oben), dann verkleinern."""
        img = Image.open(OUT / f"{name}.webp").convert("RGB")
        if img.width / img.height > width / height:
            w = int(img.height * width / height)
            img = img.crop(((img.width - w) // 2, 0, (img.width + w) // 2, img.height))
        else:
            img = img.crop((0, 0, img.width, int(img.width * height / width)))
        return img.resize((width, height), Image.LANCZOS)

    W, H, pad, gap = 2400, 1260, 60, 40
    canvas = Image.new("RGB", (W, H), "#e2f3e6")
    left_w = int((W - 2 * pad - gap) * 0.62)
    right_w = W - 2 * pad - gap - left_w
    right_h = (H - 2 * pad - gap) // 2
    panels = [(load("uebersicht", left_w, H - 2 * pad), (pad, pad)),
              (load("3d-starkwind", right_w, right_h), (pad + left_w + gap, pad)),
              (load("3d-tornado", right_w, right_h), (pad + left_w + gap, pad + right_h + gap))]
    for img, (x, y) in panels:
        shadow = Image.new("L", (W, H), 0)
        ImageDraw.Draw(shadow).rounded_rectangle([x + 6, y + 14, x + img.width + 6, y + img.height + 14], 28, fill=90)
        canvas.paste(Image.new("RGB", (W, H), "#10291d"), (0, 0), shadow.filter(ImageFilter.GaussianBlur(18)))
        mask = Image.new("L", img.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.width - 1, img.height - 1], 28, fill=255)
        canvas.paste(img, (x, y), mask)
    buffer = io.BytesIO()
    canvas.save(buffer, "WEBP", quality=88)
    (OUT / "vorschau.webp").write_bytes(buffer.getvalue())
    print(f"  vorschau.webp                {len(buffer.getvalue()) // 1024:5d} KB")


async def main(url: str, demo: bool):
    OUT.mkdir(parents=True, exist_ok=True)
    async with Browser() as b:
        await capture_app(b, url.rstrip("/") + "/")
        if demo:
            await capture_demo(b)
    compose_preview()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", default="http://localhost:8502", help="Adresse der laufenden App")
    parser.add_argument("--ohne-demo", action="store_true", help="Live-Demo nicht fotografieren")
    args = parser.parse_args()
    asyncio.run(main(args.url, not args.ohne_demo))
