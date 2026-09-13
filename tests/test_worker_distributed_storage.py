import pytest

from internet_hands.telemetry import NullTelemetry
from internet_hands.worker import FrontierWorker


def test_distributed_capture_store_requires_shared_object_bucket(tmp_path):
    with pytest.raises(ValueError, match="requires s3_bucket"):
        FrontierWorker(
            "worker-test",
            frontier_db=tmp_path / "frontier.db",
            content_db=tmp_path / "content.db",
            content_postgres_dsn="postgresql://example.invalid/internet_hands",
            telemetry=NullTelemetry(),
        )
