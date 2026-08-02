from annotator.grammar import parse_utterance as p


def test_plain_text_is_highlight():
    c = p("Control evaluations bound the risk of scheming models.")
    assert c.kind == "highlight" and c.text.startswith("Control evaluations")


def test_bare_note_is_pending():
    assert p("Note.").kind == "note_pending"


def test_note_with_content():
    c = p("note this contradicts the earlier claim")
    assert c.kind == "note" and c.text == "this contradicts the earlier claim"


def test_ask():
    c = p("Ask what does deference mean here?")
    assert c.kind == "ask" and c.text == "what does deference mean here?"


def test_control_words():
    assert p("undo").kind == "undo"
    assert p("Retry").kind == "retry"
    assert p("finished.").kind == "finished"
    assert p("end quiz").kind == "end_quiz"


def test_note_mid_sentence_is_highlight():
    assert p("We note that the model defects").kind == "highlight"
