from pathlib import Path
from .config import settings

def describe_book_from_folder(folder: Path) -> dict:
    # TODO: integrar OpenAI Vision (usar settings.OPENAI_API_KEY)
    # Por agora, devolve placeholders.
    title = folder.name.replace("_", " ").title()
    price = max(settings.PRICE_MIN, 5) + settings.PRICE_MARGIN_EUR
    description_pt = (
        f"TÍTULO: {title}\nPreço: {price:.0f}€\n\n"
        "Livro em bom estado.\n"
        f"Entrega em mão na {settings.VINTED_LOCATION}, senão {settings.VINTED_SHIPPING}.\n"
        "Tenho outros livros à venda; ao comprar mais, paga apenas uma vez o transporte."
    )
    return {
        "title": title,
        "author": None,
        "isbn": None,
        "genre": None,
        "price": round(price, 2),
        "description": description_pt
    }
