# Voice Annotation Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Speak a passage aloud → it is highlighted in Zotero's reader → spoken notes/questions attach to it → everything lands in `~/obsidian-ais/readings/` → "finished" triggers consolidation + an interactive quiz.

**Architecture:** One FastAPI "hub" process owns all state. A `pywebview` always-on-top companion window (the Wispr Flow dictation target) posts utterances to the hub. A tiny Zotero plugin adds write endpoints to Zotero's local server (its stock local API is read-only). An OpenRouter client (DeepSeek-v4-flash) powers ask/consolidate/quiz.

**Tech Stack:** Python ≥3.12, uv, FastAPI, uvicorn, httpx, rapidfuzz, pywebview, pynput, pytest. Zotero plugin in plain JS (bootstrapped, Zotero 9).

## Global Constraints

- Repo: `~/voice-annotator`, uv-managed. Run everything with `uv run`.
- Vault target: `~/obsidian-ais/readings/` (symlink path). Never write elsewhere in the vault.
- Vault style: dash-bullets, tab indentation, spoken text preserved verbatim, no emojis.
- OpenRouter key from env var `OPENROUTER_API_KEY` only — never in files. Mint a fresh key (old one was scheduled for revocation).
- Model slug default `deepseek/deepseek-v4-flash`; Task 6 verifies the real slug against the live `/models` endpoint and corrects the default if needed.
- Zotero local server: `http://localhost:23119`. Read API = `/api/users/0/...`; our plugin endpoints live under `/voiceannotator/...`.
- All spoken-command words are matched only at utterance start, case-insensitive, trailing punctuation ignored.

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`, `src/annotator/__init__.py`, `tests/test_smoke.py`, `.gitignore`

**Interfaces:**
- Produces: importable package `annotator`; `uv run pytest` works.

- [ ] **Step 1: Scaffold with uv**

```bash
cd ~/voice-annotator
uv init --name annotator --package --python 3.12
rm -f src/annotator/py.typed main.py
uv add fastapi uvicorn httpx rapidfuzz pywebview pynput
uv add --dev pytest
```

- [ ] **Step 2: Write smoke test**

```python
# tests/test_smoke.py
def test_import():
    import annotator  # noqa: F401
```

- [ ] **Step 3: Run and verify PASS**

Run: `uv run pytest -q` — Expected: 1 passed.

- [ ] **Step 4: Add .gitignore and commit**

```bash
printf '.venv/\n__pycache__/\n*.egg-info/\n.pytest_cache/\n' > .gitignore
git add -A && git commit -m "chore: scaffold uv project"
```

---

### Task 2: Voice grammar parser

**Files:**
- Create: `src/annotator/grammar.py`
- Test: `tests/test_grammar.py`

**Interfaces:**
- Produces: `parse_utterance(raw: str) -> Command`; `Command(kind: str, text: str = "")` dataclass. `kind` ∈ {"highlight", "note", "note_pending", "ask", "undo", "retry", "finished", "end_quiz"}.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_grammar.py
from annotator.grammar import parse_utterance as p

def test_plain_text_is_highlight():
    c = p("Control evaluations bound the risk of scheming models.")
    assert c.kind == "highlight" and c.text.startswith("Control evaluations")

def test_bare_note_is_pending():
    assert p("Note.").kind == "note_pending"

def test_note_with_content():
    c = p("note this contradicts the earlier claim")
    assert c.kind == "note" and c.text == "this contradicts the earlier claim"

def test_ask():
    c = p("Ask what does deference mean here?")
    assert c.kind == "ask" and c.text == "what does deference mean here?"

def test_control_words():
    assert p("undo").kind == "undo"
    assert p("Retry").kind == "retry"
    assert p("finished.").kind == "finished"
    assert p("end quiz").kind == "end_quiz"

def test_note_mid_sentence_is_highlight():
    assert p("We note that the model defects").kind == "highlight"
```

- [ ] **Step 2: Run to verify FAIL** — `uv run pytest tests/test_grammar.py -q` → ModuleNotFoundError.

- [ ] **Step 3: Implement**

```python
# src/annotator/grammar.py
from dataclasses import dataclass

@dataclass
class Command:
    kind: str
    text: str = ""

_BARE = {"note": "note_pending", "undo": "undo", "retry": "retry",
         "finished": "finished", "end quiz": "end_quiz"}

def _clean(s: str) -> str:
    return s.strip().rstrip(".!?,").lower()

def parse_utterance(raw: str) -> Command:
    text = raw.strip()
    if _clean(text) in _BARE:
        return Command(_BARE[_clean(text)])
    first, _, rest = text.partition(" ")
    if _clean(first) in ("note", "ask") and rest.strip():
        return Command(_clean(first), rest.strip())
    return Command("highlight", text)
```

