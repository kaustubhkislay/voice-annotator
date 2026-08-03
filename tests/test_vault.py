from pathlib import Path
from annotator.vault import VaultWriter

META = {"zotero_key": "ABCD1234", "url": "https://arxiv.org/abs/1", "read": "2026-08-02"}

def make(tmp_path) -> tuple[VaultWriter, Path]:
    w = VaultWriter(tmp_path)
    p = w.start("Greenblatt 2024 - AI Control", META)
    return w, p

def test_start_creates_frontmatter(tmp_path):
    _, p = make(tmp_path)
    t = p.read_text()
    assert t.startswith("---\n") and "status: reading" in t and "zotero_key: ABCD1234" in t

def test_highlight_and_nested_annotations(tmp_path):
    w, p = make(tmp_path)
    w.add_highlight("first passage")
    w.add_annotation("note", "my reaction")
    w.add_annotation("q", "what is X")
    w.add_annotation("a", "X is Y")
    w.add_highlight("second passage")
    t = p.read_text()
    assert '- "first passage"\n\t- note: my reaction\n\t- q: what is X\n\t- a: X is Y\n- "second passage"\n' in t

def test_undo_removes_block(tmp_path):
    w, p = make(tmp_path)
    w.add_highlight("keep me")
    w.add_highlight("drop me")
    w.add_annotation("note", "attached to drop")
    w.undo_last_highlight()
    t = p.read_text()
    assert "drop me" not in t and "attached to drop" not in t and "keep me" in t

def test_section_and_status(tmp_path):
    w, p = make(tmp_path)
    w.add_section("Consolidation", "summary here")
    w.set_status("consolidated")
    t = p.read_text()
    assert "## Consolidation\n\nsummary here" in t and "status: consolidated" in t

def test_undo_on_empty_note_is_noop(tmp_path):
    w, p = make(tmp_path)
    original = p.read_text()
    w.undo_last_highlight()
    assert p.read_text() == original

def test_undo_twice_after_one_highlight(tmp_path):
    w, p = make(tmp_path)
    w.add_highlight("only one")
    w.undo_last_highlight()
    state_after_first_undo = p.read_text()
    w.undo_last_highlight()
    state_after_second_undo = p.read_text()
    assert state_after_first_undo == state_after_second_undo and "only one" not in state_after_second_undo
