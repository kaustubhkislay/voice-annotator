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
TITLE_MARGIN = 15.0
TITLE_CONTAINS_THRESHOLD = 90.0
MIN_TITLE_LEN = 15

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

    if title is not None and len(title) >= MIN_TITLE_LEN:
        def is_title_like(c: Match) -> bool:
            # Title is (nearly) contained in the candidate — catches windows
            # that pair the title with an author line, which dilutes a
            # whole-string ratio against the bare title below any sane
            # threshold while still being a title-only read for the user.
            return fuzz.partial_ratio(title.lower(), c.text.lower()) >= TITLE_CONTAINS_THRESHOLD

        title_margin_eligible = [c for c in candidates if c.score >= best_raw - TITLE_MARGIN]
        non_title_wide = [c for c in title_margin_eligible if not is_title_like(c)]
        if non_title_wide:
            # At least one plausible (within TITLE_MARGIN) candidate isn't a
            # title read, so drop every title-like candidate from the normal
            # eligible set.
            non_title_main = [c for c in eligible if not is_title_like(c)]
            if non_title_main:
                eligible = non_title_main
            else:
                eligible = [max(non_title_wide, key=lambda c: c.score)]
        # else: every candidate within TITLE_MARGIN is title-like — keep the
        # original eligible set, since the user may genuinely be reading the
        # title.

    if cursor is None:
        eligible.sort(key=lambda c: c.start)
        return eligible[0]

    def distance(c: Match) -> float:
        return (c.start - cursor) if c.start >= cursor else 3 * (cursor - c.start)

    eligible.sort(key=lambda c: (distance(c), c.start))
    return eligible[0]
