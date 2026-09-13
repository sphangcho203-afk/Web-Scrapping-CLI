import pytest

from internet_hands.adapters import AdapterError, ExternalNetworkNotAllowed, capture_with_backend
from internet_hands.worker import FrontierWorker


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["crawlee", "crawl4ai", "scrapy"])
async def test_external_adapters_require_explicit_network_opt_in(backend):
    with pytest.raises(ExternalNetworkNotAllowed):
        await capture_with_backend(backend, "https://example.com/")


@pytest.mark.asyncio
async def test_unknown_external_backend_is_rejected():
    with pytest.raises(AdapterError, match="Unknown external backend"):
        await capture_with_backend("mystery", "https://example.com/")


def test_worker_rejects_external_backend_without_opt_in(tmp_path):
    with pytest.raises(ValueError, match="allow_external_network"):
        FrontierWorker(
            frontier_db=tmp_path / "frontier.db",
            content_db=tmp_path / "content.db",
            backend="crawl4ai",
        )
