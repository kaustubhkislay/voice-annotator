from fastapi.testclient import TestClient
from annotator.hub import create_app


class FakeSession:
    def handle(self, raw):
        return [{"type": "status", "text": f"got {raw}"}]


def test_utterance_roundtrip():
    c = TestClient(create_app(FakeSession()))
    r = c.post("/utterance", json={"text": "hello"})
    assert r.status_code == 200
    assert r.json()["events"][0]["text"] == "got hello"


def test_summon_invokes_callback():
    called = []
    c = TestClient(create_app(FakeSession(), on_summon=lambda: called.append(1)))
    assert c.post("/summon").json() == {"ok": True}
    assert called == [1]


def test_summon_without_callback_is_ok():
    c = TestClient(create_app(FakeSession()))
    assert c.post("/summon").status_code == 200
