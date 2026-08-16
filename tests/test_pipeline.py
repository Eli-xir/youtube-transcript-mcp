import pytest

from conftest import json3_payload
from src.transcription.pipeline import TranscribeRequest
from src.utils.errors import ErrorCode, YoutubeMcpError


def run(pipeline, **kw):
    return pipeline.run(TranscribeRequest(ref=kw.pop("url", "dQw4w9WgXcQ"), **kw))


class TestCaptionFirst:
    def test_captions_used_when_available(self, pipeline_factory):
        pipe, client, provider = pipeline_factory(captions=json3_payload())
        result = run(pipe)
        assert result.transcript.source == "youtube_auto"
        assert result.transcript.language == "en"
        assert not client.downloaded          # no audio download
        assert provider.calls == []           # no whisper
        assert not result.cache_hit

    def test_whisper_fallback_when_no_captions(self, pipeline_factory):
        pipe, client, provider = pipeline_factory(captions=None)
        result = run(pipe)
        assert result.transcript.source == "whisper"
        assert client.downloaded == ["dQw4w9WgXcQ"]
        assert len(provider.calls) == 1
        assert result.transcript.segments[0].text == "Hello world from whisper."

    def test_words_kept_only_when_requested(self, pipeline_factory):
        pipe, _, _ = pipeline_factory(captions=None)
        assert run(pipe).transcript.segments[0].words is None
        assert run(pipe, word_timestamps=True).transcript.segments[0].words is not None

    def test_force_retranscribe_bypasses_captions_and_cache(self, pipeline_factory):
        pipe, client, provider = pipeline_factory(captions=json3_payload())
        first = run(pipe)
        second = run(pipe, force_retranscribe=True)
        assert second.transcript.source == "whisper"
        assert client.downloaded == ["dQw4w9WgXcQ"]

    def test_metadata_cached_between_runs(self, pipeline_factory):
        pipe, client, _ = pipeline_factory(captions=json3_payload())
        run(pipe)
        client.meta = None  # second run would crash if it re-fetched
        result = run(pipe)
        assert result.cache_hit is True


class TestCache:
    def test_second_run_is_hit_without_work(self, pipeline_factory):
        pipe, client, provider = pipeline_factory(captions=None)
        first = run(pipe)
        second = run(pipe)
        assert first.cache_hit is False and second.cache_hit is True
        assert len(client.downloaded) == 1
        assert len(provider.calls) == 1
        assert second.transcript.video_id == first.transcript.video_id

    def test_different_language_different_key(self, pipeline_factory):
        pipe, _, provider = pipeline_factory(captions=None)
        run(pipe, language="en")
        run(pipe, language="de")
        assert len(provider.calls) == 2

    def test_speaker_request_is_honestly_noted(self, pipeline_factory):
        pipe, _, _ = pipeline_factory(captions=None)
        result = run(pipe, include_speakers=True)
        assert any("NOT identified" in n for n in result.transcript.notes)
        assert all(s.speaker is None for s in result.transcript.segments)


class TestErrors:
    def test_video_too_long(self, tmp_path):
        from conftest import META, FakeClient, FakeProvider, make_settings
        from src.cache.repository import TranscriptRepository
        from src.transcription.pipeline import TranscriptionPipeline
        settings = make_settings(tmp_path, MAX_VIDEO_DURATION="60")
        client = FakeClient()
        client.meta = dict(META, duration=7200.0)
        pipe = TranscriptionPipeline(settings, client, TranscriptRepository(settings),
                                     provider=FakeProvider())
        with pytest.raises(YoutubeMcpError) as e:
            run(pipe)
        assert e.value.code == ErrorCode.VIDEO_TOO_LONG

    def test_captions_only_mode_without_captions(self, tmp_path):
        from conftest import FakeClient, make_settings
        from src.cache.repository import TranscriptRepository
        from src.transcription.pipeline import TranscriptionPipeline
        settings = make_settings(tmp_path, TRANSCRIPTION_PROVIDER="none")
        pipe = TranscriptionPipeline(settings, FakeClient(captions=None),
                                     TranscriptRepository(settings), provider=None)
        with pytest.raises(YoutubeMcpError) as e:
            run(pipe)
        assert e.value.code == ErrorCode.CAPTIONS_UNAVAILABLE

    def test_provider_failure_mapped(self, pipeline_factory):
        from src.transcription.provider import TranscriptionProvider
        pipe, _, _ = pipeline_factory(captions=None)

        class Failing(TranscriptionProvider):
            name = "failing"

            def transcribe(self, audio_path, **kw):
                raise YoutubeMcpError(ErrorCode.TRANSCRIPTION_FAILED, "boom", retryable=True)

        pipe._provider = Failing()
        with pytest.raises(YoutubeMcpError) as e:
            run(pipe)
        assert e.value.code == ErrorCode.TRANSCRIPTION_FAILED


class TestJobs:
    def test_job_progress_and_complete(self, pipeline_factory):
        from src.jobs.manager import Job, JobManager
        pipe, _, _ = pipeline_factory(captions=None)
        job = JobManager().create("dQw4w9WgXcQ")
        result = run(pipe, job=job)
        assert job.status == "complete" and job.progress == 1.0
        assert job.cache_key
        assert result.transcript.video_id == "dQw4w9WgXcQ"

    def test_cancellation_before_start(self, pipeline_factory):
        from src.jobs.manager import Job, JobManager
        pipe, _, provider = pipeline_factory(captions=None)
        job = JobManager().create("dQw4w9WgXcQ")
        job.request_cancel()
        with pytest.raises(YoutubeMcpError) as e:
            run(pipe, job=job)
        assert e.value.code == ErrorCode.CANCELLED
        assert provider.calls == []
