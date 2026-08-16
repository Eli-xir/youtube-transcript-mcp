from src.transcript.summarize import (build_summary, extract_topics, key_moments,
                                      sentences_from_segments)

PAYLOAD = {
    "video_id": "vid",
    "duration": 60.0,
    "segments": [
        {"start": 0.0, "end": 5.0, "text": "Welcome. Today we explore PostgreSQL performance tuning in depth."},
        {"start": 5.0, "end": 10.0, "text": "PostgreSQL indexes are the most important topic. Let me show you a demonstration."},
        {"start": 10.0, "end": 15.0, "text": "Make sure you run ANALYZE after loading data. Don't forget the statistics."},
        {"start": 15.0, "end": 20.0, "text": "In conclusion, PostgreSQL performance depends on indexes and statistics."},
    ],
}


def test_sentences():
    s = sentences_from_segments(PAYLOAD["segments"])
    assert len(s) >= 6
    assert s[0]["text"] == "Welcome."
    assert s[1]["start"] == 0.0


def test_executive_has_label_and_text():
    out = build_summary(PAYLOAD, style="executive")
    assert "Extractive summary" in out
    assert "EXECUTIVE SUMMARY" in out


def test_bullets_with_timestamps():
    out = build_summary(PAYLOAD, style="bullets")
    assert "- [" in out


def test_action_items_cue():
    out = build_summary(PAYLOAD, style="action_items")
    assert "ANALYZE" in out or "Don't forget" in out


def test_all_styles():
    out = build_summary(PAYLOAD, style="all", max_points=3)
    for section in ("EXECUTIVE SUMMARY", "KEY POINTS", "KEY TAKEAWAYS", "DETAILED SUMMARY",
                    "ACTION ITEMS", "NOTABLE LINES"):
        assert section in out


def test_key_moments():
    m = key_moments(PAYLOAD)
    assert any("demonstration" in x["cue"] or "conclusion" in x["cue"] for x in m)
    assert all(x["url"].startswith("https://www.youtube.com/watch?v=vid&t=") for x in m)


def test_topics():
    t = extract_topics(PAYLOAD, top=3)
    assert t and "Postgresql" in t[0]["topics"]
    assert t[0]["timestamp"] == "00:00:00"
