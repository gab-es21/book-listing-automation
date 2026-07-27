from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass

# status: pending (grouped, not yet reviewed/listed) -> available (listed on
# Vinted) -> sold_out, with a side branch to failed (extraction couldn't
# resolve a title via barcode+Almedina - needs manual entry before it can
# become available). Category/condition/language aren't tracked here - they
# never vary and are picked by hand in Vinted's own UI.
class Book(Base):
    __tablename__ = "books"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    isbn: Mapped[str | None] = mapped_column(String(32), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    folder_path: Mapped[str] = mapped_column(String(512), unique=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    # Set when "Passar por agora" is used (or, in DEV_MODE, on every Próximo
    # click, since nothing is ever consumed there): pushes the book behind
    # every never-skipped book, and behind any book skipped earlier than it -
    # a real FIFO carousel rather than a one-shot "show me the next one".
    skipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)


# One row per physical copy sold - snapshots title/isbn/price at the moment
# of sale rather than joining back to Book, so history survives even if the
# Book row is later deleted (see the /delete route on the stock page).
class Sale(Base):
    __tablename__ = "sales"
    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int | None] = mapped_column(ForeignKey("books.id"), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    isbn: Mapped[str | None] = mapped_column(String(32), nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    sold_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
