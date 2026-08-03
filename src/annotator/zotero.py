import httpx


class ZoteroError(Exception):
    pass


class ZoteroClient:
    def __init__(self, base: str = "http://localhost:23119", transport=None):
        self.base = base
        self.http = httpx.Client(transport=transport, timeout=10.0)

    def _req(self, method: str, path: str, **kw):
        try:
            r = self.http.request(method, self.base + path, **kw)
        except httpx.TransportError as e:
            raise ZoteroError(f"Cannot reach Zotero ({e}). Is Zotero running?") from e
        if r.status_code != 200:
            raise ZoteroError(f"Zotero returned {r.status_code} for {path}: {r.text[:200]}")
        return r

    def _parse_json(self, response, path: str, expected_key=None):
        try:
            data = response.json()
        except (ValueError, httpx.ResponseNotRead) as e:
            raise ZoteroError(f"Unexpected response from Zotero at {path}: invalid JSON - {e}") from e
        if expected_key:
            try:
                return data[expected_key]
            except KeyError as e:
                raise ZoteroError(f"Unexpected response from Zotero at {path}: missing key '{expected_key}'") from e
        return data

    def current_item(self) -> dict:
        r = self._req("GET", "/voiceannotator/current")
        return self._parse_json(r, "/voiceannotator/current")

    def fulltext(self, key: str) -> str:
        # Served by the bridge plugin, not Zotero's read API: that API is off by
        # default and expects the attachment key, not the key /current returns.
        # The key is sent only so the plugin can check we mean the open item.
        r = self._req("GET", "/voiceannotator/fulltext", params={"key": key})
        return self._parse_json(r, "/voiceannotator/fulltext", expected_key="content")

    def create_highlight(self, text: str, comment: str = "", key: str | None = None) -> str:
        body = {"text": text, "comment": comment}
        if key is not None:
            body["key"] = key
        r = self._req("POST", "/voiceannotator/highlight", json=body)
        return self._parse_json(r, "/voiceannotator/highlight", expected_key="annotationKey")

    def delete_annotation(self, key: str) -> None:
        self._req("POST", "/voiceannotator/delete", json={"key": key})

    def add_comment(self, key: str, comment: str) -> None:
        self._req("POST", "/voiceannotator/comment", json={"key": key, "comment": comment})
