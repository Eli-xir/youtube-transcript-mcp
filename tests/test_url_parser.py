import pytest

from src.utils.errors import ErrorCode, YoutubeMcpError
from src.youtube.url_parser import canonical_url, parse_video_ref, timestamp_url


class TestParse:
    def test_watch_url(self):
        ref = parse_video_ref("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert ref.video_id == "dQw4w9WgXcQ"
        assert ref.url == canonical_url("dQw4w9WgXcQ")

    def test_watch_url_with_params(self):
        ref = parse_video_ref("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=90s&list=x")
        assert ref.video_id == "dQw4w9WgXcQ"

    def test_short_url(self):
        assert parse_video_ref("https://youtu.be/dQw4w9WgXcQ").video_id == "dQw4w9WgXcQ"

    def test_shorts_embed_live(self):
        for u in ("https://www.youtube.com/shorts/dQw4w9WgXcQ",
                  "https://www.youtube.com/embed/dQw4w9WgXcQ",
                  "https://www.youtube.com/live/dQw4w9WgXcQ"):
            assert parse_video_ref(u).video_id == "dQw4w9WgXcQ", u

    def test_mobile_and_music(self):
        assert parse_video_ref("https://m.youtube.com/watch?v=dQw4w9WgXcQ").video_id == "dQw4w9WgXcQ"
        assert parse_video_ref("https://music.youtube.com/watch?v=dQw4w9WgXcQ").video_id == "dQw4w9WgXcQ"

    def test_bare_id(self):
        assert parse_video_ref("dQw4w9WgXcQ").video_id == "dQw4w9WgXcQ"

    def test_schemeless_tolerated(self):
        assert parse_video_ref("youtu.be/dQw4w9WgXcQ").video_id == "dQw4w9WgXcQ"

    def test_timestamp_url(self):
        assert timestamp_url("abc12345678", 90) == "https://www.youtube.com/watch?v=abc12345678&t=90s"


class TestRejections:
    @pytest.mark.parametrize("bad", [
        "", "not a url", "https://example.com/watch?v=dQw4w9WgXcQ",
        "https://evil.com/dQw4w9WgXcQ", "https://www.youtube.com/watch?v=short",
        "https://www.youtube.com/whatever", "https://youtu.be/toolongid12345",
    ])
    def test_invalid(self, bad):
        with pytest.raises(YoutubeMcpError) as e:
            parse_video_ref(bad)
        assert e.value.code == ErrorCode.INVALID_URL

    def test_playlist_rejected(self):
        with pytest.raises(YoutubeMcpError) as e:
            parse_video_ref("https://www.youtube.com/playlist?list=PL123")
        assert e.value.code == ErrorCode.PLAYLIST_UNSUPPORTED
