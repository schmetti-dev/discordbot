"""
Tests für die DNB-Abfrage und die Reihenfolge der Quellen

Die Katalogdaten unten stammen aus den DNB-Einträgen der beiden Ausgaben
(Katalogdaten der DNB stehen unter CC0). Kein echtes Netzwerk.
"""

import httpx
import pytest

from cogs.books import build_author_card, build_book_card
from services import bookinfo
from services.dnb import blurb_to_text, fetch_book_from_dnb, parse_record

HEAD = '<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/"><records><record><recordData>'
TAIL = "</recordData></record></records></searchRetrieveResponse>"


def marc(*fields: str, idn: str = "1024616401") -> str:
    body = "".join(fields)
    return (
        f'{HEAD}<record xmlns="http://www.loc.gov/MARC21/slim" type="Bibliographic">'
        f'<controlfield tag="001">{idn}</controlfield>{body}</record>{TAIL}'
    )


def field(tag: str, **subfields: str) -> str:
    inner = "".join(f'<subfield code="{code}">{value}</subfield>' for code, value in subfields.items())
    return f'<datafield tag="{tag}" ind1=" " ind2=" ">{inner}</datafield>'


def link(url: str, label: str) -> str:
    return f'<datafield tag="856" ind1="4" ind2="2"><subfield code="u">{url}</subfield><subfield code="3">{label}</subfield></datafield>'


EBOOK = marc(
    field("020", a="9783492954525", **{"9": "978-3-492-95452-5"}),
    field("100", a="Schwartz, Richard", d="1958-"),
    # So liefert die DNB den Titel: das Artikelwort zwischen U+0098 und U+009C.
    field("245", a="\u0098Das\u009c Erste Horn", b="Das Geheimnis von Askir 1", c="Richard Schwartz"),
    field("264", a="München", b="Piper ebooks", c="2011"),
    field("300", a="Online-Ressource"),
    field("655", a="Fantasy"),
    link("https://services.dnb.de/plus/idn/1024616401/blurb/", "Inhaltstext"),
)

PAPERBACK = marc(
    field("020", a="9783492268172", **{"9": "978-3-492-26817-2"}),
    field("100", a="Schwartz, Richard"),
    field("245", a="Das Geheimnis von Askir", n="1.", p="Das erste Horn", c="Richard Schwartz"),
    field("264", a="München", b="Piper", c="2011"),
    field("300", a="397 S."),
    idn="1009999999",
)

EMPTY = '<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/"><numberOfRecords>0</numberOfRecords></searchRetrieveResponse>'


def test_parse_ebook_record():
    book = parse_record(EBOOK)
    assert book["title"] == "Das Erste Horn"
    assert book["subtitle"] == "Das Geheimnis von Askir 1"
    assert book["author"] == "Richard Schwartz"
    assert book["publisher"] == "Piper ebooks"
    assert book["year"] == "2011"
    assert book["genre"] == "Fantasy"
    assert book["total_pages"] is None  # E-Book: "Online-Ressource", keine Seitenzahl erfunden
    assert book["isbn_display"] == "978-3-492-95452-5"
    assert book["record_url"] == "https://d-nb.info/1024616401"
    assert book["blurb_url"].endswith("/blurb/")


def test_parse_series_volume_takes_the_volume_title():
    book = parse_record(PAPERBACK)
    assert book["title"] == "Das erste Horn"
    assert book["subtitle"] == "Das Geheimnis von Askir 1"
    assert book["total_pages"] == 397
    assert book["genre"] is None


def test_parse_no_record():
    assert parse_record(EMPTY) is None


def test_blurb_to_text():
    page = "<html><head><style>p{}</style></head><body><p>Ein verschneiter Gasthof &raquo;Zum Hammerkopf&laquo;.</p><p>Zweiter Absatz.</p></body></html>"
    assert blurb_to_text(page) == "Ein verschneiter Gasthof »Zum Hammerkopf«.\n\nZweiter Absatz."