- [ ] **Step 4: Run to verify PASS** — `uv run pytest tests/test_grammar.py -q`.

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: voice grammar parser"`

---

### Task 3: Fuzzy passage matcher

**Files:**
- Create: `src/annotator/matcher.py`
- Test: `tests/test_matcher.py`

**Interfaces:**
- Produces: `find_passage(transcript: str, fulltext: str) -> Match`; `Match(text: str, score: float, start: int)` — always returns the best candidate; the caller applies the threshold. Candidates are sentence windows of length 1–3 so a read-aloud passage spanning sentences still matches.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_matcher.py
from annotator.matcher import find_passage

DOC = ("AI control aims to maintain safety even if models scheme. "
       "Control evaluations measure this with red teams. "
       "The blue team proposes protocols; the red team attacks them. "
       "Deference is a separate axis entirely.")

def test_exact_sentence():
    m = find_passage("Control evaluations measure this with red teams", DOC)
    assert m.score > 90 and "red teams" in m.text

def test_misread_words_still_match():
    m = find_passage("control evaluation measures this with red team", DOC)
    assert m.score > 80 and m.text.startswith("Control evaluations")

def test_two_sentence_span():
    m = find_passage("Control evaluations measure this with red teams. "
                     "The blue team proposes protocols", DOC)
    assert "blue team" in m.text and "Control evaluations" in m.text

def test_garbage_scores_low():
    m = find_passage("completely unrelated cooking recipe for pasta", DOC)
    assert m.score < 60
```

- [ ] **Step 2: Run to verify FAIL** — `uv run pytest tests/test_matcher.py -q`.

- [ ] **Step 3: Implement**

```python
# src/annotator/matcher.py
import re
from dataclasses import dataclass
from rapidfuzz import fuzz

@dataclass
class Match:
    text: str
    score: float
    start: int

def _sentences(fulltext: str) -> list[tuple[int, str]]:
    return [(m.start(), m.group().strip())
            for m in re.finditer(r"[^.!?\n]+[.!?]?", fulltext) if m.group().strip()]

def find_passage(transcript: str, fulltext: str) -> Match:
    sents = _sentences(fulltext)
    best = Match("", 0.0, 0)
    for i in range(len(sents)):
        for span in (1, 2, 3):
            chunk = sents[i:i + span]
            if not chunk:
                continue
            cand = " ".join(s for _, s in chunk)
            score = fuzz.token_sort_ratio(transcript.lower(), cand.lower())
            if score > best.score:
                best = Match(cand, score, chunk[0][0])
    return best
```

- [ ] **Step 4: Run to verify PASS**, then **Step 5: Commit** — `git commit -am "feat: fuzzy passage matcher"`

---

### Task 4: Vault writer

**Files:**
- Create: `src/annotator/vault.py`
- Test: `tests/test_vault.py`

**Interfaces:**
- Produces class `VaultWriter(readings_dir: Path)` with:
  - `start(title: str, meta: dict) -> Path` — create `<title>.md` with frontmatter (`zotero_key`, `url`, `read`, `status: reading`) if absent; remembers path.
  - `add_highlight(text: str) -> None` — appends `- "text"` bullet.
  - `add_annotation(kind: str, text: str) -> None` — kind ∈ {"note","q","a"}; appends `\t- kind: text` under the last highlight.
  - `undo_last_highlight() -> None` — removes the last highlight bullet and its children.
  - `add_section(heading: str, body: str) -> None` — appends `\n## heading\n\nbody\n`.
  - `set_status(status: str) -> None` — rewrites frontmatter `status:` line.
- Filename sanitization: strip `/:\\` from titles.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_vault.py
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
```

- [ ] **Step 2: Run to verify FAIL.**

- [ ] **Step 3: Implement**

```python
# src/annotator/vault.py
import re
from pathlib import Path

class VaultWriter:
    def __init__(self, readings_dir: Path):
        self.dir = Path(readings_dir)
        self.path: Path | None = None

    def start(self, title: str, meta: dict) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[/:\\]", "-", title).strip()
        self.path = self.dir / f"{safe}.md"
        if not self.path.exists():
            fm = "".join(f"{k}: {v}\n" for k, v in meta.items())
            self.path.write_text(f"---\n{fm}status: reading\n---\n")
        return self.path

    def _append(self, s: str) -> None:
        assert self.path is not None
        self.path.write_text(self.path.read_text() + s)

    def add_highlight(self, text: str) -> None:
        self._append(f'- "{text}"\n')

    def add_annotation(self, kind: str, text: str) -> None:
        self._append(f"\t- {kind}: {text}\n")

    def undo_last_highlight(self) -> None:
        assert self.path is not None
        lines = self.path.read_text().splitlines(keepends=True)
        idx = max(i for i, l in enumerate(lines) if l.startswith('- "'))
        end = idx + 1
        while end < len(lines) and lines[end].startswith("\t"):
            end += 1
        self.path.write_text("".join(lines[:idx] + lines[end:]))

    def add_section(self, heading: str, body: str) -> None:
        self._append(f"\n## {heading}\n\n{body}\n")

    def set_status(self, status: str) -> None:
        assert self.path is not None
        t = self.path.read_text()
        self.path.write_text(re.sub(r"^status: .*$", f"status: {status}", t, count=1, flags=re.M))
