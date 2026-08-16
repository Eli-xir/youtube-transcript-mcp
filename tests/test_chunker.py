from src.transcript import chunker


def _segs(n, step=60.0):
    return [{"id": i, "start": i * step, "end": (i + 1) * step, "text": f"s{i}"} for i in range(n)]


def test_slice():
    segs = _segs(10)
    out = chunker.slice_segments(segs, 120, 240)
    assert [s["id"] for s in out] == [2, 3]  # inclusive overlap on both ends


def test_slice_open_ended():
    segs = _segs(10)
    assert len(chunker.slice_segments(segs, None, None)) == 10
    assert len(chunker.slice_segments(segs, 540, None)) == 1


def test_paginate():
    segs = _segs(10)
    assert len(chunker.paginate_segments(segs, 0, 3)) == 3
    assert chunker.paginate_segments(segs, 9, 3)[0]["id"] == 9
    assert len(chunker.paginate_segments(segs, 20)) == 0


def test_chunk_ranges():
    segs = _segs(20, step=60.0)  # 20 minutes
    ranges = chunker.chunk_ranges(segs, window_s=600)
    assert len(ranges) == 2
    assert ranges[0]["total_chunks"] == 2
    assert ranges[0]["start_timestamp"] == "00:00:00"
    assert ranges[1]["end_timestamp"] == "00:20:00"


def test_footer_shows_pagination_hint():
    segs = _segs(10)
    footer = chunker.chunk_footer({"d": 1}, segs[:4], 10, 0)
    assert footer is not None and "4 of 10" in footer and "offset=4" in footer
    assert chunker.chunk_footer({"d": 1}, segs, 10, 0) is None
