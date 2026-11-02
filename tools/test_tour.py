"""Offline unit tests for tools/tour.py: python3 -m pytest tools/ or python3 tools/test_tour.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import tour  # noqa: E402


def test_polyline6():
    # Google's reference polyline, read at precision 6 → coordinates / 10
    pts = tour.decode_polyline6("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
    assert pts == [[3.85, -12.02], [4.07, -12.095], [4.3252, -12.6453]]


def test_script_segments():
    txt = "# Título\n<!-- fuente: x -->\nPrimera frase. *Énfasis*.\n\n[pausa]\n\nSegundo párrafo [pausa larga] fin.\n"
    segs = tour.script_to_segments(txt)
    texts = [v for k, v in segs if k == "text"]
    pauses = [v for k, v in segs if k == "pause"]
    assert texts == ["Primera frase. Énfasis.", "Segundo párrafo", "fin."]
    assert 1.2 in pauses and 3.0 in pauses
    assert not any("Título" in t or "fuente" in t for t in texts)


def test_chunks_respect_limit():
    text = " ".join(f"Frase número {i} con algo de texto." for i in range(200))
    chunks = list(tour._chunks(text, 300))
    assert all(len(c) <= 300 for c in chunks) and " ".join(chunks) == text


def test_track_order_and_labels():
    plan = {"meta": {"language": "en-GB"},
            "stops": [{"id": "S01", "name": "A"}, {"id": "S02", "name": "B"}],
            "legs": [{"id": "L00", "to": "S01", "script": "scripts/L00.md"},
                     {"id": "L01", "to": "S02", "script": "scripts/L01.md"}]}
    order = tour._track_order(plan)
    assert [t["id"] for t in order] == ["T00", "L00", "S01", "L01", "S02", "T99"]
    assert order[1]["title"] == "Walk to A" and order[-1]["n"] == 6



def test_hms_and_timeline(tmp_path=None):
    import tempfile, json
    assert tour._hms(3725.5) == "01:02:05" and tour._hms(65.25, True) == "00:01:05.250"
    d = Path(tempfile.mkdtemp())
    (d / "map").mkdir(); dist = d / "dist"; (dist / "mp3").mkdir(parents=True)
    plan = {"meta": {"slug": "t", "title": "T", "language": "es-ES", "start_time": "16:00", "buffer_min_per_stop": 2},
            "stops": [{"id": "S01", "name": "A"}], "legs": [{"id": "L00", "time_s": 300}]}
    tl = [{"id": "T00", "kind": "intro", "n": 1, "title": "Intro", "file": "01 - intro.mp3", "start": 0, "duration": 60,
           "segments": [{"start": 0, "end": 5, "text": "Hola."}]},
          {"id": "L00", "kind": "leg", "n": 2, "title": "Camino", "file": "02 - c.mp3", "start": 60, "duration": 120,
           "segments": [{"start": 1, "end": 3, "text": "Gire."}]},
          {"id": "S01", "kind": "stop", "n": 3, "title": "A", "file": "03 - a.mp3", "start": 180, "duration": 600,
           "segments": []}]
    tour.write_timeline(d, plan, tl, dist)
    j = json.loads((dist / "timeline.json").read_text())
    clocks = [t["clock"] for t in j["tracks"]]
    assert clocks == [57600, 57660, 57960]  # 16:00, 16:01, then the leg takes max(walk 300 s, audio 120 s)
    vtt = (dist / "transcripcion.vtt").read_text()
    assert "00:01:01.000 --> 00:01:03.000" in vtt and "[02] Gire." in vtt
    assert (dist / "mp3" / "02 - c.lrc").read_text().splitlines()[2] == "[00:01.00]Gire."
    assert "16:06" in (dist / "indice.md").read_text()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
