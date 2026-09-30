from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


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
    # Which marketplace(s) this listing is currently posted on - independent
    # of status/quantity, since the same physical stock can be cross-posted
    # to several places at once. The set of possible platforms is config-driven
    # (see blt.platforms.load_platforms), so this is a join table rather than
    # one column per platform.
    platforms: Mapped[list["BookPlatform"]] = relationship(cascade="all, delete-orphan")


# One row per (book, platform) the book is currently posted on. A plain slug
# string rather than a foreign key to a platforms table, since the available
# platforms live in platforms.json, not the database - matches how Sale.platform
# below is also just a snapshot string, not a join.
class BookPlatform(Base):
    __tablename__ = "book_platforms"
    __table_args__ = (UniqueConstraint("book_id", "platform"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"))
    platform: Mapped[str] = mapped_column(String(32))


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
    # Which platform this particular copy sold on. Null when the book wasn't
    # cross-posted (nothing to disambiguate) or for sales recorded before
    # this column existed.
    platform: Mapped[str | None] = mapped_column(String(32), nullable=True)


# One "lote" (Marketplace/OLX grouped listing) per /bundle "Marcar
# selecionados" click - records which books were grouped and where, so
# /bundles can look back at what was published. Deliberately stores no
# sold/available state of its own: that's always read live from each item's
# Book row, the same single source of truth /stock already uses, so selling
# a book individually is reflected here automatically with no sync step.
class Bundle(Base):
    __tablename__ = "bundles"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
    items: Mapped[list["BundleItem"]] = relationship(cascade="all, delete-orphan")
    platforms: Mapped[list["BundlePlatform"]] = relationship(cascade="all, delete-orphan")


# One row per book included in a Bundle - snapshots title/author/price at
# the time of bundling (same reasoning as Sale: the lot's history survives
# the Book row being deleted later), while book_id is what lets a live
# available/sold status be looked up for as long as the book still exists.
class BundleItem(Base):
    __tablename__ = "bundle_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    bundle_id: Mapped[int] = mapped_column(ForeignKey("bundles.id"))
    book_id: Mapped[int | None] = mapped_column(ForeignKey("books.id"), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)


# Which platform(s) a Bundle went out on - same shape as BookPlatform, kept
# as its own table since these rows belong to a Bundle, not a Book.
class BundlePlatform(Base):
    __tablename__ = "bundle_platforms"
    __table_args__ = (UniqueConstraint("bundle_id", "platform"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    bundle_id: Mapped[int] = mapped_column(ForeignKey("bundles.id"))
    platform: Mapped[str] = mapped_column(String(32))
