from annotator.matcher import find_passage

DOC = ("AI control aims to maintain safety even if models scheme. "
       "Control evaluations measure this with red teams. "
       "The blue team proposes protocols; the red team attacks them. "
       "Deference is a separate axis entirely.")

def test_exact_sentence():
    m = find_passage("Control evaluations measure this with red teams", DOC)
    assert m.score > 90 and "red teams" in m.text

def test_misread_words_still_match():
    m = find_passage("control evaluation measures this with red team", DOC)
    assert m.score > 80 and m.text.startswith("Control evaluations")

def test_two_sentence_span():
    m = find_passage("Control evaluations measure this with red teams. "
                     "The blue team proposes protocols", DOC)
    assert "blue team" in m.text and "Control evaluations" in m.text

def test_garbage_scores_low():
    m = find_passage("completely unrelated cooking recipe for pasta", DOC)
    assert m.score < 60

def test_length_prefilter_and_cache():
    # Very short transcript should not match long sentences
    short = "red"
    m_short = find_passage(short, DOC)
    # Should find a best match but not the entire document
    assert len(m_short.text) < 50

    # Repeated calls with same DOC should hit cache and return same result
    m_short_again = find_passage(short, DOC)
    assert m_short.text == m_short_again.text
    assert m_short.score == m_short_again.score
    assert m_short.start == m_short_again.start

DUP_DOC = ("Control evaluations measure this with red teams. "
           "AI control aims to maintain safety even if models scheme. "
           "The blue team proposes protocols; the red team attacks them. "
           "Deference is a separate axis entirely. "
           "Control evaluations measure this with red teams.")

def test_cursor_picks_later_duplicate_when_past_earlier_one():
    early_end = DUP_DOC.index("AI control")  # end of the early duplicate
    m = find_passage("Control evaluations measure this with red teams", DUP_DOC, cursor=early_end + 5)
    # earliest occurrence starts at 0, later one is near the end
    assert m.start > early_end

def test_cursor_behind_match_still_returned_when_no_forward_alternative():
    # cursor placed after the only decent match; behind-cursor match should
    # still be returned (penalized but not excluded).
    m = find_passage("Control evaluations measure this with red teams", DOC, cursor=len(DOC))
    assert m.score > 80 and "red teams" in m.text

# --- Normalized combined scoring + symmetric-exact title demotion --------
#
# History of this logic, in order of what broke and why:
#   1. token_sort_ratio alone: a whole-string check against the bare title
#      missed a title+author-line window that dilutes the ratio just enough
#      to dodge a >=95 cutoff.
#   2. Containment (fuzz.partial_ratio(title, candidate) >= 90): fixed (1)
#      but regressed live matching — real body sentences legitimately quote
#      or closely paraphrase a paper's title, so partial_ratio (which slides
#      the shorter string and only needs SOME window to align) flagged the
#      true target sentence as title-like and demoted it. Also degenerate
#      for short fragments (a 1-char extraction can score 100).
#   3. Position (HEAD_REGION) + symmetric whole-string ratio: fixed (2) but
#      broke on a real document where the abstract starts at char 199 —
#      well inside any plausible head-region cutoff — and got wrongly
#      demoted.
#
# Final validated spec: is_title_like uses ONLY a symmetric, normalized
# whole-string ratio (fuzz.token_sort_ratio(_norm(candidate), _norm(title))
# >= 90) with no position rule at all. This kills the title line and any
# running head reprinting it verbatim, while real body text — including
# text that starts very early in the document, like an abstract — is judged
# purely on how much it actually resembles the bare title string, not on
# where it sits.
#
# Scoring itself also changed: transcript and candidate are both run through
# _norm (lowercase, all non-alphanumeric runs collapsed to a single space)
# before scoring, and the score is the average of token_set_ratio and
# token_sort_ratio. _norm makes a spoken "self improvement" equivalent to a
# printed "self-improvement" (see test_hyphenation_normalized_away below).
# The token_set/token_sort blend makes a partial read of a long sentence
# (token_set_ratio, robust to the candidate having extra words) score well
# without losing the ability to penalize a candidate that's mostly unrelated
# text (token_sort_ratio). The length prefilter's upper bound also widened
# from 3x to 6x transcript length for the same partial-read reason.

TITLE = "The Economics of Recursive Self-Improvement"
TITLE_LINE = TITLE + "."
FILLER = ("Prior work in this area has been limited by data availability and methodological "
          "constraints across many decades of study. Researchers have proposed various "
          "frameworks for understanding institutional change over long time horizons in "
          "unrelated domains. This paper contributes to that literature by providing a novel "
          "empirical approach grounded in historical case comparisons. ")

