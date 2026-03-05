"""
Tests für den OpenLibrary API Client (services/openlibrary.py)

Nutzt httpx's eingebautes MockTransport — kein echtes Netzwerk nötig.
"""

import pytest
import httpx
import json

from services.openlibrary import fetch_book_by_isbn


def _make_transport(responses: dict[str, dict]) -> httpx.MockTransport:
    """
    Hilfsfunktion: Erstellt ein Mock-Transport das für jede URL
    eine vordefinierte JSON-Antwort zurückgibt.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for pattern, data in responses.items():
            if pattern in url:
                return httpx.Response(200, json=data)
        return httpx.Response(404, json={"error": "not found"})

    return httpx.MockTransport(handler)


# Minimal-Fixtures für API-Responses
EDITION_RESPONSE = {
    "title": "Der Schwarm",
    "number_of_pages": 987,
    "covers": [12345],
    "works": [{"key": "/works/OL123W"}],
    "authors": [{"key": "/authors/OL456A"}],
}

WORK_RESPONSE = {
    "description": {"value": "Ein fesselnder Meeresthriller."},
    # Autor sitzt im Work mit tieferem Nesting: authors[i]["author"]["key"]
    "authors": [{"author": {"key": "/authors/OL456A"}}],
}

AUTHOR_RESPONSE = {
    "name": "Frank Schätzing"
}


async def test_fetch_book_success(monkeypatch):
    """Erfolgreicher API-Aufruf gibt korrektes dict zurück."""
    transport = _make_transport({
        "/isbn/": EDITION_RESPONSE,
        "/works/": WORK_RESPONSE,
        "/authors/": AUTHOR_RESPONSE,
    })

    async def mock_client(*args, **kwargs):
        return httpx.AsyncClient(transport=transport)

    # httpx.AsyncClient mit Mock-Transport patchen
    import httpx as httpx_module
    original = httpx_module.AsyncClient

    class PatchedClient(httpx_module.AsyncClient):
        def __init__(self, **kwargs):
            super().__init__(transport=transport)

    monkeypatch.setattr(httpx_module, "AsyncClient", PatchedClient)

    result = await fetch_book_by_isbn("9783453319875")

    assert result is not None
    assert result["title"] == "Der Schwarm"
    assert result["author"] == "Frank Schätzing"
    assert result["description"] == "Ein fesselnder Meeresthriller."
    assert result["total_pages"] == 987
    assert "covers.openlibrary.org" in result["cover_url"]


async def test_fetch_book_isbn_normalization(monkeypatch):
    """ISBN mit Bindestrichen wird normalisiert."""
    called_urls = []

    class TrackingClient(httpx.AsyncClient):
        def __init__(self, **kwargs):
            super().__init__(transport=_make_transport({
                "/isbn/9783453319875": EDITION_RESPONSE,
                "/works/": WORK_RESPONSE,
                "/authors/": AUTHOR_RESPONSE,
            }))

        async def get(self, url, **kwargs):
            called_urls.append(url)
            return await super().get(url, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", TrackingClient)

    await fetch_book_by_isbn("978-3-453-31987-5")

    # Normalisierte ISBN ohne Bindestriche muss im URL auftauchen
    assert any("9783453319875" in u for u in called_urls)


async def test_fetch_book_not_found(monkeypatch):
    """404 von OpenLibrary → None zurückgeben."""
    class NotFoundClient(httpx.AsyncClient):
        def __init__(self, **kwargs):
            super().__init__(transport=_make_transport({}))  # alles → 404

    monkeypatch.setattr(httpx, "AsyncClient", NotFoundClient)

    result = await fetch_book_by_isbn("0000000000000")
    assert result is None
