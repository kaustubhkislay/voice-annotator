from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

COMPANION = Path(__file__).resolve().parents[2] / "companion" / "index.html"


class Utterance(BaseModel):
    text: str


def create_app(session) -> FastAPI:
    app = FastAPI()

    @app.post("/utterance")
    def utterance(u: Utterance):
        return {"events": session.handle(u.text)}

    @app.get("/", response_class=HTMLResponse)
    def index():
        if COMPANION.exists():
            return COMPANION.read_text()
        return "<h1>companion missing</h1>"

    return app
