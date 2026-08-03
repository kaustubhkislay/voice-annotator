from pathlib import Path
from annotator.session import Session
from annotator.vault import VaultWriter
from annotator.zotero import ZoteroError

DOC = ("AI control aims to maintain safety even if models scheme. "
       "Control evaluations measure this with red teams.")

class FakeZotero:
    def __init__(self):
        self.highlights, self.deleted, self.comments = [], [], []
    def current_item(self):
        return {"key": "K1", "title": "AI Control", "url": "u", "year": "2024", "firstCreator": "Greenblatt"}
    def fulltext(self, key):
        return DOC
    def create_highlight(self, text, comment="", key=None):
        self.highlights.append(text); self.last_key = key; return f"ANN{len(self.highlights)}"
    def delete_annotation(self, key):
        self.deleted.append(key)
    def add_comment(self, key, comment):
        self.comments.append((key, comment))

class FlakyCommentZotero(FakeZotero):
    """add_comment() always raises."""
    def add_comment(self, key, comment):
        raise ZoteroError("comment write failed")

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
    def create_highlight(self, text, comment="", key=None):
        self.create_calls += 1
        if self.create_calls == 1:
            raise ZoteroError("write failed")
        return super().create_highlight(text, comment, key)

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
    # A matched-but-failed-write utterance replaces last_failed with the new
    # transcript, so "retry" redoes the write, not the earlier bad match.
    assert s.last_failed == "Control evaluations measure this with red teams"
    ev3 = s.handle("retry")  # must not crash
    assert isinstance(ev3, list)

def test_write_failure_preserves_utterance_for_retry(tmp_path):
    z = FlakyCreateZotero()
    s = Session(z, VaultWriter(tmp_path), FakeLLM())
    ev1 = s.handle("Control evaluations measure this with red teams")  # matches, write fails
    assert ev1[0]["type"] == "error"
    assert s.last_failed == "Control evaluations measure this with red teams"
    ev2 = s.handle("retry")  # no re-dictation needed
    assert ev2[0]["type"] == "status"
    assert len(z.highlights) == 1
    assert z.last_key == "K1"

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

def test_end_quiz_as_first_utterance_no_crash(tmp_path):
    s, z, d = make(tmp_path)
    ev = s.handle("end quiz")
    assert ev[0]["type"] == "error" and ev[0]["text"] == "not in a quiz"
    assert list(d.glob("*.md")) == []  # no note was ever started

DUP_DOC = ("The Economics of Recursive Self-Improvement. "
           "AI control aims to maintain safety even if models scheme. "
           "We model the economics of recursive self-improvement using three assumptions. "
           "Deference is a separate axis entirely.")

class DupZotero(FakeZotero):
    def current_item(self):
        return {"key": "K1", "title": "The Economics of Recursive Self-Improvement",
                "url": "u", "year": "2024", "firstCreator": "Greenblatt"}
    def fulltext(self, key):
        return DUP_DOC

def test_cursor_and_title_avoid_duplicate_title_highlight(tmp_path):
    z = DupZotero()
    s = Session(z, VaultWriter(tmp_path), FakeLLM())
    # First, highlight a mid-document sentence to advance the cursor.
    s.handle("AI control aims to maintain safety even if models scheme")
    assert len(z.highlights) == 1
    # Now dictate the ambiguous phrase which is similar to both the title
    # and the later body sentence; the body sentence must win, not the title.
    ev = s.handle("we model this the economics of recursive self-improvement")
    assert ev[0]["type"] == "status"
    assert len(z.highlights) == 2
    assert "We model the economics" in z.highlights[-1]

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

def test_note_after_highlight_mirrors_to_zotero_comment_via_pending(tmp_path):
    s, z, d = make(tmp_path)
    s.handle("Control evaluations measure this with red teams")
    s.handle("note")
    s.handle("this is my reaction")
    assert z.comments == [("ANN1", "this is my reaction")]

def test_direct_note_after_highlight_mirrors_to_zotero_comment(tmp_path):
    s, z, d = make(tmp_path)
    s.handle("Control evaluations measure this with red teams")
    s.handle("note this is my reaction")
    assert z.comments == [("ANN1", "this is my reaction")]

def test_note_with_no_prior_highlight_records_no_comment(tmp_path):
    s, z, d = make(tmp_path)
    ev = s.handle("note this is my first thought")
    assert ev[0]["type"] == "status"
    assert z.comments == []
    assert "- note: this is my first thought" in note_text(d)

def test_comment_failure_still_reports_note_attached(tmp_path):
    z = FlakyCommentZotero()
    s = Session(z, VaultWriter(tmp_path), FakeLLM())
    s.handle("Control evaluations measure this with red teams")
    ev = s.handle("note this is my reaction")
    assert any(e["type"] == "status" and e["text"] == "note attached ✓" for e in ev)
    assert any(e["type"] == "error" and "Zotero comment failed" in e["text"] for e in ev)
    assert "- note: this is my reaction" in note_text(tmp_path)

def test_ask_mirrors_qa_to_zotero_comment_when_last_annotation_exists(tmp_path):
    s, z, d = make(tmp_path)
    s.handle("Control evaluations measure this with red teams")
    s.handle("ask what is a red team")
    assert z.comments == [("ANN1", "Q: what is a red team\nA: llm answer")]