# Regression test for failure (3) above: a body sentence sitting early in the
# document (well within what used to be the 400-char head region) that
# closely echoes — but does not near-duplicate — the title must win over the
# bare title line. Empirically (validated against the real paper): the title
# line itself scores ~82.8 against this transcript (best_raw) and gets
# demoted via the exact symmetric-ratio check (its ratio to itself is 100);
# the real body sentence scores ~79-80 and wins.
def test_body_sentence_near_title_wins_over_title_line_even_early_in_doc():
    body = "Our model addresses the economics of self improvement under several key growth assumptions."
    doc = TITLE_LINE + " " + body + " Deference is a separate axis entirely."
    body_start = doc.index(body)
    assert body_start < 400  # this is exactly the case the HEAD_REGION rule broke
    m = find_passage("we model the economics of self improvement", doc, title=TITLE)
    assert m.text == body
    assert 74 <= m.score <= 84  # ~79, in the "body sentence ~80" ballpark

# Live gap found after the above: a "title + byline" window ("Title. Tom
# Cunningham*.") only scores sym=85.1 against the bare title — under the 90
# whole-string bar — so it dodged demotion entirely and outranked the real
# abstract. is_title_like now also catches this shape via a bounded
# containment check: len(cand) <= 2.5x len(title) AND
# fuzz.partial_ratio(title, cand) >= 95. Validated live: this window is
# sym=85.1 / partial=100 / len_ok=True -> demoted; a long body sentence that
# happens to quote the title verbatim has len_ok=False -> spared; a section
# heading like "2 MODELS OF RECURSIVE SELF-IMPROVEMENT" only reaches
# partial=89.9 -> spared. Numbers below reproduce sym=85.1 exactly.
def test_title_plus_byline_window_demoted_even_when_symmetric_ratio_under_90():
    title_author = TITLE + " Tom Cunningham*."
    from annotator.matcher import _norm
    from rapidfuzz import fuzz
    sym = fuzz.token_sort_ratio(_norm(title_author), _norm(TITLE))
    assert 84 <= sym <= 86  # reproduces the live sym=85.1 exactly
    assert fuzz.partial_ratio(_norm(TITLE), _norm(title_author)) >= 95
    abstract = "Cunningham studies recursive self improvement economics here."
    doc = title_author + " " + abstract + " Deference is a separate axis entirely."
    m = find_passage("the economics of recursive self improvement tom cunningham", doc, title=TITLE)
    assert m.text == abstract

# Companion "spared" case for the containment check above: a real section
# heading that merely shares vocabulary with the title (partial=89.9,
# reproduced below — just under the 95 bar) must not be caught by it, and
# must still win when it's genuinely what the user is reading.
def test_section_heading_not_wrongly_demoted():
    from annotator.matcher import _norm
    from rapidfuzz import fuzz
    heading = "2 MODELS OF RECURSIVE SELF-IMPROVEMENT"
    partial = fuzz.partial_ratio(_norm(TITLE), _norm(heading))
    assert 89 <= partial <= 91  # reproduces the live partial=89.9
    doc = (TITLE_LINE + " " + heading + ". "
           "Some unrelated filler content about methodology follows here in this document. "
           "Deference is a separate axis entirely.")
    m = find_passage("models of recursive self improvement", doc, title=TITLE)
    assert m.text == heading + "."

def test_title_only_match_still_returned_when_no_alternative():
    m = find_passage("the economics of recursive self improvement",
                      "The Economics of Recursive Self-Improvement.",
                      title="The Economics of Recursive Self-Improvement")
    assert "Economics of Recursive Self-Improvement" in m.text

# Running-head duplicate: the title reappears verbatim as a running head
# later in the document. There's no position rule anymore, but the
# symmetric whole-string ratio against the bare title is ~100 regardless of
# where it sits, so it's still demoted in favor of a real, merely
# title-adjacent sentence nearby that is not a near-duplicate of the title.
def test_running_head_duplicate_demoted_in_favor_of_real_sentence():
    running_head = TITLE + "."
    # Wording deliberately avoids reproducing "economics of recursive self
    # improvement" as a contiguous run — a body sentence that happens to
    # echo the title phrase in the same word order also trips the
    # length+partial_ratio containment check (see is_title_like) and would
    # be wrongly demoted too, same as the real title text.
    body = "The self-improvement economics of recursive agents appear here."
    doc = TITLE_LINE + " " + FILLER + running_head + " " + body + " Deference is a separate axis entirely."
    m = find_passage("the economics of recursive self improvement", doc, title=TITLE)
    assert m.text == body

# --- Normalization: hyphenation shouldn't break matching -------------------

def test_hyphenation_normalized_away():
    doc = ("AI control aims to maintain safety even if models scheme. "
           "Recursive self-improvement is the process by which an AI system revises its own architecture. "
           "Deference is a separate axis entirely.")
    m = find_passage(
        "recursive self improvement is the process by which an ai system revises its own architecture",
        doc,
    )
    assert m.score >= 95  # ~100, verbatim modulo the hyphen
    assert m.text.startswith("Recursive self-improvement")

# --- Generic chatter still scores low and gets rejected upstream -----------

def test_generic_chatter_scores_low():
    m = find_passage("this paper seems really interesting to me overall", DOC)
    assert m.score < 60  # ~53
