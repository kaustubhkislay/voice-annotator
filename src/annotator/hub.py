import json
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

COMPANION = Path(__file__).resolve().parents[2] / "companion" / "index.html"
JOURNAL = Path.home() / ".voice-annotator" / "utterances.jsonl"


class Utterance(BaseModel):
    text: str


def _journal(entry: dict) -> None:
    # Crash-safe debugging trail: every utterance and its outcome, one JSON
    # line each. Best-effort — journaling must never break the request.
    try:
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with JOURNAL.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def create_app(session, on_summon=None) -> FastAPI:
    app = FastAPI()

    @app.post("/summon")
    def summon():
        # Pull the companion window to the current workspace/position.
        # Bound to a hotkey in the user's window manager (see README) so no
        # Accessibility permission is needed for the in-process hotkey.
        if on_summon is not None:
            on_summon()
        return {"ok": True}

    @app.post("/utterance")
    def utterance(u: Utterance):
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        try:
            events = session.handle(u.text)
        except Exception as e:
            _journal({"ts": ts, "text": u.text, "crash": repr(e)})
            raise
        _journal({"ts": ts, "text": u.text, "events": events})
        return {"events": events}

    @app.get("/", response_class=HTMLResponse)
    def index():
        if COMPANION.exists():
            return COMPANION.read_text()
        return "<h1>companion missing</h1>"

    return app
