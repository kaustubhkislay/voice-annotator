import httpx, json
from annotator.llm import LLMClient

def make(capture):
    def handler(req):
        capture.append(json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "answer"}}]})
    return LLMClient(api_key="k", transport=httpx.MockTransport(handler))

def test_ask_includes_focus_and_question():
    sent = []
    out = make(sent).ask("what is X", article_text="ARTICLE", note_md="NOTES", focus="the focus passage")
    assert out == "answer"
    body = json.dumps(sent[0])
    assert "what is X" in body and "the focus passage" in body and "ARTICLE" in body

def test_quiz_first_turn_has_no_user_msgs():
    sent = []
    make(sent).quiz_turn([], note_md="NOTES")
    roles = [m["role"] for m in sent[0]["messages"]]
    assert "user" in roles  # the kickoff instruction counts as user content

def test_truncation():
    sent = []
    make(sent).consolidate("N", article_text="x" * 100_000)
    assert len(json.dumps(sent[0])) < 80_000
