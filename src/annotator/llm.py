import httpx

DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
_MAX_ARTICLE = 60_000

class LLMClient:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, transport=None):
        self.model = model
        self.http = httpx.Client(
            transport=transport, timeout=120.0,
            headers={"Authorization": f"Bearer {api_key}"})

    def chat(self, messages: list[dict], system: str) -> str:
        r = self.http.post("https://openrouter.ai/api/v1/chat/completions", json={
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages]})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    def ask(self, question: str, article_text: str, note_md: str, focus: str) -> str:
        system = ("You answer a reader's question about an article they are reading. "
                  "Be direct and short. Ground answers in the article text.")
        user = (f"Article text:\n{article_text[:_MAX_ARTICLE]}\n\n"
                f"Reader's highlights and notes so far:\n{note_md}\n\n"
                f"The reader just highlighted: \"{focus}\"\n\n"
                f"Question: {question}")
        return self.chat([{"role": "user", "content": user}], system)

    def consolidate(self, note_md: str, article_text: str) -> str:
        system = ("Consolidate a reader's highlights and notes — NOT a generic paper summary. "
                  "Output markdown with three parts: a structured synthesis of what the reader "
                  "attended to, a short list of likely misunderstandings to check (grounded in "
                  "their notes vs the article), and 3-5 key follow-up questions.")
        user = f"Article text:\n{article_text[:_MAX_ARTICLE]}\n\nReading note:\n{note_md}"
        return self.chat([{"role": "user", "content": user}], system)

    def quiz_turn(self, history: list[dict], note_md: str) -> str:
        system = ("You quiz a reader on an article using their own highlights and notes. "
                  "Ask one question at a time. After each answer: grade it briefly, correct "
                  "if wrong, then ask the next question. Probe weak spots adaptively.")
        kickoff = {"role": "user", "content": f"Reading note:\n{note_md}\n\nBegin the quiz."}
        return self.chat([kickoff, *history], system)