```

- [ ] **Step 4: Run to verify PASS**, then **Step 5: Commit** — `git commit -am "feat: vault writer"`

---

### Task 5: Zotero client

**Files:**
- Create: `src/annotator/zotero.py`
- Test: `tests/test_zotero.py`

**Interfaces:**
- Produces class `ZoteroClient(base: str = "http://localhost:23119", transport: httpx.BaseTransport | None = None)` with:
  - `current_item() -> dict` — GET `{base}/voiceannotator/current` → `{"key","title","url","year","firstCreator"}` (plugin endpoint, Task 9).
  - `fulltext(key: str) -> str` — GET `{base}/api/users/0/items/{key}/fulltext` → JSON `content` field.
  - `create_highlight(text: str, comment: str = "") -> str` — POST `{base}/voiceannotator/highlight` JSON `{"text","comment"}` → returns `annotationKey`.
  - `delete_annotation(key: str) -> None` — POST `{base}/voiceannotator/delete` JSON `{"key"}`.
- Raises `ZoteroError(str)` on connection failure or non-200, with a human message ("Is Zotero running?").

- [ ] **Step 1: Write failing tests (httpx MockTransport)**

```python
# tests/test_zotero.py
import httpx, json, pytest
from annotator.zotero import ZoteroClient, ZoteroError

def make(handler):
    return ZoteroClient(transport=httpx.MockTransport(handler))

def test_current_and_fulltext_and_highlight():
    def handler(req):
        if req.url.path == "/voiceannotator/current":
            return httpx.Response(200, json={"key": "K1", "title": "T", "url": "u", "year": "2024", "firstCreator": "Greenblatt"})
        if req.url.path == "/api/users/0/items/K1/fulltext":
            return httpx.Response(200, json={"content": "full text here"})
        if req.url.path == "/voiceannotator/highlight":
            assert json.loads(req.content)["text"] == "passage"
            return httpx.Response(200, json={"annotationKey": "ANN1"})
        raise AssertionError(req.url.path)
    z = make(handler)
    assert z.current_item()["key"] == "K1"
    assert z.fulltext("K1") == "full text here"
    assert z.create_highlight("passage") == "ANN1"

def test_error_wraps():
    def handler(req):
        raise httpx.ConnectError("refused")
    with pytest.raises(ZoteroError, match="Is Zotero running"):
        make(handler).current_item()
```

- [ ] **Step 2: Run to verify FAIL.**

- [ ] **Step 3: Implement**

```python
# src/annotator/zotero.py
import httpx

class ZoteroError(Exception):
    pass

class ZoteroClient:
    def __init__(self, base: str = "http://localhost:23119", transport=None):
        self.base = base
        self.http = httpx.Client(transport=transport, timeout=10.0)

    def _req(self, method: str, path: str, **kw):
        try:
            r = self.http.request(method, self.base + path, **kw)
        except httpx.TransportError as e:
            raise ZoteroError(f"Cannot reach Zotero ({e}). Is Zotero running?") from e
        if r.status_code != 200:
            raise ZoteroError(f"Zotero returned {r.status_code} for {path}: {r.text[:200]}")
        return r

    def current_item(self) -> dict:
        return self._req("GET", "/voiceannotator/current").json()

    def fulltext(self, key: str) -> str:
        return self._req("GET", f"/api/users/0/items/{key}/fulltext").json()["content"]

    def create_highlight(self, text: str, comment: str = "") -> str:
        r = self._req("POST", "/voiceannotator/highlight", json={"text": text, "comment": comment})
        return r.json()["annotationKey"]

    def delete_annotation(self, key: str) -> None:
        self._req("POST", "/voiceannotator/delete", json={"key": key})
