from pathlib import Path
from annotator.session import Session
from annotator.vault import VaultWriter
from annotator.zotero import ZoteroError

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

class FlakyFulltextZotero(FakeZotero):
    """fulltext() raises once, then succeeds — simulates a transient failure."""
    def __init__(self):
        super().__init__()
        self.fulltext_calls = 0
    def fulltext(self, key):
        self.fulltext_calls += 1
        if self.fulltext_calls == 1:
            raise ZoteroError("temporary outage")
        return super().fulltext(key)

class FlakyCreateZotero(FakeZotero):
    """create_highlight() raises once, then succeeds."""
    def __init__(self):
        super().__init__()
        self.create_calls = 0
    def create_highlight(self, text, comment=""):
        self.create_calls += 1
        if self.create_calls == 1:
            raise ZoteroError("write failed")
        return super().create_highlight(text, comment)

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

def test_note_as_first_utterance_no_crash(tmp_path):
    s, z, d = make(tmp_path)
    ev = s.handle("note this is my first thought")
    assert isinstance(ev, list) and ev[0]["type"] == "status"
    assert "- note: this is my first thought" in note_text(d)

def test_note_pending_first_then_text_no_crash(tmp_path):
    s, z, d = make(tmp_path)
    s.handle("note")
    ev = s.handle("this is my reaction")
    assert isinstance(ev, list) and ev[0]["type"] == "status"
    assert "- note: this is my reaction" in note_text(d)

def test_ensure_started_retries_after_fulltext_failure(tmp_path):
    z = FlakyFulltextZotero()
    s = Session(z, VaultWriter(tmp_path), FakeLLM())
    ev1 = s.handle("Control evaluations measure this with red teams")
    assert ev1[0]["type"] == "error"
    assert s.item is None  # partial lazy-start must not stick
    ev2 = s.handle("Control evaluations measure this with red teams")
    assert ev2[0]["type"] == "status"
    assert z.highlights

def test_retry_survives_create_highlight_failure(tmp_path):
    z = FlakyCreateZotero()
    s = Session(z, VaultWriter(tmp_path), FakeLLM())
    ev1 = s.handle("totally unrelated pasta recipe words here")
    assert ev1[0]["type"] == "error"
    failed_before = s.last_failed
    assert failed_before is not None
    ev2 = s.handle("Control evaluations measure this with red teams")  # matches, but write fails
    assert ev2[0]["type"] == "error"
    assert s.last_failed == failed_before  # state unchanged on caught error
    ev3 = s.handle("retry")  # must not crash
    assert isinstance(ev3, list)

def test_quiz_mode_treats_undo_as_answer(tmp_path):
    s, z, d = make(tmp_path)
    s.handle("Control evaluations measure this with red teams")
    s.handle("finished")
    ev = s.handle("undo")
    assert ev[0]["type"] == "chat"
    assert z.deleted == []  # not treated as a real undo while in quiz mode

def test_direct_note_clears_pending_flag(tmp_path):
    s, z, d = make(tmp_path)
    s.handle("Control evaluations measure this with red teams")
    s.handle("note")
    assert s.pending_note is True
    s.handle("note explicit text")
    assert s.pending_note is False

def test_pending_note_survives_ensure_started_failure(tmp_path):
    z = FlakyFulltextZotero()
    s = Session(z, VaultWriter(tmp_path), FakeLLM())
    s.handle("note")
    assert s.pending_note is True
    ev1 = s.handle("this is my reaction")  # _ensure_started's fulltext() raises
    assert ev1[0]["type"] == "error"
    assert s.pending_note is True  # state unchanged on caught error
    ev2 = s.handle("this is my reaction")  # retry succeeds this time
    assert ev2[0]["type"] == "status"
    assert s.pending_note is False
    assert "- note: this is my reaction" in note_text(tmp_path)
