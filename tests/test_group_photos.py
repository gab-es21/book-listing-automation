import os
import time
from pathlib import Path

import pytest
from PIL import Image

from blt import config
from blt import group_photos as gp


@pytest.fixture
def raw_and_grouped(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    grouped = tmp_path / "grouped"
    raw.mkdir()
    monkeypatch.setattr(config.settings, "RAW_DIR", str(raw))
    monkeypatch.setattr(config.settings, "GROUPED_DIR", str(grouped))
    monkeypatch.setattr(gp, "settings", config.settings)
    return raw, grouped


def _make_photo(folder: Path, name: str, taken_at: float, color) -> Path:
    """Create a distinct-colored JPEG with no EXIF, mtime set to `taken_at`."""
    p = folder / name
    Image.new("RGB", (4, 4), color=color).save(p, "JPEG")
    os.utime(p, (taken_at, taken_at))
    return p


def _pixel(path: Path):
    return Image.open(path).convert("RGB").getpixel((0, 0))


def _assert_color(actual, expected, tol=15):
    """JPEG is lossy - a solid color can drift a few units per channel after one encode/decode."""
    assert all(abs(a - e) <= tol for a, e in zip(actual, expected)), f"{actual} != {expected} (tol={tol})"


def test_pairs_by_capture_time_regardless_of_filename(raw_and_grouped):
    raw, grouped = raw_and_grouped
    base = time.time()
    COVER1, BACK1, COVER2, BACK2 = (10, 0, 0), (20, 0, 0), (30, 0, 0), (40, 0, 0)

    # filenames deliberately scrambled / not in chronological order
    _make_photo(raw, "zzz_book1_cover.jpg", base + 0, COVER1)
    _make_photo(raw, "aaa_book1_back.jpg", base + 10, BACK1)
    _make_photo(raw, "mmm_book2_cover.jpg", base + 20, COVER2)
    _make_photo(raw, "bbb_book2_back.jpg", base + 30, BACK2)

    created = gp.group_all()

    assert [c.name for c in created] == ["book_001", "book_002"]
    assert {p.name for p in created[0].iterdir()} == {"cover.jpg", "back.jpg"}
    _assert_color(_pixel(created[0] / "cover.jpg"), COVER1)
    _assert_color(_pixel(created[0] / "back.jpg"), BACK1)
    _assert_color(_pixel(created[1] / "cover.jpg"), COVER2)
    _assert_color(_pixel(created[1] / "back.jpg"), BACK2)


def test_exif_datetime_wins_over_mtime(raw_and_grouped):
    raw, grouped = raw_and_grouped
    p_earlier_exif = raw / "a.jpg"
    p_later_exif = raw / "b.jpg"

    img1 = Image.new("RGB", (4, 4), color=(2, 0, 0))
    exif1 = img1.getexif()
    exif1[306] = "2020:01:01 10:00:00"  # DateTime, earlier
    img1.save(p_earlier_exif, "JPEG", exif=exif1.tobytes())

    img2 = Image.new("RGB", (4, 4), color=(1, 0, 0))
    exif2 = img2.getexif()
    exif2[306] = "2021:01:01 10:00:00"  # DateTime, later
    img2.save(p_later_exif, "JPEG", exif=exif2.tobytes())

    # mtimes intentionally REVERSED vs EXIF dates, to prove EXIF wins
    now = time.time()
    os.utime(p_earlier_exif, (now + 100, now + 100))
    os.utime(p_later_exif, (now, now))

    created = gp.group_all()

    _assert_color(_pixel(created[0] / "cover.jpg"), (2, 0, 0))  # earlier EXIF -> cover
    _assert_color(_pixel(created[0] / "back.jpg"), (1, 0, 0))


def test_odd_leftover_is_kept_not_dropped_or_guessed(raw_and_grouped):
    raw, grouped = raw_and_grouped
    base = time.time()
    _make_photo(raw, "1.jpg", base + 0, (1, 0, 0))
    _make_photo(raw, "2.jpg", base + 10, (2, 0, 0))
    leftover = _make_photo(raw, "3.jpg", base + 20, (3, 0, 0))

    created = gp.group_all()

    assert len(created) == 1
    assert leftover.exists()  # left in place, not moved/paired/deleted
    assert list(raw.iterdir()) == [leftover]


def test_rerun_with_only_a_leftover_is_a_noop(raw_and_grouped):
    raw, grouped = raw_and_grouped
    _make_photo(raw, "only.jpg", time.time(), (1, 0, 0))

    created = gp.group_all()

    assert created == []
    assert len(list(raw.iterdir())) == 1


def test_empty_raw_dir_returns_empty_list(raw_and_grouped):
    created = gp.group_all()
    assert created == []


def test_numbering_continues_from_existing_book_folders(raw_and_grouped):
    raw, grouped = raw_and_grouped
    grouped.mkdir()
    (grouped / "book_005").mkdir()

    base = time.time()
    _make_photo(raw, "a.jpg", base, (1, 0, 0))
    _make_photo(raw, "b.jpg", base + 1, (2, 0, 0))

    created = gp.group_all()

    assert [c.name for c in created] == ["book_006"]


def test_max_groups_limits_how_many_are_created(raw_and_grouped):
    raw, grouped = raw_and_grouped
    base = time.time()
    for i in range(8):  # 4 full pairs
        _make_photo(raw, f"{i}.jpg", base + i, (i, 0, 0))

    created = gp.group_all(max_groups=2)

    assert [c.name for c in created] == ["book_001", "book_002"]
    # the other 4 photos (2 more pairs) are left ungrouped in raw
    assert len(list(raw.iterdir())) == 4
