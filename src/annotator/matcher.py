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
TITLE_WHOLE_THRESHOLD = 90.0
TITLE_CONTAINS_LEN_MULT = 2.5
TITLE_CONTAINS_THRESHOLD = 95.0
LENGTH_LOWER_MULT = 1 / 3
LENGTH_UPPER_MULT = 6

def _norm(s: str) -> str:
    # Lowercase and collapse every run of non-alphanumeric characters (spaces,
    # punctuation, hyphens) to a single space. This is what lets a spoken
    # "self improvement" match a printed "self-improvement" — hyphenation and
    # punctuation differences stop mattering entirely once both sides go
    # through the same normalization before scoring.
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s.lower()).split())

def find_passage(transcript: str, fulltext: str, cursor: int | None = None,
                  title: str | None = None) -> Match:
    sents = _sentences(fulltext)
    transcript_len = len(transcript)
    transcript_norm = _norm(transcript)
    candidates: list[Match] = []

    for i in range(len(sents)):
        for span in (1, 2, 3):
            chunk = sents[i:i + span]
            if not chunk:
                continue
            cand = " ".join(s for _, s in chunk)
            cand_len = len(cand)

            # Length prefilter: lower bound guards against a short utterance
            # spuriously matching a whole paragraph. Upper bound is loose
            # (6x) so a partial read of a long sentence — which is much
            # shorter than what it's read from — still stays in.
            if transcript_len > 0:
                if cand_len > LENGTH_UPPER_MULT * transcript_len or cand_len < transcript_len * LENGTH_LOWER_MULT:
                    continue

            cand_norm = _norm(cand)
            # Blend token_set_ratio (robust to a partial read that's a subset
            # of the sentence's words) with token_sort_ratio (still penalizes
            # a candidate that's mostly unrelated extra words) so neither
            # failure mode dominates on its own.
            score = (fuzz.token_set_ratio(transcript_norm, cand_norm) +
                     fuzz.token_sort_ratio(transcript_norm, cand_norm)) / 2
            candidates.append(Match(cand, score, chunk[0][0]))

    if not candidates:
        return Match("", 0.0, 0)

    best_raw = max(c.score for c in candidates)
    eligible = [c for c in candidates if c.score >= best_raw - MARGIN]

    if title is not None:
        title_norm = _norm(title)

        def is_title_like(c: Match) -> bool:
            # Symmetric, normalized whole-string ratio: kills the title line
            # itself and any running head reprinting it verbatim, while a
            # body sentence that merely echoes title vocabulary scores low
            # because the extra body words dilute both sides of the ratio.
            # No position rule — the abstract (and other head-region body
            # text) starts well within any plausible "head region" cutoff on
            # real documents, so position alone false-flags real content.
            cand_norm = _norm(c.text)
            if fuzz.token_sort_ratio(cand_norm, title_norm) >= TITLE_WHOLE_THRESHOLD:
                return True
            # A "title + byline" window (e.g. "Title. Tom Cunningham*.") can
            # dilute the symmetric ratio just enough to dodge the check above
            # while still being (near-)nothing but the title with a short
            # author tag appended. Catch that shape specifically: bounded by
            # length (so a long body sentence that happens to quote the
            # title verbatim isn't caught — TITLE_CONTAINS_LEN_MULT keeps
            # this from firing on anything much longer than the title
            # itself) and by a near-exact containment of the title inside
            # the candidate (fuzz.partial_ratio, which a real section
            # heading like "2 MODELS OF RECURSIVE SELF-IMPROVEMENT" doesn't
            # clear at the 95 bar, even though it's title-adjacent text).
            return (len(cand_norm) <= TITLE_CONTAINS_LEN_MULT * len(title_norm) and
                    fuzz.partial_ratio(title_norm, cand_norm) >= TITLE_CONTAINS_THRESHOLD)

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