```

- [ ] **Step 4: Run to verify PASS**, then **Step 5: Commit** — `git commit -am "feat: zotero client"`

---

### Task 6: OpenRouter LLM client

**Files:**
- Create: `src/annotator/llm.py`
- Test: `tests/test_llm.py`

**Interfaces:**
- Produces class `LLMClient(api_key: str, model: str = DEFAULT_MODEL, transport=None)` with:
  - `chat(messages: list[dict], system: str) -> str` — POST `https://openrouter.ai/api/v1/chat/completions`, returns `choices[0].message.content`.
  - `ask(question: str, article_text: str, note_md: str, focus: str) -> str`
  - `consolidate(note_md: str, article_text: str) -> str`
  - `quiz_turn(history: list[dict], note_md: str) -> str` — `history` is chat-format messages of the quiz so far; empty history yields the first question.
- `DEFAULT_MODEL = "deepseek/deepseek-v4-flash"` module constant.
- Article text is truncated to 60,000 characters before sending.

- [ ] **Step 1: Verify the real model slug**

Run: `curl -s https://openrouter.ai/api/v1/models | jq -r '.data[].id' | grep -i deepseek`
If `deepseek/deepseek-v4-flash` is absent, set `DEFAULT_MODEL` to the closest DeepSeek v4 flash slug that IS listed, and record the choice in the commit message.

- [ ] **Step 2: Write failing tests**

```python
# tests/test_llm.py
import httpx, json
from annotator.llm import LLMClient

def make(capture):
    def handler(req):
        capture.append(json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "answer"}}]})
    return LLMClient(api_key="k", transport=httpx.MockTransport(handler))

def test_ask_includes_focus_and_question():
    sent = []
    out = make(sent).ask("what is X", article_text="ARTICLE", note_md="NOTES", focus="the focus passage")
    assert out == "answer"
    body = json.dumps(sent[0])
    assert "what is X" in body and "the focus passage" in body and "ARTICLE" in body

def test_quiz_first_turn_has_no_user_msgs():
    sent = []
    make(sent).quiz_turn([], note_md="NOTES")
    roles = [m["role"] for m in sent[0]["messages"]]
    assert "user" in roles  # the kickoff instruction counts as user content

def test_truncation():
    sent = []
    make(sent).consolidate("N", article_text="x" * 100_000)
    assert len(json.dumps(sent[0])) < 80_000
```

- [ ] **Step 3: Run to verify FAIL.**

- [ ] **Step 4: Implement**

```python
# src/annotator/llm.py
import httpx

DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
_MAX_ARTICLE = 60_000

class LLMClient:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, transport=None):
        self.model = model
        self.http = httpx.Client(
            transport=transport, timeout=120.0,
            headers={"Authorization": f"Bearer {api_key}"})

    def chat(self, messages: list[dict], system: str) -> str:
        r = self.http.post("https://openrouter.ai/api/v1/chat/completions", json={
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages]})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    def ask(self, question: str, article_text: str, note_md: str, focus: str) -> str:
        system = ("You answer a reader's question about an article they are reading. "
                  "Be direct and short. Ground answers in the article text.")
        user = (f"Article text:\n{article_text[:_MAX_ARTICLE]}\n\n"
                f"Reader's highlights and notes so far:\n{note_md}\n\n"
                f"The reader just highlighted: \"{focus}\"\n\n"
                f"Question: {question}")
        return self.chat([{"role": "user", "content": user}], system)

    def consolidate(self, note_md: str, article_text: str) -> str:
        system = ("Consolidate a reader's highlights and notes — NOT a generic paper summary. "
                  "Output markdown with three parts: a structured synthesis of what the reader "
                  "attended to, a short list of likely misunderstandings to check (grounded in "
                  "their notes vs the article), and 3-5 key follow-up questions.")
        user = f"Article text:\n{article_text[:_MAX_ARTICLE]}\n\nReading note:\n{note_md}"
        return self.chat([{"role": "user", "content": user}], system)

    def quiz_turn(self, history: list[dict], note_md: str) -> str:
        system = ("You quiz a reader on an article using their own highlights and notes. "
                  "Ask one question at a time. After each answer: grade it briefly, correct "
                  "if wrong, then ask the next question. Probe weak spots adaptively.")
        kickoff = {"role": "user", "content": f"Reading note:\n{note_md}\n\nBegin the quiz."}
        return self.chat([kickoff, *history], system)
```

- [ ] **Step 5: Run to verify PASS**, then **Step 6: Commit** — `git commit -am "feat: openrouter llm client"`

---

### Task 7: Session orchestrator

**Files:**
- Create: `src/annotator/session.py`
- Test: `tests/test_session.py`

