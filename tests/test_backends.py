import pytest

from internet_hands.backends import (
    BackendError,
    backend_specs,
    get_backend,
    playwright_mcp_config,
)


def test_curated_backend_catalog_contains_expected_engines():
    names = {spec.name for spec in backend_specs()}
    assert {
        "playwright-mcp",
        "crawlee-python",
        "scrapy",
        "crawl4ai",
        "trafilatura",
        "firecrawl",
    }.issubset(names)


def test_firecrawl_is_not_cloned_by_default():
    assert get_backend("firecrawl").clone_by_default is False


def test_playwright_mcp_config_is_portable():
    config = playwright_mcp_config()
    server = config["mcpServers"]["playwright"]
    assert server["command"] == "npx"
    assert server["args"] == ["@playwright/mcp@latest"]


def test_unknown_backend_is_rejected():
    with pytest.raises(BackendError, match="Unknown backend"):
        get_backend("whatever-user-supplied-repo")
