"""
Buchdaten aus mehreren Quellen

Zuerst OpenLibrary, dann die Deutsche Nationalbibliothek. Ist OpenLibrary nicht
erreichbar, fragt der Bot trotzdem die DNB, statt das Buch als unbekannt zu
melden.
"""

import logging

import httpx

from services.dnb import fetch_book_from_dnb
from services.openlibrary import fetch_book_by_isbn

log = logging.getLogger("buchclub.bookinfo")


async def fetch_book(isbn: str) -> dict | None:
    try:
        book = await fetch_book_by_isbn(isbn)
        if book:
            return book
    except httpx.HTTPError as error:
        log.warning(f"OpenLibrary nicht erreichbar ({error.__class__.__name__}), frage die DNB.")

    try:
        return await fetch_book_from_dnb(isbn)
    except httpx.HTTPError as error:
        log.warning(f"DNB nicht erreichbar ({error.__class__.__name__}).")
        return None
