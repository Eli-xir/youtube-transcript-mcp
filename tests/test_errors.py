import pytest

from src.utils.errors import ErrorCode, YoutubeMcpError, map_ytdlp_error


def _mapped(msg):
    return map_ytdlp_error(RuntimeError("ERROR: [youtube] " + msg))


def test_private():
    e = _mapped("dQw4w9WgXcQ: Private video. Sign in if you've been granted access")
    assert e.code == ErrorCode.VIDEO_PRIVATE and not e.retryable and e.hint


def test_age_restricted():
    assert _mapped("Sign in to confirm your age").code == ErrorCode.AGE_RESTRICTED


def test_unavailable():
    assert _mapped("Video unavailable").code == ErrorCode.VIDEO_UNAVAILABLE


def test_geo():
    assert _mapped("not available in your country").code == ErrorCode.GEO_BLOCKED


def test_rate_limit():
    e = _mapped("HTTP Error 429: Too Many Requests")
    assert e.code == ErrorCode.RATE_LIMITED and e.retryable


def test_bot_check():
    assert _mapped("Sign in to confirm you're not a bot").code == ErrorCode.BOT_CHECK


def test_network():
    e = _mapped("Unable to download webpage: <urlopen error timed out>")
    assert e.code == ErrorCode.NETWORK_ERROR and e.retryable


def test_fallback_download_failed():
    e = _mapped("Requested format is not available")
    assert e.code == ErrorCode.DOWNLOAD_FAILED and e.retryable


def test_to_dict_shape():
    e = YoutubeMcpError("X_CODE", "boom", retryable=True, hint="do this", details={"video": "v"})
    d = e.to_dict()
    assert d == {"error": "X_CODE", "message": "boom", "retryable": True,
                 "hint": "do this", "video": "v"}
