from dataclasses import dataclass


@dataclass
class Command:
    kind: str
    text: str = ""


_BARE = {
    "note": "note_pending",
    "undo": "undo",
    "retry": "retry",
    "finished": "finished",
    "end quiz": "end_quiz",
}


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
