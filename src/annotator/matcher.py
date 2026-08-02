import re
from dataclasses import dataclass
from functools import lru_cache
from rapidfuzz import fuzz

@dataclass
class Match:
    text: str
    score: float
    start: int

@lru_cache(maxsize=8)
def _sentences(fulltext: str) -> tuple[tuple[int, str], ...]:
    return tuple((m.start(), m.group().strip())
                 for m in re.finditer(r"[^.!?\n]+[.!?]?", fulltext) if m.group().strip())

def find_passage(transcript: str, fulltext: str) -> Match:
    sents = _sentences(fulltext)
    best = Match("", 0.0, 0)
    transcript_len = len(transcript)

    for i in range(len(sents)):
        for span in (1, 2, 3):
            chunk = sents[i:i + span]
            if not chunk:
                continue
            cand = " ".join(s for _, s in chunk)
            cand_len = len(cand)

            # Length prefilter: skip if candidate length is >3x or <1/3x transcript length
            if transcript_len > 0:
                if cand_len > 3 * transcript_len or cand_len < transcript_len / 3:
                    continue

            score = fuzz.token_sort_ratio(transcript.lower(), cand.lower())
            if score > best.score:
                best = Match(cand, score, chunk[0][0])
    return best
