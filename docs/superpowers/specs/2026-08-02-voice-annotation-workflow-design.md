# Voice-driven reading annotation workflow — design

Date: 2026-08-02
Status: approved (brainstorm complete)
Repo: `~/voice-annotator`

## Purpose

Read an article/PDF, speak a passage aloud, and have it highlighted in the reader.
Speak notes and questions against highlights. Everything lands, organized, in the
`ais` Obsidian vault. Saying "finished" consolidates the notes, surfaces likely
misunderstandings and follow-up questions, and runs an interactive voice quiz.

## Scope decisions (locked)

- **Zotero PDFs first.** The Chrome extension for web articles is phase 2.
- **Curius is untouched.** Voice highlights are working notes, not curation; social
  highlights there would be noise. A manual "promote to Curius" action may come later.
- **No custom PDF viewer.** Zotero's reader does rendering and annotation storage.
- **Voice input = Wispr Flow → companion window (Option A).** Flow is plain system
  dictation typing into a focused text field; no Flow API exists or is needed. The
  input source is swappable later (push-to-talk whisper.cpp) without hub changes.
- **LLM = OpenRouter, DeepSeek-v4-flash**, key from env var `OPENROUTER_API_KEY`
  (mint a fresh key; the old one was scheduled for revocation). Verify the exact
  model slug at implementation time.
- **Vault target = `~/obsidian-ais/readings/`**, one note per article.

## Architecture

Single uv-managed Python repo, four parts:

1. **Hub** — FastAPI process on localhost. Owns all state: current article session,
   highlight list, mode (highlighting / awaiting-note / quiz). All other parts are
   thin clients.
2. **Companion window** — small always-on-top `pywebview` window served by the hub.
   One text input (the Wispr Flow target), a status line, and a chat pane used for
   mid-reading Q&A and the end-of-article quiz. A global hotkey focuses the input.
3. **Zotero plugin** — ~150-line bootstrapped plugin. Zotero's local HTTP API is
   **read-only**, so the plugin registers a write endpoint on Zotero's existing local
   server (port 23119). Given exact text it: finds the open reader, creates a real
   highlight annotation, scrolls to and flashes it, and returns the annotation key.
   It also reports which item the reader currently has open.
4. **Chrome extension (phase 2)** — speaks the same hub protocol over a WebSocket;
   highlights DOM text and stores locally, never in Curius.

## Data flow — one utterance

1. Focus companion (global hotkey or click) → press Flow hotkey → speak.
2. Flow types the transcript into the input. Flow does not press Enter; the companion
   auto-submits after ~600 ms with no new text inserted.
3. Hub parses the utterance against the voice grammar.
4. Highlight path: hub asks the plugin which item is open, fetches that item's full
   text once per session via Zotero's read API, fuzzy-matches the transcript with
   `rapidfuzz`, and sends the exact canonical text to the plugin. Fuzzy logic lives
   only in Python; the plugin only ever does exact search.
5. Plugin creates the highlight and confirms; companion shows "highlighted ✓" and the
   matched text.
6. Hub appends to the vault note immediately (crash-safe; no separate export step).

## Voice grammar

Checked only at utterance start:

- **plain text** → highlight that passage
- **"note"** alone → next utterance is a note on the last highlight;
  **"note …"** → one-shot note
- **"ask …"** → question to DeepSeek with context = article full text + all
  highlights/notes + last highlight as focus. Answer streams to the chat pane and the
  exchange is logged under the relevant highlight.
- **"undo"** → remove last highlight from Zotero and the vault note
- **"retry"** → re-match the last failed utterance with a looser threshold
- **"finished"** → end-of-article flow
- **"end quiz"** → close the quiz and write the transcript summary

## Vault note format

`readings/<Author> <Year> - <Title>.md`, created on first highlight:

```markdown
---
zotero_key: ABCD1234
url: https://arxiv.org/abs/...
read: 2026-08-02
status: reading   # reading | consolidated
---
- "matched highlight text"
	- note: spoken note, verbatim
	- q: spoken question
	- a: model answer
- "next highlight"
```

Dash-bullets match vault style. Spoken notes stay verbatim — vault notetaking rules
apply (no smoothing, shorthand preserved). Wikilinks spoken aloud are preserved.

## "Finished" flow

1. Hub calls OpenRouter with the full note + article text → consolidation of *the
   user's notes* (not a paper summary), likely misunderstandings to check, and key
   follow-up questions. Appended under `## Consolidation`.
2. Companion switches to quiz mode: model asks questions grounded in the highlights;
   user answers by voice into the same input; model grades and probes adaptively.
3. On "end quiz": `## Quiz` section appended (questions, answers, verdicts) and
   frontmatter `status:` flips to `consolidated`.

## Error handling

- **Fuzzy match below threshold**: show best candidate + score; highlight nothing
  until "retry" or a re-read.
- **Zotero closed / no reader open**: clear status error; the utterance is kept.
- **OpenRouter down**: highlights/notes are already in the vault; "finished" again
  retries consolidation.
- Hub journals every raw utterance to a session log for recovery.

## Testing

- Unit tests: grammar parser; fuzzy matcher against fixture article texts including
  OCR-noisy ones.
- Zotero plugin: manual test checklist.
- One scripted end-to-end test drives the hub with fake utterances against a mock
  Zotero.

## Out of scope (explicit)

- Curius write integration, always-listening voice (whisper.cpp), custom PDF viewer,
  mobile. Chrome extension is phase 2, after the Zotero chain works end to end.