**Interfaces:**
- Consumes: `parse_utterance`, `find_passage`, `ZoteroClient`, `VaultWriter`, `LLMClient` (exact signatures from Tasks 2–6).
- Produces class `Session(zotero, vault, llm, threshold: float = 80.0)` with `handle(raw: str) -> list[dict]`. Each event dict: `{"type": "status"|"chat"|"error", "text": str}`. State: `mode` ("reading"|"quiz"), cached `item`/`fulltext`, `last_annotation_key`, `last_highlight_text`, `pending_note` flag, `last_failed` transcript, `quiz_history` list.
- Behavior table:
  - highlight → lazy-start session (current_item + fulltext + vault.start with title `"{firstCreator} {year} - {title}"`), match; score ≥ threshold → create Zotero highlight + vault bullet + status event; below → error event showing candidate + score, store `last_failed`.
  - retry → re-handle `last_failed` with threshold −15.
  - note_pending → set flag; next highlight-kind utterance is treated as note text.
  - note → `vault.add_annotation("note", ...)`.
  - ask → `llm.ask(...)`, vault `q`/`a` annotations, chat event with the answer.
  - undo → `zotero.delete_annotation(last)` + `vault.undo_last_highlight()`.
  - finished → `llm.consolidate` → `vault.add_section("Consolidation", ...)` → mode=quiz → first `quiz_turn([])` as chat event.
  - in quiz mode any non-command utterance is an answer: append to `quiz_history` as user msg, `quiz_turn(history)`, append assistant msg, chat event.
  - end_quiz → `vault.add_section("Quiz", transcript)` + `set_status("consolidated")` + mode=reading.
  - `ZoteroError` and `httpx.HTTPError` are caught → error event; state unchanged.

- [ ] **Step 1: Write failing tests (fake collaborators)**

```python
# tests/test_session.py
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
```

- [ ] **Step 2: Run to verify FAIL.**

- [ ] **Step 3: Implement**

```python
# src/annotator/session.py
import httpx
from .grammar import parse_utterance
from .matcher import find_passage
from .zotero import ZoteroError

def _ev(type_: str, text: str) -> dict:
    return {"type": type_, "text": text}

class Session:
    def __init__(self, zotero, vault, llm, threshold: float = 80.0):
        self.zotero, self.vault, self.llm = zotero, vault, llm
        self.threshold = threshold
        self.mode = "reading"
        self.item = None
        self.fulltext = ""
        self.last_annotation_key = None
        self.last_highlight_text = ""
        self.pending_note = False
        self.last_failed = None
        self.quiz_history: list[dict] = []

    def handle(self, raw: str) -> list[dict]:
        try:
            return self._handle(raw)
        except (ZoteroError, httpx.HTTPError) as e:
            return [_ev("error", str(e))]

    def _ensure_started(self):
        if self.item is None:
            self.item = self.zotero.current_item()
            self.fulltext = self.zotero.fulltext(self.item["key"])
            title = f'{self.item["firstCreator"]} {self.item["year"]} - {self.item["title"]}'
            from datetime import date
            self.vault.start(title, {"zotero_key": self.item["key"],
                                     "url": self.item["url"],
                                     "read": date.today().isoformat()})

    def _note_md(self) -> str:
        return self.vault.path.read_text() if self.vault.path else ""

    def _handle(self, raw: str) -> list[dict]:
        cmd = parse_utterance(raw)
        if self.mode == "quiz" and cmd.kind not in ("end_quiz",):
            self.quiz_history.append({"role": "user", "content": raw.strip()})
            reply = self.llm.quiz_turn(self.quiz_history, self._note_md())
            self.quiz_history.append({"role": "assistant", "content": reply})
            return [_ev("chat", reply)]
        if cmd.kind == "note_pending":
            self.pending_note = True
            return [_ev("status", "listening for note…")]
        if cmd.kind == "highlight" and self.pending_note:
            self.pending_note = False
            self.vault.add_annotation("note", cmd.text)
            return [_ev("status", "note attached ✓")]
        if cmd.kind == "highlight":
            return self._highlight(cmd.text, self.threshold)
        if cmd.kind == "retry":
            if self.last_failed is None:
                return [_ev("error", "nothing to retry")]
            return self._highlight(self.last_failed, self.threshold - 15)
        if cmd.kind == "note":
            self.vault.add_annotation("note", cmd.text)
            return [_ev("status", "note attached ✓")]
        if cmd.kind == "ask":
            self._ensure_started()
            answer = self.llm.ask(cmd.text, self.fulltext, self._note_md(),
                                  self.last_highlight_text)
            self.vault.add_annotation("q", cmd.text)
            self.vault.add_annotation("a", answer)
            return [_ev("chat", answer)]
        if cmd.kind == "undo":
            if self.last_annotation_key:
                self.zotero.delete_annotation(self.last_annotation_key)
                self.vault.undo_last_highlight()
                self.last_annotation_key = None
                return [_ev("status", "undone ✓")]
            return [_ev("error", "nothing to undo")]
        if cmd.kind == "finished":
            self._ensure_started()
            self.vault.add_section("Consolidation",
                                   self.llm.consolidate(self._note_md(), self.fulltext))
            self.mode = "quiz"
            self.quiz_history = []
            first = self.llm.quiz_turn([], self._note_md())
            self.quiz_history.append({"role": "assistant", "content": first})
            return [_ev("status", "consolidated ✓ — quiz starting"), _ev("chat", first)]
        if cmd.kind == "end_quiz":
            transcript = "\n".join(f'- {m["role"]}: {m["content"]}' for m in self.quiz_history)
            self.vault.add_section("Quiz", transcript)
            self.vault.set_status("consolidated")
            self.mode = "reading"
            return [_ev("status", "quiz saved ✓")]
        return [_ev("error", f"unknown command {cmd.kind}")]

    def _highlight(self, transcript: str, threshold: float) -> list[dict]:
        self._ensure_started()
        m = find_passage(transcript, self.fulltext)
        if m.score < threshold:
            self.last_failed = transcript
            return [_ev("error", f'no match (best {m.score:.0f}): "{m.text[:80]}" — say retry or re-read')]
        self.last_failed = None
        self.last_annotation_key = self.zotero.create_highlight(m.text)
        self.last_highlight_text = m.text
        self.vault.add_highlight(m.text)
        return [_ev("status", f'highlighted ✓ ({m.score:.0f}): "{m.text[:80]}"')]
```

