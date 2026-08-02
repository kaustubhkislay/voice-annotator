import httpx
import json
import pytest
from annotator.zotero import ZoteroClient, ZoteroError


def make(handler):
    return ZoteroClient(transport=httpx.MockTransport(handler))


def test_current_and_fulltext_and_highlight():
    def handler(req):
        if req.url.path == "/voiceannotator/current":
            return httpx.Response(200, json={"key": "K1", "title": "T", "url": "u", "year": "2024", "firstCreator": "Greenblatt"})
        if req.url.path == "/api/users/0/items/K1/fulltext":
            return httpx.Response(200, json={"content": "full text here"})
        if req.url.path == "/voiceannotator/highlight":
            assert json.loads(req.content)["text"] == "passage"
            return httpx.Response(200, json={"annotationKey": "ANN1"})
        raise AssertionError(req.url.path)
    z = make(handler)
    assert z.current_item()["key"] == "K1"
    assert z.fulltext("K1") == "full text here"
    assert z.create_highlight("passage") == "ANN1"


def test_error_wraps():
    def handler(req):
        raise httpx.ConnectError("refused")
    with pytest.raises(ZoteroError, match="Is Zotero running"):
        make(handler).current_item()
