import pytest

from src.utils.timestamps import (format_seconds, human_duration, parse_timestamp,
                                  srt_timestamp, vtt_timestamp)


class TestFormat:
    def test_hhmmss(self):
        assert format_seconds(382.41) == "00:06:22"
        assert format_seconds(3723) == "01:02:03"

    def test_mmss(self):
        assert format_seconds(750, "mmss") == "12:30"
        assert format_seconds(3723, "mmss") == "1:02:03"

    def test_seconds_style(self):
        assert format_seconds(382.41, "seconds") == "382.41"

    def test_ms(self):
        assert format_seconds(382.41, ms=True) == "00:06:22.410"

    def test_zero_and_negative(self):
        assert format_seconds(0) == "00:00:00"
        assert format_seconds(-5) == "00:00:00"


class TestParse:
    def test_plain_seconds(self):
        assert parse_timestamp("750") == 750.0
        assert parse_timestamp(750) == 750.0

    def test_mmss(self):
        assert parse_timestamp("12:30") == 750.0

    def test_hhmmss_and_ms(self):
        assert parse_timestamp("01:02:03") == 3723.0
        assert parse_timestamp("01:02:03.5") == 3723.5

    @pytest.mark.parametrize("bad", ["", "xx:30", "1:2:3:4", "-5", "12:99"])
    def test_invalid(self, bad):
        with pytest.raises(ValueError):
            parse_timestamp(bad)

    def test_roundtrip(self):
        for s in (0, 59.5, 750, 3723.25):
            assert parse_timestamp(format_seconds(s, ms=True)) == pytest.approx(s, abs=0.01)


def test_subtitle_formats():
    assert srt_timestamp(382.41) == "00:06:22,410"   # SRT uses commas
    assert vtt_timestamp(382.41) == "00:06:22.410"   # VTT uses dots
    assert "," in srt_timestamp(1.5) and "." in vtt_timestamp(1.5)


def test_human_duration():
    assert human_duration(3723) == "1:02:03"
    assert human_duration(750) == "12:30"