- [ ] **Step 4: Run all tests** — `uv run pytest -q` → all pass.

- [ ] **Step 5: Commit** — `git commit -am "feat: session orchestrator"`

---

### Task 8: Hub API + static serving

**Files:**
- Create: `src/annotator/hub.py`
- Test: `tests/test_hub.py`

**Interfaces:**
- Consumes: `Session.handle(raw) -> list[dict]`.
- Produces: `create_app(session) -> FastAPI` with `POST /utterance` (body `{"text": str}` → `{"events": [...]}`) and `GET /` serving `companion/index.html` (Task 10; a missing file returns a plain placeholder page, so this task tests only `/utterance`).

- [ ] **Step 1: Write failing test**

```python
# tests/test_hub.py
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
```

- [ ] **Step 2: Run to verify FAIL.**

- [ ] **Step 3: Implement**

```python
# src/annotator/hub.py
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
```

- [ ] **Step 4: Run to verify PASS**, then **Step 5: Commit** — `git commit -am "feat: hub api"`

---

### Task 9: Zotero plugin

**Files:**
- Create: `zotero-plugin/manifest.json`, `zotero-plugin/bootstrap.js`, `zotero-plugin/README.md`

**Interfaces:**
- Produces the three HTTP endpoints Task 5's client consumes: `GET /voiceannotator/current`, `POST /voiceannotator/highlight`, `POST /voiceannotator/delete` — response shapes exactly as tested in `tests/test_zotero.py`.
- No Python tests; manual checklist below. **Research note:** the reader-internals calls (`_iframeWindow`, find primitives) must be verified against the installed Zotero 9 source — `github.com/zotero/zotero` (`chrome/content/zotero/xpcom/reader.js`) and `github.com/zotero/reader`. The endpoint scaffolding and annotation-item creation below use stable, documented APIs; only the text→position lookup may need adjustment.

- [ ] **Step 1: Write manifest**

```json
{
  "manifest_version": 2,
  "name": "Voice Annotator Bridge",
  "version": "0.1.0",
  "description": "Local endpoints for voice-driven highlighting",
  "applications": {
    "zotero": {
      "id": "voice-annotator@kaustubh.local",
      "update_url": "",
      "strict_min_version": "7.0",
      "strict_max_version": "9.*"
    }
  }
}
```

- [ ] **Step 2: Write bootstrap.js**

