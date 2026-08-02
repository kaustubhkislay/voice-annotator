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
