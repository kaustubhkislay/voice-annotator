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

TITLE_DOC = ("The Economics of Recursive Self-Improvement. "
             "We model the economics of recursive self-improvement using three assumptions. "
             "Deference is a separate axis entirely.")

def test_title_demotion_prefers_body_over_title():
    m = find_passage("we model the economics of recursive self improvement", TITLE_DOC,
                      title="The Economics of Recursive Self-Improvement")
    assert m.text.startswith("We model the economics")

def test_title_only_match_still_returned_when_no_alternative():
    m = find_passage("the economics of recursive self improvement",
                      "The Economics of Recursive Self-Improvement.",
                      title="The Economics of Recursive Self-Improvement")
    assert "Economics of Recursive Self-Improvement" in m.text