```javascript
// zotero-plugin/bootstrap.js
var endpoints = {};

function activeReader() {
  var reader = Zotero.Reader._readers[Zotero.Reader._readers.length - 1];
  if (!reader) throw new Error("No reader window open");
  return reader;
}

function register(path, methods, handler) {
  endpoints[path] = function () {};
  endpoints[path].prototype = {
    supportedMethods: methods,
    supportedDataTypes: ["application/json"],
    init: async function (req) {
      try {
        var out = await handler(req.data || {});
        return [200, "application/json", JSON.stringify(out)];
      } catch (e) {
        return [500, "text/plain", String(e)];
      }
    },
  };
  Zotero.Server.Endpoints[path] = endpoints[path];
}

function install() {}
function uninstall() {}

function startup() {
  register("/voiceannotator/current", ["GET"], async function () {
    var reader = activeReader();
    var item = Zotero.Items.get(reader.itemID);
    var parent = item.parentItem || item;
    return {
      key: parent.key,
      title: parent.getField("title"),
      url: parent.getField("url") || ("https://doi.org/" + parent.getField("DOI")),
      year: parent.getField("date").slice(0, 4),
      firstCreator: parent.firstCreator,
    };
  });

  register("/voiceannotator/highlight", ["POST"], async function (data) {
    var reader = activeReader();
    // Locate the text in the PDF via the reader's find primitives, then create
    // a real highlight annotation. VERIFY these internals against the installed
    // Zotero 9 source (see task research note) and adjust names if they moved.
    var internal = reader._internalReader;
    var results = await internal._primaryView.findInDocument(data.text);
    if (!results || !results.length) throw new Error("text not found in document");
    var pos = results[0].position; // { pageIndex, rects }
    var attachment = Zotero.Items.get(reader.itemID);
    var annotation = new Zotero.Item("annotation");
    annotation.libraryID = attachment.libraryID;
    annotation.parentID = attachment.id;
    annotation.annotationType = "highlight";
    annotation.annotationText = data.text;
    annotation.annotationComment = data.comment || "";
    annotation.annotationColor = "#ffd400";
    annotation.annotationPageLabel = String(pos.pageIndex + 1);
    annotation.annotationSortIndex = "00000|000000|00000";
    annotation.annotationPosition = JSON.stringify(pos);
    await annotation.saveTx();
    internal.navigate({ position: pos });
    return { annotationKey: annotation.key };
  });

  register("/voiceannotator/delete", ["POST"], async function (data) {
    var item = Zotero.Items.getByLibraryAndKey(Zotero.Libraries.userLibraryID, data.key);
    if (item) await item.eraseTx();
    return { ok: true };
  });
}

function shutdown() {
  for (var path in endpoints) delete Zotero.Server.Endpoints[path];
}
```

- [ ] **Step 3: Research pass** — open the installed Zotero source (Zotero 9 app bundle or github tags) and confirm/fix: `Zotero.Reader._readers`, `reader._internalReader`, the find-in-document call, and the position shape. Update `bootstrap.js` accordingly. Record findings in `zotero-plugin/README.md`.

- [ ] **Step 4: Package and install**

```bash
cd ~/voice-annotator/zotero-plugin && zip -r ../voice-annotator.xpi manifest.json bootstrap.js
```
Install in Zotero: Tools → Plugins → gear → Install Plugin From File. Restart Zotero.

- [ ] **Step 5: Manual test checklist** (write results into `zotero-plugin/README.md`)
  - `curl localhost:23119/voiceannotator/current` with a PDF open → JSON with correct title.
  - Same with no reader open → 500 "No reader window open".
  - `curl -X POST localhost:23119/voiceannotator/highlight -H 'Content-Type: application/json' -d '{"text": "<exact sentence from the PDF>"}'` → highlight appears in the reader, view scrolls to it, response has `annotationKey`.
  - POST `/voiceannotator/delete` with that key → highlight disappears.

- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat: zotero bridge plugin"`

---

### Task 10: Companion window UI

**Files:**
- Create: `companion/index.html`

**Interfaces:**
- Consumes: `POST /utterance` from Task 8.
- Produces: the Wispr Flow dictation target — input auto-submits ~600 ms after text stops arriving; status line; scrolling chat pane.

- [ ] **Step 1: Write the page**

```html
<!-- companion/index.html -->
<!doctype html>
<meta charset="utf-8">
<title>voice annotator</title>
<style>
  body { font: 13px -apple-system, sans-serif; margin: 0; background: #1e1e1e; color: #ddd;
         display: flex; flex-direction: column; height: 100vh; }
  #chat { flex: 1; overflow-y: auto; padding: 8px; white-space: pre-wrap; }
  .status { color: #8c8; } .error { color: #e88; } .chat-msg { color: #ade; margin: 6px 0; }
  #box { margin: 8px; padding: 8px; font-size: 14px; border-radius: 6px;
         border: 1px solid #444; background: #2a2a2a; color: #eee; }
</style>
<div id="chat"></div>
<input id="box" placeholder="dictate here" autofocus>
<script>
  const chat = document.getElementById("chat"), box = document.getElementById("box");
  let timer = null;
  function show(ev) {
    const d = document.createElement("div");
    d.className = ev.type === "chat" ? "chat-msg" : ev.type;
    d.textContent = ev.text;
    chat.appendChild(d); chat.scrollTop = chat.scrollHeight;
  }
  async function submit() {
    const text = box.value.trim();
    if (!text) return;
    box.value = "";
    const r = await fetch("/utterance", { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
    (await r.json()).events.forEach(show);
  }
  box.addEventListener("input", () => {          // Wispr Flow types but never hits Enter
    clearTimeout(timer);
    timer = setTimeout(submit, 600);
  });
  box.addEventListener("keydown", e => { if (e.key === "Enter") { clearTimeout(timer); submit(); } });
</script>
```

