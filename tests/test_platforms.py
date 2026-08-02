from blt import platforms


def test_load_platforms_reads_the_real_committed_config():
    result = platforms.load_platforms()

    slugs = {p.slug for p in result}
    assert slugs == {"vinted", "olx", "marketplace"}
    vinted = next(p for p in result if p.slug == "vinted")
    assert vinted.default is True
    assert vinted.name == "Vinted"


def test_load_platforms_returns_empty_list_when_config_file_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(platforms, "_CONFIG_PATH", tmp_path / "does_not_exist.json")

    assert platforms.load_platforms() == []


def test_platform_icon_url_derives_from_domain_when_no_override():
    p = platforms.Platform(slug="vinted", name="Vinted", domain="vinted.pt")

    assert p.icon_url == "https://www.google.com/s2/favicons?domain=vinted.pt&sz=16"


def test_platform_icon_url_uses_explicit_override_when_set():
    p = platforms.Platform(slug="vinted", name="Vinted", domain="vinted.pt", icon="https://example.com/logo.png")

    assert p.icon_url == "https://example.com/logo.png"
