import os, threading, time
from pathlib import Path
import httpx
import uvicorn, webview
from pynput import keyboard
from .hub import create_app
from .llm import LLMClient
from .session import Session
from .vault import VaultWriter
from .zotero import ZoteroClient

READINGS = Path(os.environ.get("VOICE_ANNOTATOR_VAULT_DIR", str(Path.home() / "obsidian-ais" / "readings")))
PORT = 8765
WIDTH, HEIGHT, MARGIN = 280, 360, 12


def _pin_above_fullscreen(window):
    # macOS: join all Spaces (incl. fullscreen ones) so the panel overlays
    # fullscreen apps instead of living on its own Space. No-op elsewhere.
    try:
        import AppKit

        for ns in AppKit.NSApplication.sharedApplication().windows():
            if ns.title() == "voice annotator":
                can_join_all_spaces, fullscreen_auxiliary = 1 << 0, 1 << 8
                ns.setCollectionBehavior_(
                    ns.collectionBehavior() | can_join_all_spaces | fullscreen_auxiliary
                )
    except Exception:
        pass


def main():
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("Set OPENROUTER_API_KEY first.")
    session = Session(ZoteroClient(), VaultWriter(READINGS), LLMClient(api_key))
    app = create_app(session)
    threading.Thread(target=lambda: uvicorn.run(app, port=PORT, log_level="warning"),
                     daemon=True).start()
    deadline = time.time() + 5.0
    while time.time() < deadline:
        try:
            httpx.get(f"http://localhost:{PORT}/", timeout=0.2)
            break
        except httpx.HTTPError:
            time.sleep(0.1)
    screen = webview.screens[0]
    window = webview.create_window("voice annotator", f"http://localhost:{PORT}",
                                   width=WIDTH, height=HEIGHT,
                                   x=screen.width - WIDTH - MARGIN, y=MARGIN,
                                   on_top=True)
    window.events.shown += lambda: _pin_above_fullscreen(window)
    hotkey = keyboard.GlobalHotKeys({"<ctrl>+<alt>+<space>": lambda: window.show()})
    hotkey.start()
    webview.start()

if __name__ == "__main__":
    main()
