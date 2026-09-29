"""
Deutsche Nationalbibliothek als zweite Quelle für Buchdaten

OpenLibrary kennt viele deutsche Ausgaben nicht, besonders E-Books. Die DNB
katalogisiert jede in Deutschland erschienene Ausgabe und hat eine freie
Schnittstelle ohne Schlüssel (SRU): https://www.dnb.de/sru

Gelesen wird das MARC21-Format, weil Titel, Band, Seitenzahl und Verlag dort
in eigenen Feldern stehen und nicht aus einem Satz herausgeschnitten werden
müssen.
"""

import html
import logging
import re
import xml.etree.ElementTree as ET

import httpx

log = logging.getLogger("buchclub.dnb")

SRU_URL = "https://services.dnb.de/sru/dnb"
COVER_URL = "https://portal.dnb.de/opac/mvb/cover?isbn={isbn}"
RECORD_URL = "https://d-nb.info/{idn}"
NS = {"m": "http://www.loc.gov/MARC21/slim"}

# MARC klammert Wörter, die beim Sortieren übersprungen werden ("Das", "Der"),
# mit Steuerzeichen ein: U+0098 davor, U+009C danach. Auf dem Bildschirm sind
# sie Müll. U+0088/U+0089 sind dieselben Zeichen in einer älteren Kodierung.
NON_SORT = str.maketrans("", "", "\u0098\u009c\u0088\u0089")


def _subfields(record: ET.Element, tag: str, code: str) -> list[str]:
    values = (
        (sub.text or "").translate(NON_SORT).strip()
        for field in record.findall(f"m:datafield[@tag='{tag}']", NS)
        for sub in field.findall(f"m:subfield[@code='{code}']", NS)
    )
    return [value for value in values if value]


def _first(record: ET.Element, tag: str, code: str) -> str | None:
    values = _subfields(record, tag, code)
    return values[0] if values else None


def _person(name: str | None) -> str | None:
    """'Schwartz, Richard' wird zu 'Richard Schwartz'."""
    if not name:
        return None
    last, _, first = name.partition(",")
    return f"{first.strip()} {last.strip()}".strip() if first else name.strip()


def _clean(text: str | None) -> str | None:
    """Katalogtitel tragen Satzzeichen am Ende ('Das erste Horn /')."""
    if not text:
        return None
    return re.sub(r"\s*[/:;,.]\s*$", "", text).strip() or None


def parse_record(xml_text: str) -> dict | None:
    """Ersten Treffer einer SRU-Antwort in das Buch-Format des Bots übersetzen."""
    root = ET.fromstring(xml_text)
    record = root.find(".//m:record", NS)
    if record is None:
        return None

    # Bände einer Reihe: 245 $a ist die Reihe, $n die Nummer, $p der Bandtitel.
    part_title = _clean(_first(record, "245", "p"))
    main_title = _clean(_first(record, "245", "a"))
    if part_title:
        title = part_title
        subtitle = " ".join(filter(None, [main_title, _clean(_first(record, "245", "n"))]))
    else:
        title = main_title
        subtitle = _clean(_first(record, "245", "b"))
    if not title:
        return None

    pages = None
    extent = _first(record, "300", "a") or ""
    match = re.search(r"(\d+)\s*(S\.|Seiten)", extent)
    if match:
        pages = int(match.group(1))

    year = None
    date = _first(record, "264", "c") or _first(record, "260", "c")
    if date and (found := re.search(r"\d{4}", date)):
        year = found.group(0)

    blurb_url = None
    for field in record.findall("m:datafield[@tag='856']", NS):
        label = field.find("m:subfield[@code='3']", NS)
        link = field.find("m:subfield[@code='u']", NS)
        if label is not None and link is not None and (label.text or "").strip() == "Inhaltstext":
            blurb_url = (link.text or "").strip()

    idn = (record.findtext("m:controlfield[@tag='001']", default="", namespaces=NS) or "").strip()
    return {
        "title": title,
        "subtitle": subtitle or None,
        "author": _person(_first(record, "100", "a")),
        "publisher": _first(record, "264", "b") or _first(record, "260", "b"),
        "year": year,
        "genre": _first(record, "655", "a"),
        "total_pages": pages,
        "isbn_display": _first(record, "020", "9"),
        "record_url": RECORD_URL.format(idn=idn) if idn else None,
        "blurb_url": blurb_url,
    }


def blurb_to_text(page: str) -> str | None:
    """Den Inhaltstext der DNB (eine kleine HTML-Seite) in reinen Text wandeln."""
    text = re.sub(r"<(br|p|/p|div|/div)[^>]*>", "\n", page, flags=re.IGNORECASE)
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return text or None


async def fetch_book_from_dnb(isbn: str) -> dict | None:
    """
    Buchinfos von der DNB holen.

    Returns:
        dict im Format von fetch_book_by_isbn (isbn, title, author, description,
        cover_url, total_pages) plus subtitle, publisher, year, genre,
        isbn_display und record_url, oder None wenn die DNB die ISBN nicht kennt.
    """
    isbn = isbn.replace("-", "").replace(" ", "")
    params = {
        "version": "1.1",
        "operation": "searchRetrieve",
        "query": f"num={isbn}",
        "recordSchema": "MARC21-xml",
        "maximumRecords": "1",
    }
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        resp = await client.get(SRU_URL, params=params)
        resp.raise_for_status()
        book = parse_record(resp.text)
        if not book:
            return None

        description = None
        if book["blurb_url"]:
            blurb = await client.get(book["blurb_url"])
            if blurb.status_code == 200:
                description = blurb_to_text(blurb.text)

        cover_url = COVER_URL.format(isbn=isbn)
        cover = await client.get(cover_url)
        if cover.status_code != 200 or not cover.headers.get("content-type", "").startswith("image/"):
            cover_url = None

    book.pop("blurb_url")
    return {"isbn": isbn, "description": description, "cover_url": cover_url, **book}
