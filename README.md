# voice-annotator

Voice-annotator is a voice-driven reading tool for Zotero. You read a PDF out
loud, and the tool turns your speech into Zotero highlights and a linked
Obsidian note. It uses an LLM to answer questions, consolidate your notes,
and quiz you at the end of a reading session.

## Status

This is a personal tool, not a maintained product. It is tested on macOS
only. Do not assume it works on other platforms. It supports PDFs opened
in Zotero. A Chrome extension for web articles is planned but not built.

## Requirements

- macOS.
- Zotero 7 or later (developed and tested against Zotero 9).
- A dictation tool that types into a text field. The author uses Wispr
  Flow. Any similar tool works, because the companion window reads plain
  text from a normal input box.
- An OpenRouter API key, for the ask/consolidate/quiz features.

## Setup

1. Install dependencies:

   ```bash
   uv sync
   ```

2. Build and install the Zotero plugin. Build the `.xpi` file:

   ```bash
   cd zotero-plugin && zip -r ../voice-annotator.xpi manifest.json bootstrap.js
   ```

   Then, in Zotero: Tools -> Plugins -> gear icon -> Install Plugin From
   File. Select `voice-annotator.xpi`. Restart Zotero.

   See `zotero-plugin/README.md` for headless install steps and endpoint
   details.

3. Export your OpenRouter API key:

   ```bash
   export OPENROUTER_API_KEY=sk-...
   ```

4. Optional: set the vault directory. By default, notes go to
   `~/obsidian-ais/readings`. To use a different directory:

   ```bash
   export VOICE_ANNOTATOR_VAULT_DIR=/path/to/your/vault
   ```

5. The global hotkey needs Accessibility permission for your terminal app.
   macOS often does not prompt for it. If the hotkey does nothing, grant it
   manually in System Settings -> Privacy & Security -> Accessibility, then
   restart the tool.

   If you use a tiling window manager, exempt the companion window from
   tiling. For AeroSpace, add to `~/.aerospace.toml`:

   ```toml
   [[on-window-detected]]
   if.window-title-regex-substring = "voice annotator"
   run = "layout floating"
   ```

   AeroSpace has no sticky windows, so the companion stays on one
   workspace. Instead of moving it by hand, bind `scripts/summon.sh` to a
   key. The script tells AeroSpace to move the window into your current
   workspace (so AeroSpace does not jump you to its old workspace), then
   asks the app to re-pin the window top-right without taking focus:

   ```toml
   [mode.main.binding]
   cmd-shift-space = 'exec-and-forget /path/to/voice-annotator/scripts/summon.sh'
   ```

   This route needs no Accessibility permission. Without a tiling WM, a
   plain `curl -X POST http://localhost:8765/summon` does the same job.

6. Run the tool:

   ```bash
   uv run annotate
   ```

## Usage

Open a PDF in Zotero. Read a passage out loud. The tool matches your
speech against the document text and creates a Zotero highlight, and it
writes the same highlight to a note in your Obsidian vault.

### Voice grammar

Say a command word to control the session. Say plain text to highlight it.

| You say | What happens |
| --- | --- |
| Plain text (a passage from the document) | Highlights the matched passage in Zotero and the note. |
| "note" (alone) | Waits for your next utterance and attaches it as a note. |
| "note ..." | Attaches the rest of the sentence as a note. |
| "ask ..." | Sends the question to the LLM and logs the question and answer in the note. |
| "undo" | Removes the last highlight from Zotero and from the note. |
| "retry" | Retries the last failed highlight match, with a looser matching threshold. |
| "finished" | Consolidates the note with the LLM and starts a quiz. |
| "end quiz" | Ends the quiz, saves the transcript, and marks the note as consolidated. |

During an active quiz, every utterance except "end quiz" is treated as a
quiz answer. Commands like "undo" do not execute.

#### What counts as a highlight

You can read out loud in three ways, and all three highlight the matched
text in Zotero and the note:

- **A full sentence**, read as printed. This matches most reliably.
- **A partial sentence** — reading only part of a long sentence, or
  paraphrasing/misreading a few words, still matches the sentence (or
  span of sentences) it came from.
- **A short exact phrase** (fewer than 4 words, e.g. "Other definitions.")
  — too short for a reliable fuzzy match on its own, so it must appear
  **verbatim** in the document text. A hit highlights the whole sentence
  that contains it, not just the quoted words. If the same short phrase
  appears more than once, the tool picks the occurrence closest ahead of
  where you last highlighted. If it doesn't appear verbatim anywhere, you
  get an error asking you to read a longer span instead.

Notes always attach to your **last highlight**, wherever it came from — do
not re-read the passage when saying a note; just say "note ..." (or "note"
followed by your note text as a separate utterance) right after the
highlight.

### The per-utterance loop

For each utterance:

1. Press cmd+shift+space. This shows the companion window.
2. Press your dictation tool's hotkey (for example, Wispr Flow's hotkey).
3. Speak.

The companion window sends your text to the tool and shows the result:
a highlight confirmation, an error, or a chat reply from the LLM.

## Note format

The tool writes one Markdown file per reading, in your vault directory.
The file name is `{author} {year} - {title}.md`. Example:

```markdown
---
zotero_key: K1
url: https://example.com/paper
read: 2026-08-02
status: reading
---
- "Control evaluations measure this with red teams."
	- note: key method of the paper
	- q: what is a red team
	- a: llm answer

## Consolidation

consolidated md

## Quiz

- assistant: quiz msg 0
- user: my quiz answer
```

After you say "end quiz", the tool sets `status: consolidated` in the
frontmatter.

## Tip: personal shorthand

If you use short phrases as commands (for example, a nickname for "ask" or
a habitual filler word), add them to your dictation tool's custom
dictionary. This stops the dictation tool from mis-transcribing them, so
the voice grammar in this tool matches your words reliably.

## License

MIT. See `LICENSE`.
