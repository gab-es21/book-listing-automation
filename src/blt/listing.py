"""
Turns extracted book fields ({title, author, isbn}) into a ready-to-paste PT
description and the price to use. Category/condition/language aren't
touched here - they're always the same and picked by hand in Vinted's UI.
Transport isn't mentioned either - Vinted handles shipping natively, no need
to describe delivery/shipping arrangements in the listing text. Negotiation
happens through Vinted's own offer feature, not spelled out in the text.
"""
from .config import settings


def compose_description(fields: dict) -> str:
    lines = [f"TÍTULO: {fields['title']}" if fields.get("title") else "TÍTULO: N/D"]
    if fields.get("author"):
        lines.append(f"Autor(es): {fields['author']}")
    if fields.get("isbn"):
        lines.append(f"ISBN: {fields['isbn']}")
    lines.append("")
    lines.append("Livro em bom estado.")
    lines.append("Tenho mais livros à venda.")
    return "\n".join(lines)


def suggested_price() -> float:
    return settings.BOOK_PRICE_EUR


def compose_listing(fields: dict) -> dict:
    """Combines both into what the Book row needs, on top of {title, author, isbn}."""
    return {**fields, "description": compose_description(fields), "price": suggested_price()}
