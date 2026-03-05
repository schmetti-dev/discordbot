"""
OpenLibrary API Client

Holt Buchmetadaten (Titel, Autor, Beschreibung, Cover) anhand einer ISBN.
API-Dokumentation: https://openlibrary.org/developers/api
"""

import httpx


OPENLIBRARY_BASE = "https://openlibrary.org"
COVERS_BASE = "https://covers.openlibrary.org"


async def fetch_book_by_isbn(isbn: str) -> dict | None:
    """
    Buchinfos von OpenLibrary abrufen.

    Returns:
        dict mit isbn, title, author, description, cover_url, total_pages
        oder None wenn das Buch nicht gefunden wurde.
    """
    # ISBN normalisieren (Bindestriche und Leerzeichen entfernen)
    isbn = isbn.replace("-", "").replace(" ", "")

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Schritt 1: Buch-Edition via ISBN API laden
        resp = await client.get(
            f"{OPENLIBRARY_BASE}/isbn/{isbn}.json"
        )

        if resp.status_code == 404:
            return None
        resp.raise_for_status()

        edition = resp.json()

        # Schritt 2: Work-Infos laden (für Beschreibung)
        description = None
        works = edition.get("works", [])
        if works:
            work_key = works[0]["key"]  # z.B. "/works/OL12345W"
            work_resp = await client.get(f"{OPENLIBRARY_BASE}{work_key}.json")
            if work_resp.status_code == 200:
                work = work_resp.json()
                desc = work.get("description")
                if isinstance(desc, dict):
                    description = desc.get("value")
                elif isinstance(desc, str):
                    description = desc

        # Schritt 3: Autor-Namen auflösen
        author = None
        authors = edition.get("authors", [])
        if authors:
            author_key = authors[0]["key"]
            author_resp = await client.get(f"{OPENLIBRARY_BASE}{author_key}.json")
            if author_resp.status_code == 200:
                author_data = author_resp.json()
                author = author_data.get("name") or author_data.get("personal_name")

        # Cover-URL zusammenbauen (Large)
        cover_url = None
        covers = edition.get("covers", [])
        if covers:
            cover_id = covers[0]
            cover_url = f"{COVERS_BASE}/b/id/{cover_id}-L.jpg"

        return {
            "isbn": isbn,
            "title": edition.get("title", "Unbekannter Titel"),
            "author": author,
            "description": description,
            "cover_url": cover_url,
            "total_pages": edition.get("number_of_pages"),
        }