def test_ask_records_no_comment_when_no_prior_highlight(tmp_path):
    s, z, d = make(tmp_path)
    ev = s.handle("ask what is a red team")
    assert ev[0]["type"] == "chat"
    assert z.comments == []

# --- Length-aware match threshold ------------------------------------------
#
# Live report: "no matter what I say is matching with the text" — a short or
# generic utterance reliably finds SOME window scoring above a flat
# threshold in a long document. Word-count bands raise the bar for short
# utterances instead of relying on find_passage (a pure scorer) to know
# about reliability. Base threshold is 75 (lowered from an earlier 80: live
# numbers showed a partial-read body sentence landing at ~78-79 and generic
# chatter at ~48, so 75 passes real partial reads with a large margin over
# noise). The 4-6-word band keeps its own higher floor regardless.

def test_utterance_under_four_words_with_no_exact_match_rejected(tmp_path):
    s, z, d = make(tmp_path)
    ev = s.handle("red teams here")  # 3 words, not a verbatim quote of anything in DOC
    assert ev[0]["type"] == "error"
    assert ev[0]["text"] == "no exact match for short phrase — read a longer span"
    assert z.highlights == []
    assert s.last_failed is None  # nothing stored to retry

# --- Short exact-match highlighting -----------------------------------------
#
# Live UX finding (utterance journal): users legitimately highlight short
# passages ("Other definitions."). A flat <4-word rejection blocked all of
# them, forcing bad workarounds. Short utterances now get an exact
# (normalized-substring) match attempt via matcher.find_exact before any
# rejection; a hit highlights the whole containing sentence.

def test_short_verbatim_phrase_highlights_containing_sentence(tmp_path):
    s, z, d = make(tmp_path)
    ev = s.handle("red teams")  # 2 words, verbatim substring of the 2nd sentence
    assert ev[0]["type"] == "status"
    assert z.highlights == ["Control evaluations measure this with red teams."]

def test_short_verbatim_phrase_appearing_twice_uses_cursor(tmp_path):
    doc = ("Other definitions apply in the introduction. "
           "AI control aims to maintain safety even if models scheme. "
           "Other definitions apply in the appendix as well.")
    z = FakeZotero()
    z.fulltext = lambda key: doc
    s = Session(z, VaultWriter(tmp_path), FakeLLM())
    s.handle("AI control aims to maintain safety even if models scheme")  # advances cursor
    ev = s.handle("other definitions")  # 2 words, present at both start and end
    assert ev[0]["type"] == "status"
    assert z.highlights[-1] == "Other definitions apply in the appendix as well."

def test_short_phrase_absent_rejected_with_no_highlight(tmp_path):
    s, z, d = make(tmp_path)
    ev = s.handle("purple giraffes")  # 2 words, not present anywhere in DOC
    assert ev[0]["type"] == "error"
    assert ev[0]["text"] == "no exact match for short phrase — read a longer span"
    assert z.highlights == []

def test_five_word_exact_phrase_matches_despite_low_fuzzy_score(tmp_path):
    s, z, d = make(tmp_path)
    # 5 words, verbatim tail of sentence 1; fuzzy alone scores ~83.3, below
    # the mid-band's 88 floor, but the exact-match-first check catches it.
    ev = s.handle("safety even if models scheme")
    assert ev[0]["type"] == "status"
    assert z.highlights == ["AI control aims to maintain safety even if models scheme."]

def test_five_word_utterance_needs_88_not_75(tmp_path):
    s, z, d = make(tmp_path)
    # 5 words, scores ~86 against "Control evaluations measure this with red
    # teams." — clears the base 75 threshold but not the 88 mid-band floor.
    ev = s.handle("control evaluation measures this teams")
    assert ev[0]["type"] == "error"
    assert z.highlights == []

def test_seven_word_utterance_keeps_normal_threshold(tmp_path):
    s, z, d = make(tmp_path)
    # 7 words, scores ~84.5 against the same sentence — below the 88 mid-band
    # floor but still clears the unchanged base threshold for 7+ words.
    ev = s.handle("control evaluation measures thing with blue teams")
    assert ev[0]["type"] == "status"
    assert z.highlights and "red teams" in z.highlights[0]

def test_seven_plus_word_utterance_passes_at_75_but_would_fail_at_80(tmp_path):
    s, z, d = make(tmp_path)
    # 9 words, scores ~77 against "Control evaluations measure this with red
    # teams." — below the old flat 80 threshold, but clears the new base 75.
    ev = s.handle("control evaluation reviews this with blue team here today")
    assert ev[0]["type"] == "status"
    assert z.highlights and "red teams" in z.highlights[0]

def test_retry_after_mid_band_rejection_relaxes_that_bands_threshold(tmp_path):
    s, z, d = make(tmp_path)
    ev1 = s.handle("control evaluation measures this teams")  # 5 words, ~86, needs 88
    assert ev1[0]["type"] == "error"
    assert s.last_failed == "control evaluation measures this teams"
    # retry relaxes the 5-word band's 88 floor by 15 -> 73, which the ~86
    # score clears, not the base threshold - 15 (= 60).
    ev2 = s.handle("retry")
    assert ev2[0]["type"] == "status"
    assert z.highlights and "red teams" in z.highlights[0]
