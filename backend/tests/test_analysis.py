from app.services.analysis import generate_candidates, score_candidates
from app.services.ffmpeg import write_caption_srt


def test_highlights_include_context_and_are_ranked_without_duplicates():
    transcript = [
        {"start": 20, "end": 24, "text": "Wait, this is actually unbelievable!", "words": []},
        {"start": 25, "end": 29, "text": "Nobody expected that answer.", "words": []},
        {"start": 90, "end": 94, "text": "Here is how to do it step by step.", "words": []},
    ]
    scenes = [{"start": 0, "end": 45, "duration": 45}, {"start": 45, "end": 120, "duration": 75}]
    audio = [{"start": 20, "end": 20.5, "rms": 0.2, "peak": 0.8, "relative": 2.0}]
    candidates = generate_candidates(120, transcript, scenes, audio, [22])
    result = score_candidates(candidates, transcript, scenes, audio, [22])
    assert result
    assert result[0]["rank"] == 1
    assert result[0]["start"] < 20
    assert result[0]["end"] > 29
    assert result[0]["category"] in {"SHOCKING", "REACTION", "INTERESTING"}
    assert len(result[0]["title_suggestions"]) >= 2
    assert result[0]["hashtags"]
    assert all(item["score"] <= 99 for item in result)


def test_caption_file_uses_clip_relative_timestamps(tmp_path):
    output = write_caption_srt(
        [{"start": 10, "end": 13, "text": "A useful caption", "words": []}],
        clip_start=8,
        clip_end=18,
        output_path=tmp_path / "captions.srt",
    )
    assert output is not None
    content = output.read_text()
    assert "00:00:02,000 --> 00:00:05,000" in content
    assert "A useful caption" in content
