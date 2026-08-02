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

    def current_item(self) -> dict:
        return self._req("GET", "/voiceannotator/current").json()

    def fulltext(self, key: str) -> str:
        return self._req("GET", f"/api/users/0/items/{key}/fulltext").json()["content"]

    def create_highlight(self, text: str, comment: str = "") -> str:
        r = self._req("POST", "/voiceannotator/highlight", json={"text": text, "comment": comment})
        return r.json()["annotationKey"]

    def delete_annotation(self, key: str) -> None:
        self._req("POST", "/voiceannotator/delete", json={"key": key})
