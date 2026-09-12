from internet_hands.endpoints import Capability, endpoint_catalog, providers
from internet_hands.intel import youtube_revenue_scenario, youtube_video_id


def test_youtube_video_id_variants():
    assert youtube_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert youtube_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert (
        youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        == "dQw4w9WgXcQ"
    )
    assert (
        youtube_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ")
        == "dQw4w9WgXcQ"
    )


def test_revenue_scenario_is_labeled_estimate():
    result = youtube_revenue_scenario(
        1_000_000,
        rpm_low=1.0,
        rpm_high=4.0,
        currency="USD",
    )
    assert result["kind"] == "scenario_estimate"
    assert result["estimated_low"] == 1000.0
    assert result["estimated_high"] == 4000.0
    assert "Not reported creator earnings" in result["warning"]


def test_endpoint_catalog_filters():
    youtube = endpoint_catalog(provider="youtube")
    assert youtube
    assert all(item.provider == "youtube" for item in youtube)
    assert any(item.capability == Capability.REVENUE for item in youtube)


def test_provider_catalog_has_broad_coverage():
    names = providers()
    for expected in {
        "youtube",
        "github",
        "bluesky",
        "mastodon",
        "twitch",
        "tiktok",
        "wikipedia",
        "openalex",
    }:
        assert expected in names