def patch_client(monkeypatch, routes: dict):
    """Jede URL, die einen Schlüssel aus `routes` enthält, bekommt dessen Antwort."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        for pattern, response in routes.items():
            if pattern in url:
                return response() if callable(response) else response
        return httpx.Response(404, text="not found")

    class Client(httpx.AsyncClient):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(handler), follow_redirects=True)

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    return calls


async def test_fetch_from_dnb_with_blurb_and_cover(monkeypatch):
    patch_client(monkeypatch, {
        "sru/dnb": httpx.Response(200, text=EBOOK),
        "/blurb/": httpx.Response(200, text="<p>Ein verschneiter Gasthof.</p>"),
        "mvb/cover": httpx.Response(200, content=b"\xff\xd8", headers={"content-type": "image/jpeg"}),
    })
    book = await fetch_book_from_dnb("978-3-492-95452-5")
    assert book["isbn"] == "9783492954525"
    assert book["description"] == "Ein verschneiter Gasthof."
    assert book["cover_url"] == "https://portal.dnb.de/opac/mvb/cover?isbn=9783492954525"
    assert "blurb_url" not in book


async def test_fetch_from_dnb_without_cover(monkeypatch):
    patch_client(monkeypatch, {
        "sru/dnb": httpx.Response(200, text=EBOOK),
        "mvb/cover": httpx.Response(200, text="<html>kein Bild</html>", headers={"content-type": "text/html"}),
    })
    book = await fetch_book_from_dnb("9783492954525")
    assert book["cover_url"] is None
    assert book["description"] is None


async def test_fetch_from_dnb_unknown_isbn(monkeypatch):
    patch_client(monkeypatch, {"sru/dnb": httpx.Response(200, text=EMPTY)})
    assert await fetch_book_from_dnb("0000000000000") is None


# ── Reihenfolge der Quellen ───────────────────────────────────────────────────

async def test_dnb_only_when_openlibrary_does_not_know_the_book(monkeypatch):
    calls = patch_client(monkeypatch, {
        "openlibrary.org/isbn/": httpx.Response(404),
        "sru/dnb": httpx.Response(200, text=EBOOK),
    })
    book = await bookinfo.fetch_book("9783492954525")
    assert book["title"] == "Das Erste Horn"
    assert any("openlibrary.org" in url for url in calls) and any("sru/dnb" in url for url in calls)


async def test_dnb_when_openlibrary_is_down(monkeypatch):
    patch_client(monkeypatch, {
        "openlibrary.org/isbn/": httpx.Response(503),
        "sru/dnb": httpx.Response(200, text=EBOOK),
    })
    assert (await bookinfo.fetch_book("9783492954525"))["title"] == "Das Erste Horn"


async def test_openlibrary_hit_does_not_ask_the_dnb(monkeypatch):
    calls = patch_client(monkeypatch, {
        "openlibrary.org/isbn/": httpx.Response(200, json={"title": "Der Schwarm", "number_of_pages": 987}),
    })
    assert (await bookinfo.fetch_book("9783453319875"))["title"] == "Der Schwarm"
    assert not any("sru/dnb" in url for url in calls)


async def test_both_down_means_not_found(monkeypatch):
    patch_client(monkeypatch, {"openlibrary.org": httpx.Response(503), "sru/dnb": httpx.Response(503)})
    assert await bookinfo.fetch_book("9783492954525") is None


# ── Buchkarte ─────────────────────────────────────────────────────────────────

def test_book_card_has_the_fields_of_the_old_cards():
    book = {**parse_record(EBOOK), "isbn": "9783492954525", "description": "Klappentext."}
    card = build_book_card(book, pages="397 (Taschenbuch)", published="2011 (E-Book)")
    assert card.title == "Das Erste Horn\nDas Geheimnis von Askir 1"
    assert card.author.name == "Richard Schwartz"
    assert card.description == "Klappentext."
    assert [(f.name, f.value) for f in card.fields] == [
        ("Genre", "Fantasy"),
        ("Seiten", "397 (Taschenbuch)"),
        ("Erscheinungsdatum", "2011 (E-Book)"),
        ("ISBN", "978-3-492-95452-5"),
        ("Verlag", "Piper ebooks"),
    ]
    assert card.url == "https://d-nb.info/1024616401"


def test_book_card_leaves_out_what_it_does_not_know():
    card = build_book_card({"title": "Nur ein Titel", "isbn": "123"})
    assert [f.name for f in card.fields] == ["ISBN"]
    assert card.description is None


def test_author_card():
    card = build_author_card("Richard Schwartz", "Geboren 1958.")
    assert (card.title, card.author.name, card.description) == ("Richard Schwartz", "Autor", "Geboren 1958.")
