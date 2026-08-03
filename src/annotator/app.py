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


def _pin_above_fullscreen(*_args):
    # macOS: turn the window into a true overlay panel — status level so it
    # sits above fullscreen apps, joins every Space (incl. native-fullscreen
    # Spaces), and is stationary so tiling window managers leave it alone.
    # Then re-assert the top-right frame: a tiling WM (e.g. AeroSpace) may
    # have repositioned the window before these flags took effect. Runs on
    # the Cocoa main thread. No-op on other platforms.
    try:
        import AppKit
        from PyObjCTools import AppHelper

        def apply():
            can_join_all_spaces = 1 << 0
            stationary = 1 << 4
            fullscreen_auxiliary = 1 << 8
            vf = AppKit.NSScreen.mainScreen().visibleFrame()
            x = vf.origin.x + vf.size.width - WIDTH - MARGIN
            y = vf.origin.y + vf.size.height - HEIGHT - MARGIN
            for ns in AppKit.NSApplication.sharedApplication().windows():
                ns.setLevel_(AppKit.NSStatusWindowLevel)
                ns.setCollectionBehavior_(
                    ns.collectionBehavior()
                    | can_join_all_spaces
                    | stationary
                    | fullscreen_auxiliary
                )
                ns.setFrame_display_(AppKit.NSMakeRect(x, y, WIDTH, HEIGHT), True)
                ns.orderFrontRegardless()

        AppHelper.callAfter(apply)
    except Exception:
        pass


def main():
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("Set OPENROUTER_API_KEY first.")
    session = Session(ZoteroClient(), VaultWriter(READINGS), LLMClient(api_key))
    summon_ref = {"fn": None}
    app = create_app(session, on_summon=lambda: summon_ref["fn"] and summon_ref["fn"]())
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
    window.events.shown += _pin_above_fullscreen
    def summon():
        window.show()
        _pin_above_fullscreen()

    summon_ref["fn"] = summon
    hotkey = keyboard.GlobalHotKeys({"<cmd>+<shift>+<space>": summon})
    hotkey.start()
    webview.start()

if __name__ == "__main__":
    main()
