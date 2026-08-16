from src.transcript.chapters import (from_description, from_metadata,
                                     heuristic_chapters, render_chapters)


META = {
    "description": "Intro stuff\n\n0:00 Introduction\n2:30 Setup\n4:45 Demo\n7:00 Wrap up\n",
    "duration": 500.0,
    "chapters": None,
}


def test_from_metadata():
    meta = {"chapters": [{"title": "Intro", "start_time": 0, "end_time": 60},
                          {"title": "Main", "start_time": 60, "end_time": 120}]}
    ch = from_metadata(meta)
    assert [c["title"] for c in ch] == ["Intro", "Main"]
    assert ch[0]["source"] == "youtube"


def test_from_description():
    ch = from_description(META)
    assert [c["title"] for c in ch] == ["Introduction", "Setup", "Demo", "Wrap up"]
    assert ch[1]["start"] == 150.0
    assert ch[-1]["end"] == 500.0  # clamped to duration
    assert ch[0]["source"] == "description"


def test_description_rejects_non_chapter_timestamps():
    # two scattered timestamps -> not a chapter list
    assert from_description({"description": "at 1:00 something\nrandom 5:00 note", "duration": 600}) is None


def test_heuristic():
    segs = [{"start": i * 60, "end": (i + 1) * 60,
             "text": f"postgresql database query index performance minute {i}"} for i in range(20)]
    ch = heuristic_chapters(segs, target_minutes=5, duration=1200)
    assert len(ch) == 4  # 20 minutes / 5-minute windows
    assert all(c["source"] == "heuristic" for c in ch)
    assert any("Postgresql" in c["title"] for c in ch)


def test_render():
    ch = from_description(META)
    text = render_chapters(ch, "Video X")
    assert "[00:02:30 - 00:04:45] Setup" in text