- [ ] **Step 2: Manual test** — `uv run uvicorn 'annotator.hub:create_app' --factory` won't work with a session arg; instead run a scratch script:

```bash
uv run python - <<'EOF' &
import uvicorn
from annotator.hub import create_app
class Echo:  # no Zotero needed for a UI check
    def handle(self, raw): return [{"type": "status", "text": f"echo: {raw}"}]
uvicorn.run(create_app(Echo()), port=8765)
EOF
open http://localhost:8765
```
Type into the box, wait 600 ms → "echo: …" appears. Test Wispr Flow dictation into the box too. Kill the background server.

- [ ] **Step 3: Commit** — `git add companion && git commit -m "feat: companion window ui"`

---

### Task 11: App entrypoint (window + hotkey)

**Files:**
- Create: `src/annotator/app.py`
- Modify: `pyproject.toml` (add `[project.scripts] annotate = "annotator.app:main"`)

**Interfaces:**
- Consumes: everything above with real clients.
- Produces: `uv run annotate` → hub on port 8765, always-on-top pywebview window, global hotkey ⌃⌥Space focuses the window.

- [ ] **Step 1: Implement**

```python
# src/annotator/app.py
import os, threading
from pathlib import Path
import uvicorn, webview
from pynput import keyboard
from .hub import create_app
from .llm import LLMClient
from .session import Session
from .vault import VaultWriter
from .zotero import ZoteroClient

READINGS = Path.home() / "obsidian-ais" / "readings"
PORT = 8765

def main():
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("Set OPENROUTER_API_KEY first.")
    session = Session(ZoteroClient(), VaultWriter(READINGS), LLMClient(api_key))
    app = create_app(session)
    threading.Thread(target=lambda: uvicorn.run(app, port=PORT, log_level="warning"),
                     daemon=True).start()
    window = webview.create_window("voice annotator", f"http://localhost:{PORT}",
                                   width=380, height=520, on_top=True)
    hotkey = keyboard.GlobalHotKeys({"<ctrl>+<alt>+<space>": lambda: window.show()})
    hotkey.start()
    webview.start()

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Register script and sync** — add to `pyproject.toml`:

```toml
[project.scripts]
annotate = "annotator.app:main"
```
Run: `uv sync`.

- [ ] **Step 3: Manual test** — `OPENROUTER_API_KEY=dummy uv run annotate` → window appears on top, echo of an error event when Zotero is closed proves the wiring (expect the "Is Zotero running?" error if Zotero is shut). macOS will prompt for Accessibility permission for pynput — grant it. Note in README that the hotkey needs this permission.

- [ ] **Step 4: Commit** — `git commit -am "feat: app entrypoint with window and hotkey"`

---

### Task 12: End-to-end scripted test + README

**Files:**
- Create: `tests/test_e2e.py`, `README.md`

**Interfaces:**
- Consumes: the full stack with `FakeZotero`/`FakeLLM` styles from Task 7's tests, driven through the HTTP layer.

- [ ] **Step 1: Write the e2e test**

```python
# tests/test_e2e.py
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
```

- [ ] **Step 2: Run full suite** — `uv run pytest -q` → all pass.

- [ ] **Step 3: Write README.md** — cover: what it is (3 sentences), setup (uv sync, plugin install from Task 9 Step 4, `OPENROUTER_API_KEY`, Accessibility permission), the voice grammar table from the spec, the per-utterance loop (⌃⌥Space → Flow hotkey → speak), and the Wispr Flow custom-dictionary tip for personal shorthand.

- [ ] **Step 4: Commit** — `git add -A && git commit -m "test: e2e session + README"`

---

## Self-review notes

- Spec coverage: grammar (T2), matching (T3), vault format incl. undo/sections/status (T4), Zotero read+write (T5, T9), ask/consolidate/quiz via OpenRouter (T6), state machine incl. retry/note-pending/quiz mode (T7), companion + auto-submit (T8, T10), always-on-top + hotkey (T11), session journal — **covered implicitly by vault-first writes; raw-utterance journal dropped as YAGNI since every utterance's effect lands in the note immediately**. Chrome extension: phase 2, out of scope here.
- Known-risk task: T9 Step 3 (reader internals) is explicitly a research step with named sources.
- Type consistency: `Session.handle` event dicts match hub test and companion JS; `VaultWriter` method names consistent across T4/T7/T12; `FakeZotero`/`FakeLLM` imported by T12 from T7's test module.
