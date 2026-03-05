"""
OpenLibrary API Client

Holt Buchmetadaten (Titel, Autor, Beschreibung, Cover) anhand einer ISBN.
API-Dokumentation: https://openlibrary.org/developers/api

OpenLibrary-Besonderheiten:
- ISBN-URL leitet per 302 auf /books/OL...M.json weiter → follow_redirects=True
- Beschreibung steht in der Edition (nicht im Work): {"type": "...", "value": "..."}
- Autoren stehen im Work mit tieferem Nesting: authors[i]["author"]["key"]
"""

import httpx


OPENLIBRARY_BASE = "https://openlibrary.org"
COVERS_BASE = "https://covers.openlibrary.org"


def _extract_text(field) -> str | None:
    """OpenLibrary Text-Felder können str oder {"value": "..."} sein."""
    if isinstance(field, str):
        return field
    if isinstance(field, dict):
        return field.get("value")
    return None


async def fetch_book_by_isbn(isbn: str) -> dict | None:
    """
    Buchinfos von OpenLibrary abrufen.

    Returns:
        dict mit isbn, title, author, description, cover_url, total_pages
        oder None wenn das Buch nicht gefunden wurde.
    """
    isbn = isbn.replace("-", "").replace(" ", "")

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        # Schritt 1: Edition via ISBN laden (302-Redirect wird automatisch gefolgt)
        resp = await client.get(f"{OPENLIBRARY_BASE}/isbn/{isbn}.json")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        edition = resp.json()

        # Schritt 2: Beschreibung — zuerst in Edition suchen, dann im Work
        description = _extract_text(edition.get("description"))

        author = None
        works = edition.get("works", [])
        if works:
            work_key = works[0]["key"]
            work_resp = await client.get(f"{OPENLIBRARY_BASE}{work_key}.json")
            if work_resp.status_code == 200:
                work = work_resp.json()

                # Beschreibung aus Work nur als Fallback
                if not description:
                    description = _extract_text(work.get("description"))

                # Autor: Work hat authors[i]["author"]["key"] (nicht authors[i]["key"])
                work_authors = work.get("authors", [])
                if work_authors:
                    author_key = work_authors[0]["author"]["key"]
                    author_resp = await client.get(f"{OPENLIBRARY_BASE}{author_key}.json")
                    if author_resp.status_code == 200:
                        author_data = author_resp.json()
                        author = author_data.get("name") or author_data.get("personal_name")

        # Fallback: by_statement aus Edition (z.B. "von Frank Schätzing")
        if not author:
            author = edition.get("by_statement")

        # Cover-URL (Large)
        cover_url = None
        covers = edition.get("covers", [])
        if covers:
            cover_url = f"{COVERS_BASE}/b/id/{covers[0]}-L.jpg"

        return {
            "isbn": isbn,
            "title": edition.get("title", "Unbekannter Titel"),
            "author": author,
            "description": description,
            "cover_url": cover_url,
            "total_pages": edition.get("number_of_pages"),
        }
