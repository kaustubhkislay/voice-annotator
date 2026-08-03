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
HEAD_REGION = 400
TITLE_WHOLE_THRESHOLD = 90.0

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
            # Position: the title (and any author line right after it) lives
            # in the head region of the document, so any candidate that
            # starts there is presumptively a title/byline read.
            # Exact match: a symmetric whole-string ratio catches a running
            # head reprinting the title verbatim on later pages — but a full
            # body sentence that merely quotes/echoes the title phrase scores
            # low here because the extra body words dilute both sides of the
            # ratio symmetrically (unlike a one-sided containment check).
            return (c.start < HEAD_REGION or
                    fuzz.token_sort_ratio(c.text.lower(), title.lower()) >= TITLE_WHOLE_THRESHOLD)

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
