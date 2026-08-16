from conftest import json3_payload
from src.youtube.captions import (caption_payload_to_segments, parse_json3_words,
                                  parse_vtt, select_caption_track, words_to_segments)


class TestSelection:
    def test_requested_exact_manual_wins(self):
        sel = select_caption_track({"en": [1]}, {"en": [1], "es": [1]}, "en", ("en",))
        assert sel == ("manual", "en")

    def test_requested_exact_auto(self):
        sel = select_caption_track({}, {"en-US": [1]}, "en-US", ("en",))
        assert sel == ("auto", "en-us")

    def test_requested_prefix_match(self):
        sel = select_caption_track({"en-GB": [1]}, {}, "en", ("en",))
        assert sel == ("manual", "en-gb")

    def test_fallback_chain(self):
        sel = select_caption_track({}, {"de": [1], "fr": [1]}, None, ("en",))
        assert sel == ("auto", "de")  # no en at all -> first auto track (original lang)

    def test_nothing_available(self):
        assert select_caption_track({}, {}, "en", ("en",)) is None


class TestJson3:
    def test_word_timeline_and_dedupe(self):
        words = parse_json3_words(json3_payload().text)
        texts = [w.text for w in words]
        # rolling duplicate window must NOT double the words
        assert texts == ["hello", "world", "today", "we", "talk", "about", "PostgreSQL."]
        assert words[0].start == 0.0
        assert words[3].start == 3.0
        assert words[0].end == pytest.approx(0.6)

    def test_segments_grouping(self):
        segments, has_words = caption_payload_to_segments(json3_payload())
        assert has_words is True
        assert len(segments) >= 2
        assert segments[0].text.startswith("hello world")
        # sentence-final punctuation on 'PostgreSQL.' forces a segment break
        last = segments[-1]
        assert "PostgreSQL." in last.text
        assert last.words is not None


class TestVtt:
    RAW = """WEBVTT

00:00:00.000 --> 00:00:02.000
hello world

00:00:02.000 --> 00:00:04.000
hello world

00:00:02.000 --> 00:00:05.000
hello world today

00:00:05.000 --> 00:00:07.000
we talk about <c>PostgreSQL</c>
"""

    def test_parse_and_rolling_dedupe(self):
        segments = parse_vtt(self.RAW)
        texts = [s.text for s in segments]
        # exact duplicate cue dropped, prefix-overlap reduced to its new suffix, tags stripped
        assert texts == ["hello world", "today", "we talk about PostgreSQL"]

    def test_payload_fallback(self):
        from src.youtube.captions import CaptionPayload
        segs, has_words = caption_payload_to_segments(
            CaptionPayload(kind="manual", language="en", ext="vtt", text=self.RAW))
        assert has_words is False
        assert segs[0].start == 0.0  # first cue emitted at its own time


import pytest  # noqa: E402  (used above via pytest.approx)
