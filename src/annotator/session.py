import httpx
from .grammar import parse_utterance
from .matcher import find_passage
from .vault import VaultError
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
        self.cursor = None

    def handle(self, raw: str) -> list[dict]:
        try:
            return self._handle(raw)
        except (ZoteroError, httpx.HTTPError, VaultError) as e:
            return [_ev("error", str(e))]

    def _ensure_started(self):
        if self.item is None:
            item = self.zotero.current_item()
            fulltext = self.zotero.fulltext(item["key"])
            title = f'{item["firstCreator"]} {item["year"]} - {item["title"]}'
            title = " ".join(title.split())
            from datetime import date
            self.vault.start(title, {"zotero_key": item["key"],
                                     "url": item["url"],
                                     "read": date.today().isoformat()})
            # Assign only after every fallible step succeeded, so a failure
            # (e.g. fulltext() raising) leaves self.item unset and the next
            # call retries from scratch instead of getting stuck half-started.
            self.item = item
            self.fulltext = fulltext

    def _note_md(self) -> str:
        return self.vault.path.read_text() if self.vault.path else ""

    def _mirror_comment(self, text: str) -> list[dict]:
        # Best-effort: the note/answer is already durably saved to the vault
        # by the time this runs, so a Zotero-side failure here must not
        # undo that or block the caller — just surface it as an extra event.
        if not self.last_annotation_key:
            return []
        try:
            self.zotero.add_comment(self.last_annotation_key, text)
        except ZoteroError as e:
            return [_ev("error", f"note saved to vault; Zotero comment failed: {e}")]
        return []

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
            self._ensure_started()
            self.vault.add_annotation("note", cmd.text)
            self.pending_note = False
            return [_ev("status", "note attached ✓")] + self._mirror_comment(cmd.text)
        if cmd.kind == "highlight":
            return self._highlight(cmd.text, self.threshold)
        if cmd.kind == "retry":
            if self.last_failed is None:
                return [_ev("error", "nothing to retry")]
            return self._highlight(self.last_failed, self.threshold - 15)
        if cmd.kind == "note":
            self._ensure_started()
            self.vault.add_annotation("note", cmd.text)
            self.pending_note = False
            return [_ev("status", "note attached ✓")] + self._mirror_comment(cmd.text)
        if cmd.kind == "ask":
            self._ensure_started()
            answer = self.llm.ask(cmd.text, self.fulltext, self._note_md(),
                                  self.last_highlight_text)
            self.vault.add_annotation("q", cmd.text)
            self.vault.add_annotation("a", answer)
            events = [_ev("chat", answer)]
            if self.last_annotation_key:
                events += self._mirror_comment(f"Q: {cmd.text}\nA: {answer}")
            return events
        if cmd.kind == "undo":
            if self.last_annotation_key:
                self.zotero.delete_annotation(self.last_annotation_key)
                self.vault.undo_last_highlight()
                self.last_annotation_key = None
                self.last_highlight_text = ""
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
            if self.mode != "quiz":
                return [_ev("error", "not in a quiz")]
            transcript = "\n".join(f'- {m["role"]}: {m["content"]}' for m in self.quiz_history)
            self.vault.add_section("Quiz", transcript)
            self.vault.set_status("consolidated")
            self.mode = "reading"
            return [_ev("status", "quiz saved ✓")]
        return [_ev("error", f"unknown command {cmd.kind}")]

    def _highlight(self, transcript: str, threshold: float) -> list[dict]:
        self._ensure_started()
        m = find_passage(transcript, self.fulltext, cursor=self.cursor, title=self.item["title"])
        if m.score < threshold:
            self.last_failed = transcript
            return [_ev("error", f'no match (best {m.score:.0f}): "{m.text[:80]}" — say retry or re-read')]
        # Only clear last_failed once the write actually succeeds. If the
        # Zotero/vault write raises, save the original transcript to
        # last_failed before re-raising, so "retry" can redo the write
        # without the user re-dictating the passage.
        try:
            self.last_annotation_key = self.zotero.create_highlight(m.text, key=self.item["key"])
            self.last_highlight_text = m.text
            self.vault.add_highlight(m.text)
        except ZoteroError:
            self.last_failed = transcript
            raise
        self.last_failed = None
        self.cursor = m.start + len(m.text)
        return [_ev("status", f'highlighted ✓ ({m.score:.0f}): "{m.text[:80]}"')]
