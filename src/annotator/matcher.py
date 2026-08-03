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

MARGIN = 5.0
TITLE_THRESHOLD = 95.0

def find_passage(transcript: str, fulltext: str, cursor: int | None = None,
                  title: str | None = None) -> Match:
    sents = _sentences(fulltext)
    transcript_len = len(transcript)
    candidates: list[Match] = []

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
            candidates.append(Match(cand, score, chunk[0][0]))

    if not candidates:
        return Match("", 0.0, 0)

    best_raw = max(c.score for c in candidates)
    eligible = [c for c in candidates if c.score >= best_raw - MARGIN]

    if title is not None:
        def is_title_like(c: Match) -> bool:
            return fuzz.token_sort_ratio(c.text.lower(), title.lower()) >= TITLE_THRESHOLD
        non_title = [c for c in eligible if not is_title_like(c)]
        if non_title:
            eligible = non_title

    if cursor is None:
        eligible.sort(key=lambda c: c.start)
        return eligible[0]

    def distance(c: Match) -> float:
        return (c.start - cursor) if c.start >= cursor else 3 * (cursor - c.start)

    eligible.sort(key=lambda c: (distance(c), c.start))
    return eligible[0]
