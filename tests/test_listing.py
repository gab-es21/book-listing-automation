from blt import listing
from blt.config import settings


def test_full_fields_produce_expected_description():
    fields = {"title": "Sempre Tu", "author": "Colleen Hoover", "isbn": "9789896689704"}

    desc = listing.compose_description(fields)

    assert desc == (
        "TÍTULO: Sempre Tu\n"
        "Autor(es): Colleen Hoover\n"
        "ISBN: 9789896689704\n"
        "\n"
        "Livro em bom estado.\n"
        "Tenho mais livros à venda."
    )


def test_missing_author_and_isbn_are_omitted_not_blank():
    fields = {"title": "Sempre Tu", "author": None, "isbn": None}

    desc = listing.compose_description(fields)

    assert "Autor(es)" not in desc
    assert "ISBN" not in desc
    assert desc.startswith("TÍTULO: Sempre Tu")


def test_missing_title_falls_back_to_placeholder():
    desc = listing.compose_description({"title": None, "author": None, "isbn": None})

    assert desc.startswith("TÍTULO: N/D")


def test_never_mentions_transport_shipping_or_negotiation():
    fields = {"title": "T", "author": "A", "isbn": "9789896689704"}

    desc = listing.compose_description(fields).lower()

    for banned in ["vinted", "transporte", "envio", "correio", "entrega", "negocia", "oferta", "desconto"]:
        assert banned not in desc, f"description should not mention '{banned}'"


def test_suggested_price_reads_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "BOOK_PRICE_EUR", 7.0)
    assert listing.suggested_price() == 7.0

    monkeypatch.setattr(settings, "BOOK_PRICE_EUR", 9.5)
    assert listing.suggested_price() == 9.5


def test_compose_listing_combines_description_and_price(monkeypatch):
    monkeypatch.setattr(settings, "BOOK_PRICE_EUR", 7.0)
    fields = {"title": "Sempre Tu", "author": "Colleen Hoover", "isbn": "9789896689704"}

    result = listing.compose_listing(fields)

    assert result["title"] == "Sempre Tu"
    assert result["price"] == 7.0
    assert "Sempre Tu" in result["description"]
