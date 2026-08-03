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

# --- Position-based title demotion ---------------------------------------
#
# A containment check (fuzz.partial_ratio(title, candidate) >= 90) was tried
# first and regressed live matching: real body sentences legitimately quote
# or closely paraphrase a paper's title (e.g. "We model the economics of
# recursive self-improvement (RSI)..."), so partial_ratio — which slides the
# shorter string and only needs SOME window in the candidate to align with
# the title — flagged the true target sentence as title-like and demoted it,
# letting a garbage match win instead. partial_ratio is also degenerate for
# short fragments (a 1-char extraction can score 100 against any title).
#
# The fix instead uses two independent, non-containment signals:
#   1. Position: title/byline text lives in the document's head region
#      (HEAD_REGION chars). A candidate starting there is presumptively a
#      title/author-line read regardless of wording.
#   2. Exact match: a SYMMETRIC whole-string ratio (both sides diluted by
#      any extra words) catches a running head that reprints the title
#      verbatim later in the document, while a body sentence that merely
#      echoes title vocabulary — without being a near-duplicate of the
#      whole string — scores low on both sides and is not flagged.

TITLE = "The Economics of Recursive Self-Improvement"
TITLE_LINE = TITLE + "."
FILLER = ("Prior work in this area has been limited by data availability and methodological "
          "constraints across many decades of study. Researchers have proposed various "
          "frameworks for understanding institutional change over long time horizons in "
          "unrelated domains. This paper contributes to that literature by providing a novel "
          "empirical approach grounded in historical case comparisons. ")
assert len(TITLE_LINE) + 1 + len(FILLER) > 400  # keeps what follows past HEAD_REGION

# Live failure (the exact regression the containment fix introduced): a body
# sentence past the head region verbatim-contains the title phrase. Under a
# containment check this false-flags as title-like and gets demoted in favor
# of a garbage match; under position + symmetric-ratio it correctly wins,
# since its position is past HEAD_REGION and its symmetric ratio against the
# bare title is diluted well below 90 by the extra words.
def test_body_sentence_quoting_title_wins_over_head_region_title_line():
    body = "We model the economics of recursive self-improvement using three assumptions."
    doc = TITLE_LINE + " " + FILLER + body + " Deference is a separate axis entirely."
    assert doc.index(body) >= 400
    m = find_passage("we model the economics of recursive self improvement", doc, title=TITLE)
    assert m.text.startswith("We model the economics of recursive self-improvement")

def test_title_only_match_still_returned_when_no_alternative():
    m = find_passage("the economics of recursive self improvement",
                      "The Economics of Recursive Self-Improvement.",
                      title="The Economics of Recursive Self-Improvement")
    assert "Economics of Recursive Self-Improvement" in m.text

# Head-region author-line window: a "title + author line" sentence (one
# combined sentence, since there's no period between title and author names)
# sits at the very start of the document, so the position signal alone flags
# it as title-like — no containment ratio needed.
TITLE_CONTAMINATED_DOC = (
    "The Economics of Recursive Self-Improvement by Nakamura and Osei-Bonsu. " + FILLER +
    "We study how recursive self improvement changes the economics of AI development over time. "
    "Deference is a separate axis entirely."
)

def test_head_region_author_line_window_demoted():
    body = "We study how recursive self improvement changes the economics of AI development over time."
    assert TITLE_CONTAMINATED_DOC.index(body) >= 400  # body is genuinely past the head region
    m = find_passage(
        "the economics of recursive self improvement by nakamura and osei bonsu",
        TITLE_CONTAMINATED_DOC,
        title="The Economics of Recursive Self-Improvement",
    )
    assert m.text.startswith("We study how recursive self improvement")

# Running-head duplicate: the title reappears verbatim as a page header at a
# mid-document offset (past HEAD_REGION), so position alone would not flag
# it — but the symmetric whole-string ratio against the bare title is ~100,
# so it is still demoted in favor of a real, merely title-adjacent sentence
# nearby that is not a near-duplicate of the title.
def test_running_head_duplicate_past_head_region_demoted():
    running_head = TITLE + "."
    body = "Our detailed study of the economics of recursive self improving systems follows."
    doc = TITLE_LINE + " " + FILLER + running_head + " " + body + " Deference is a separate axis entirely."
    running_head_offset = doc.index(running_head, len(TITLE_LINE) + 1)
    assert running_head_offset >= 400
    assert doc.index(body) >= 400
    m = find_passage("the economics of recursive self improvement", doc, title=TITLE)
    assert m.text.startswith("Our detailed study")
