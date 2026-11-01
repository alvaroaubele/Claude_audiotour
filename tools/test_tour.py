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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
