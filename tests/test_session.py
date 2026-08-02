from pathlib import Path
from annotator.session import Session
from annotator.vault import VaultWriter

DOC = ("AI control aims to maintain safety even if models scheme. "
       "Control evaluations measure this with red teams.")

class FakeZotero:
    def __init__(self):
        self.highlights, self.deleted = [], []
    def current_item(self):
        return {"key": "K1", "title": "AI Control", "url": "u", "year": "2024", "firstCreator": "Greenblatt"}
    def fulltext(self, key):
        return DOC
    def create_highlight(self, text, comment=""):
        self.highlights.append(text); return f"ANN{len(self.highlights)}"
    def delete_annotation(self, key):
        self.deleted.append(key)

class FakeLLM:
    def ask(self, question, article_text, note_md, focus): return "llm answer"
    def consolidate(self, note_md, article_text): return "consolidated md"
    def quiz_turn(self, history, note_md): return f"quiz msg {len(history)}"

def make(tmp_path):
    z = FakeZotero()
    s = Session(z, VaultWriter(tmp_path), FakeLLM())
    return s, z, tmp_path

def note_text(tmp_path):
    return next(tmp_path.glob("*.md")).read_text()

def test_highlight_flow(tmp_path):
    s, z, d = make(tmp_path)
    ev = s.handle("Control evaluations measure this with red teams")
    assert ev[0]["type"] == "status" and z.highlights and "red teams" in note_text(d)

def test_note_pending_then_text(tmp_path):
    s, z, d = make(tmp_path)
    s.handle("Control evaluations measure this with red teams")
    s.handle("note")
    s.handle("this is my reaction")
    assert "- note: this is my reaction" in note_text(d)
    assert len(z.highlights) == 1  # reaction was NOT highlighted

def test_bad_match_then_retry(tmp_path):
    s, z, d = make(tmp_path)
    s.handle("Control evaluations measure this with red teams")  # start session
    ev = s.handle("totally unrelated pasta recipe words here")
    assert ev[0]["type"] == "error" and len(z.highlights) == 1
    s.handle("retry")  # looser threshold; may still fail, but must not crash

def test_ask_logs_q_and_a(tmp_path):
    s, z, d = make(tmp_path)
    s.handle("Control evaluations measure this with red teams")
    ev = s.handle("ask what is a red team")
    assert ev[0]["type"] == "chat" and ev[0]["text"] == "llm answer"
    assert "- q: what is a red team" in note_text(d) and "- a: llm answer" in note_text(d)

def test_undo(tmp_path):
    s, z, d = make(tmp_path)
    s.handle("Control evaluations measure this with red teams")
    s.handle("undo")
    assert z.deleted == ["ANN1"] and '- "' not in note_text(d)

def test_finished_and_quiz(tmp_path):
    s, z, d = make(tmp_path)
    s.handle("Control evaluations measure this with red teams")
    ev = s.handle("finished")
    assert any(e["type"] == "chat" for e in ev) and "## Consolidation" in note_text(d)
    s.handle("my quiz answer")
    ev = s.handle("end quiz")
    t = note_text(d)
    assert "## Quiz" in t and "status: consolidated" in t and "my quiz answer" in t
