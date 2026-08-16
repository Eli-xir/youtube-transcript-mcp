import pytest

from src.transcript.search import render_search, search_segments
from src.utils.errors import ErrorCode, YoutubeMcpError

SEGS = [
    {"id": 0, "start": 0.0, "end": 5.0, "text": "Welcome to the video about databases."},
    {"id": 1, "start": 5.0, "end": 10.0, "text": "Today we discuss PostgreSQL performance."},
    {"id": 2, "start": 10.0, "end": 15.0, "text": "PostgreSQL indexes matter a lot."},
    {"id": 3, "start": 15.0, "end": 20.0, "text": "Now something unrelated entirely."},
    {"id": 4, "start": 20.0, "end": 25.0, "text": "Back to PostgreSQL backups."},
    {"id": 5, "start": 25.0, "end": 30.0, "text": "Goodbye."},
]


def test_literal_case_insensitive():
    r = search_segments("vid", SEGS, "postgresql")
    assert r["total_matching_segments"] == 3
    assert r["results"][0]["timestamp"] == "00:00:05"
    assert r["results"][0]["url"].endswith("t=5s")


def test_case_sensitive():
    assert search_segments("vid", SEGS, "PostgreSQL", case_sensitive=True)["total_matching_segments"] == 3
    assert search_segments("vid", SEGS, "postgresql", case_sensitive=True)["total_matching_segments"] == 0


def test_adjacent_merged_with_context():
    # with context=1 the gaps close and all hits merge into one result group
    r = search_segments("vid", SEGS, "PostgreSQL", context=1)
    assert r["match_count"] == 1
    assert r["total_matching_segments"] == 3
    lines = r["results"][0]["context_lines"]
    assert any(l.startswith(">>") for l in lines)
    assert any(l.startswith("   ") for l in lines)
    # with context=0 only truly adjacent segments (1,2) merge; 4 stays separate
    assert search_segments("vid", SEGS, "PostgreSQL", context=0)["match_count"] == 2


def test_regex():
    r = search_segments("vid", SEGS, r"index\w*", regex=True)
    assert r["match_count"] == 1
    assert "indexes" in r["results"][0]["matched"][0]


def test_fuzzy():
    r = search_segments("vid", SEGS, "Postgresql performence", fuzzy=True, fuzzy_threshold=75)
    assert r["match_count"] >= 1


def test_max_results():
    assert search_segments("vid", SEGS, "postgresql", max_results=1)["match_count"] == 1


def test_no_match():
    r = search_segments("vid", SEGS, "quantum")
    assert r["match_count"] == 0 and r["results"] == []


def test_empty_query_rejected():
    with pytest.raises(YoutubeMcpError) as e:
        search_segments("vid", SEGS, "  ")
    assert e.value.code == ErrorCode.INVALID_ARGUMENT


def test_bad_regex_rejected():
    with pytest.raises(YoutubeMcpError) as e:
        search_segments("vid", SEGS, "([unclosed", regex=True)
    assert e.value.code == ErrorCode.INVALID_ARGUMENT


def test_render():
    r = search_segments("vid", SEGS, "PostgreSQL", context=0)
    text = render_search(r, "My Title")
    assert "My Title" in text and "2 match(es)" in text and "&t=" in text
