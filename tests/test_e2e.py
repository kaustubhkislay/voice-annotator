from fastapi.testclient import TestClient
from annotator.hub import create_app
from annotator.session import Session
from annotator.vault import VaultWriter
from tests.test_session import FakeZotero, FakeLLM, DOC

def test_full_reading_session(tmp_path):
    session = Session(FakeZotero(), VaultWriter(tmp_path), FakeLLM())
    c = TestClient(create_app(session))
    def say(t):
        return c.post("/utterance", json={"text": t}).json()["events"]
    assert say("Control evaluations measure this with red teams")[0]["type"] == "status"
    say("note key method of the paper")
    say("ask what is a red team")
    assert any(e["type"] == "chat" for e in say("finished"))
    say("a red team attacks the protocol")
    say("end quiz")
    t = next(tmp_path.glob("*.md")).read_text()
    for needle in ['- "Control evaluations', "- note: key method", "- q: what is a red team",
                   "## Consolidation", "## Quiz", "status: consolidated"]:
        assert needle in t
