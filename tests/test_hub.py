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
