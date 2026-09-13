from pathlib import Path

from internet_hands.media import analyze_transcript, analyze_transcript_file, clean_transcript


def test_clean_srt_and_compute_transcript_metrics():
    text = """1
00:00:00,000 --> 00:00:02,000
Hello world #demo

2
00:00:02,500 --> 00:00:05,000
Visit https://example.com and ping @tester
"""
    cleaned, segments = clean_transcript(text)
    assert "Hello world #demo" in cleaned
    assert len(segments) == 2
    assert segments[1]["end_seconds"] == 5.0

    result = analyze_transcript(text)
    assert result["metrics"]["segments"] == 2
    assert result["metrics"]["duration_seconds"] == 5.0
    assert result["signals"]["hashtags"] == ["#demo"]
    assert result["signals"]["mentions"] == ["@tester"]
    assert result["signals"]["urls"] == ["https://example.com"]


def test_plain_transcript_falls_back_to_one_segment():
    result = analyze_transcript("Alpha beta beta gamma")
    assert result["metrics"]["segments"] == 1
    terms = {item["term"]: item["count"] for item in result["signals"]["top_terms"]}
    assert terms["beta"] == 2


def test_transcript_file_keeps_source_provenance(tmp_path: Path):
    path = tmp_path / "captions.vtt"
    path.write_text(
        "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nEvidence line\n",
        encoding="utf-8",
    )
    result = analyze_transcript_file(path)
    assert result["source"]["bytes"] == path.stat().st_size
    assert len(result["source"]["sha256"]) == 64
    assert result["text"] == "Evidence line"
