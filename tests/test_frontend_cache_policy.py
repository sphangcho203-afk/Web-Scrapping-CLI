import pytest

from internet_hands import site


def test_mutable_frontend_assets_are_no_store() -> None:
    assert "no-store" in site.NO_STORE_HEADERS["Cache-Control"]

    runtime = site._browser_runtime()
    assert "no-store" in runtime.headers.get("cache-control", "")

    css = site.site_asset("cognitive-foundation.css")
    assert "no-store" in css.headers.get("cache-control", "")

    index = site._index()
    assert "no-store" in index.headers.get("cache-control", "")


def test_static_brand_assets_can_still_use_normal_caching() -> None:
    mark = site.site_asset("mark.svg")
    assert "no-store" not in mark.headers.get("cache-control", "")


@pytest.mark.parametrize("name", ["glass-orbit.webp", "glass-portal.webp", "glass-globe.webp"])
def test_dimensional_art_is_served_as_a_static_image(name: str) -> None:
    artwork = site.site_asset(name)
    assert artwork.media_type == "image/webp"
    assert artwork.path.is_file()
    assert "no-store" not in artwork.headers.get("cache-control", "")
