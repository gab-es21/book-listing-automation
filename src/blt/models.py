from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import String, DateTime, Float, Integer, Text, ForeignKey, func

class Base(DeclarativeBase): pass

class Book(Base):
    __tablename__ = "books"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="available")
    folder_path: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())

    listings: Mapped[list["Listing"]] = relationship(back_populates="book", cascade="all, delete-orphan")
    photos: Mapped[list["BookPhoto"]] = relationship(back_populates="book", cascade="all, delete-orphan")

class Listing(Base):
    __tablename__ = "listings"
    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"))
    platform: Mapped[str] = mapped_column(String(32))
    listing_url: Mapped[str] = mapped_column(String(1024), default="")
    status: Mapped[str] = mapped_column(String(32), default="posted")
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())

    book: Mapped[Book] = relationship(back_populates="listings")

class BookPhoto(Base):
    __tablename__ = "book_photos"
    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"))
    url: Mapped[str] = mapped_column(String(1024))
    idx: Mapped[int] = mapped_column(Integer)  # ordem (1,2,3...)

    book: Mapped[Book] = relationship(back_populates="photos")
