import time

from src.cache.repository import TranscriptRepository, make_cache_key


def _payload(vid="vid1", source="whisper", model="small", language="en"):
    return {
        "video_id": vid, "language": language, "transcript_source": source, "model": model,
        "duration": 60.0, "created_at": time.time(), "segments": [
            {"id": 0, "start": 0.0, "end": 2.0, "text": "hello"}],
        "snapshot": {"title": "T"},
    }


class TestKey:
    def test_stable(self):
        assert make_cache_key("v", "en", "faster-whisper", "small", False, False) == \
               make_cache_key("v", "EN", "Faster-Whisper", "SMALL", False, False)

    def test_differs_by_config(self):
        base = make_cache_key("v", "en", "p", "m", False, False)
        assert make_cache_key("v", "de", "p", "m", False, False) != base
        assert make_cache_key("v", "en", "p", "large-v3", False, False) != base
        assert make_cache_key("v", "en", "p", "m", True, False) != base
        assert make_cache_key("other", "en", "p", "m", False, False) != base


class TestRepo:
    def test_put_get_roundtrip(self, repo):
        key = make_cache_key("vid1", "en", "p", "m", False, False)
        repo.put(key, _payload())
        got = repo.get(key)
        assert got["video_id"] == "vid1"
        assert got["segments"][0]["text"] == "hello"
        assert got["cache"]["cache_key"] == key

    def test_miss(self, repo):
        assert repo.get("nonexistent") is None

    def test_find_latest_and_versions(self, repo):
        repo.put(make_cache_key("v", "en", "p", "small", False, False), _payload(vid="v", language="en"))
        time.sleep(0.01)
        repo.put(make_cache_key("v", "de", "p", "small", False, False), _payload(vid="v", language="de"))
        latest = repo.find_latest("v")
        assert latest["language"] == "de"  # most recent wins
        assert repo.find_latest("v", language="en")["language"] == "en"
        assert len(repo.versions("v")) == 2
        assert repo.find_latest("other") is None

    def test_ttl_expiry(self, tmp_path):
        from conftest import make_settings
        repo = TranscriptRepository(make_settings(tmp_path, CACHE_TTL_DAYS="0"))
        key = make_cache_key("v", "en", "p", "m", False, False)
        repo.put(key, _payload())
        assert repo.get(key) is None  # TTL 0 -> instantly expired

    def test_overwrite_same_key_no_duplicate(self, repo):
        key = make_cache_key("v", "en", "p", "m", False, False)
        repo.put(key, _payload(vid="v"))
        repo.put(key, _payload(vid="v"))
        assert len(repo.versions("v")) == 1

    def test_prune_max_entries(self, tmp_path):
        from conftest import make_settings
        repo = TranscriptRepository(make_settings(tmp_path, MAX_CACHE_ENTRIES="3"))
        for i in range(6):
            repo.put(make_cache_key(f"v{i}", "en", "p", "m", False, False), _payload(vid=f"v{i}"))
            time.sleep(0.005)
        total = len([v for vs in [repo.versions(f"v{i}") for i in range(6)] for v in vs])
        assert total == 3
        assert repo.versions("v5")  # newest kept
        assert not repo.versions("v0")  # oldest evicted


class TestMetadata:
    def test_roundtrip(self, repo):
        assert repo.get_metadata("v") is None
        repo.put_metadata("v", {"title": "X"})
        assert repo.get_metadata("v") == {"title": "X"}
        repo.put_metadata("v", {"title": "Y"})
        assert repo.get_metadata("v") == {"title": "Y"}
