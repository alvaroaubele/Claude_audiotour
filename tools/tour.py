#!/usr/bin/env python3
"""Audiotour pipeline CLI.

Deterministic plumbing for the audio-guide agent: geocoding, POI discovery,
pedestrian routing, time budgeting, map export, TTS rendering, audio assembly
and the acceptance check. All judgment (stop selection, research, writing)
stays with the agents; this file only turns their decisions into artifacts.

Run `python3 tools/tour.py <command> -h` for each command's arguments.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import wave
import zipfile
from pathlib import Path
from urllib.parse import quote, urlencode

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache"
UA = "claude-audiotour/1.0 (+https://github.com/alvaroaubele/claude_audiotour)"
NOMINATIM = "https://nominatim.openstreetmap.org"
VALHALLA = os.environ.get("VALHALLA_URL", "https://valhalla1.openstreetmap.de")
SPARQL = "https://query.wikidata.org/sparql"
PIPER_HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

# Valhalla narrative languages (subset that matters for tours); fallback en-US.
VALHALLA_LANGS = {
    "es": "es-ES", "en": "en-US", "fr": "fr-FR", "de": "de-DE", "it": "it-IT",
    "pt": "pt-PT", "ca": "ca-ES", "nl": "nl-NL", "pl": "pl-PL", "ru": "ru-RU",
    "sv": "sv-SE", "cs": "cs-CZ", "el": "el-GR", "hu": "hu-HU", "ja": "ja-JP",
}


# --------------------------------------------------------------------------- io
def die(msg: str, code: int = 2) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def load_json(p: Path):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def save_json(p: Path, obj) -> None:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "tour"


def tour_dir(arg: str) -> Path:
    p = Path(arg)
    if not p.is_absolute():
        p = (ROOT / "tours" / arg) if not (ROOT / arg).exists() else ROOT / arg
    if not (p / "plan.json").exists():
        die(f"no plan.json in {p}")
    return p


# ------------------------------------------------------------------------- http
_last_call: dict[str, float] = {}


def http(method: str, url: str, *, host_interval: float = 1.1, cache: bool = True,
         timeout: int = 90, **kw):
    """Polite, cached HTTP returning parsed JSON. One request per host_interval."""
    key = hashlib.sha256(json.dumps([method, url, kw.get("params"), kw.get("json"),
                                     kw.get("data")], sort_keys=True, default=str).encode()).hexdigest()
    cpath = CACHE / "http" / f"{key}.json"
    if cache and cpath.exists():
        return load_json(cpath)
    host = url.split("/")[2]
    wait = host_interval - (time.time() - _last_call.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    headers = {"User-Agent": UA, **kw.pop("headers", {})}
    last_err = None
    for attempt in range(4):
        try:
            r = requests.request(method, url, headers=headers, timeout=timeout, **kw)
            _last_call[host] = time.time()
            if r.status_code in (429, 502, 503, 504):
                last_err = f"HTTP {r.status_code}"
                time.sleep(2 ** (attempt + 1))
                continue
            r.raise_for_status()
            data = r.json()
            if cache:
                save_json(cpath, data)
            return data
        except (requests.ConnectionError, requests.Timeout) as e:
            last_err = str(e)
            time.sleep(2 ** (attempt + 1))
    die(f"{method} {url} failed after retries: {last_err}")


# ---------------------------------------------------------------------- geo util
def haversine_m(a, b) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def decode_polyline6(s: str) -> list[list[float]]:
    coords, idx, lat, lon = [], 0, 0, 0
    while idx < len(s):
        for which in (0, 1):
            shift = result = 0
            while True:
                b = ord(s[idx]) - 63
                idx += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if which == 0:
                lat += delta
            else:
                lon += delta
        coords.append([round(lat / 1e6, 6), round(lon / 1e6, 6)])
    return coords


# ---------------------------------------------------------------------- commands
def cmd_init(a):
    slug = a.slug or slugify(f"{a.city}-{a.lang}-{int(a.minutes)}min")
    d = ROOT / "tours" / slug
    if (d / "plan.json").exists() and not a.force:
        die(f"{d}/plan.json exists (use --force to overwrite)")
    for sub in ("research", "scripts", "audio/raw", "map", "dist"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    plan = {
        "meta": {
            "slug": slug, "title": a.title or "", "city": a.city,
            "start_address": a.start, "start": None,
            "duration_min": a.minutes, "language": a.lang, "focus": a.focus or "",
            "date": a.date or "", "start_time": a.start_time or "",
            "register": "", "labels": {},
            "walking_speed_kmh": 4.0, "buffer_min_per_stop": 2.0,
            "tts": {"backend": a.tts, "voice": a.voice or "", "length_scale": 1.1},
            "wpm": None,
        },
        "stops": [],
        "legs": [],
    }
    save_json(d / "plan.json", plan)
    print(d)


def cmd_geocode(a):
    params = {"q": a.query, "format": "jsonv2", "limit": a.limit, "addressdetails": 1,
              "accept-language": a.lang or "en"}
    res = http("GET", f"{NOMINATIM}/search", params=params)
    out = [{"display_name": r["display_name"], "lat": float(r["lat"]), "lon": float(r["lon"]),
            "category": r.get("category"), "type": r.get("type"),
            "osm": f"{r.get('osm_type')}/{r.get('osm_id')}"} for r in res]
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if not out:
        die("no geocoding result; refine the address", 1)


SPARQL_POIS = """
SELECT ?item ?itemLabel ?itemDescription ?loc ?sitelinks ?article
       (GROUP_CONCAT(DISTINCT ?typeLabel; separator="|") AS ?types)
       (SAMPLE(?heritageLabel) AS ?heritage) WHERE {
  SERVICE wikibase:around {
    ?item wdt:P625 ?loc .
    bd:serviceParam wikibase:center "Point(%(lon)f %(lat)f)"^^geo:wktLiteral .
    bd:serviceParam wikibase:radius "%(radius)f" .
  }
  ?item wikibase:sitelinks ?sitelinks .
  FILTER(?sitelinks >= %(min_sitelinks)d)
  OPTIONAL { ?item wdt:P31 ?type . ?type rdfs:label ?typeLabel . FILTER(LANG(?typeLabel) = "en") }
  OPTIONAL { ?item wdt:P1435 ?h . ?h rdfs:label ?heritageLabel . FILTER(LANG(?heritageLabel) = "en") }
  OPTIONAL { ?article schema:about ?item ; schema:isPartOf <https://%(lang)s.wikipedia.org/> . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "%(lang)s,en,mul". }
}
GROUP BY ?item ?itemLabel ?itemDescription ?loc ?sitelinks ?article
ORDER BY DESC(?sitelinks)
LIMIT %(limit)d
"""


# Wikidata P31 labels (English, lowercased substrings) that are never a walkable stop.
NON_STOP_TYPES = ("edition", "contest", "election", "sports season", "tournament", "match",
                  "municipality", "capital", "big city", "city of", "commune", "human settlement",
                  "administrative", "census", "electoral", "metropolitan area", "television series",
                  "film", "album", "single", "historical event", "occurrence", "terrorist attack", "treaty",
                  "historical country", "championship", "transit line", "radio station", "news agency")


def cmd_pois(a):
    lang = a.lang.split("-")[0]
    q = SPARQL_POIS % {"lat": a.lat, "lon": a.lon, "radius": a.radius_km, "lang": lang,
                       "limit": a.limit, "min_sitelinks": a.min_sitelinks}
    res = http("POST", SPARQL, data={"query": q}, headers={"Accept": "application/sparql-results+json"},
               host_interval=1.0, timeout=120)
    out, dropped = [], 0
    for b in res["results"]["bindings"]:
        m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", b["loc"]["value"])
        if not m:
            continue
        types = b.get("types", {}).get("value", "").lower()
        if not a.keep_all and any(x in types for x in NON_STOP_TYPES):
            dropped += 1
            continue
        lon, lat = float(m.group(1)), float(m.group(2))
        qid = b["item"]["value"].rsplit("/", 1)[-1]
        if any(o["qid"] == qid for o in out):
            continue
        out.append({
            "qid": qid,
            "label": b.get("itemLabel", {}).get("value"),
            "description": b.get("itemDescription", {}).get("value", ""),
            "lat": lat, "lon": lon,
            "dist_m": round(haversine_m((a.lat, a.lon), (lat, lon))),
            "sitelinks": int(b["sitelinks"]["value"]),
            "types": [t for t in b.get("types", {}).get("value", "").split("|") if t],
            "heritage": b.get("heritage", {}).get("value", ""),
            "wikipedia": b.get("article", {}).get("value", ""),
        })
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"# {len(out)} candidates within {a.radius_km} km (ranked by Wikidata sitelinks); "
          f"{dropped} non-place items dropped (events, settlements, admin areas; --keep-all to keep)",
          file=sys.stderr)


def _valhalla_route(points, lang, speed_kmh):
    body = {
        "locations": [{"lat": p[0], "lon": p[1], "type": "break"} for p in points],
        "costing": "pedestrian",
        "costing_options": {"pedestrian": {"walking_speed": speed_kmh}},
        "language": lang, "units": "kilometers",
    }
    return http("POST", f"{VALHALLA}/route", json=body)


def cmd_route(a):
    d = tour_dir(a.tour)
    plan = load_json(d / "plan.json")
    meta, stops = plan["meta"], plan["stops"]
    if not meta.get("start"):
        die("meta.start {lat,lon} missing — geocode the start address first")
    if not stops:
        die("plan.stops is empty")
    lang = VALHALLA_LANGS.get(meta["language"].split("-")[0], "en-US")
    speed = float(meta.get("walking_speed_kmh") or 4.0)
    start = (meta["start"]["lat"], meta["start"]["lon"])

    if a.optimize:
        locs = [start] + [(s["lat"], s["lon"]) for s in stops]
        fixed_end = None
        if not a.open_end:
            fixed_end = locs.pop()  # keep the plan's last stop as the end point
        body = {"locations": [{"lat": p[0], "lon": p[1]} for p in locs + ([fixed_end] if fixed_end else [])],
                "costing": "pedestrian", "costing_options": {"pedestrian": {"walking_speed": speed}}}
        res = http("POST", f"{VALHALLA}/optimized_route", json=body)
        order = [loc["original_index"] for loc in res["trip"]["locations"]]
        new = [stops[i - 1] for i in order if 0 < i <= len(stops)]
        seen, ordered = set(), []
        for s in new:
            if s["id"] not in seen:
                seen.add(s["id"]); ordered.append(s)
        plan["stops"] = stops = ordered
        print("optimized order:", " → ".join(s["id"] for s in stops), file=sys.stderr)

    legs, prev_id, prev = [], "START", start
    for i, s in enumerate(stops):
        cur = (s["lat"], s["lon"])
        res = _valhalla_route([prev, cur], lang, speed)
        leg = res["trip"]["legs"][0]
        shape = decode_polyline6(leg["shape"])
        mans = [{
            "instruction": m.get("instruction", ""),
            "verbal": m.get("verbal_pre_transition_instruction", ""),
            "streets": m.get("street_names") or m.get("begin_street_names") or [],
            "length_m": round(m.get("length", 0) * 1000),
            "time_s": round(m.get("time", 0)),
            "type": m.get("type"),
            "at": shape[min(m.get("begin_shape_index", 0), len(shape) - 1)],
        } for m in leg["maneuvers"]]
        old = next((l for l in plan.get("legs", []) if l["id"] == f"L{i:02d}"), {})
        legs.append({
            "id": f"L{i:02d}", "from": prev_id, "to": s["id"],
            "distance_m": round(leg["summary"]["length"] * 1000),
            "time_s": round(leg["summary"]["time"]),
            "maneuvers": mans, "shape": shape,
            "script": old.get("script", f"scripts/L{i:02d}.md"),
            "words_target": old.get("words_target"),
        })
        prev_id, prev = s["id"], cur
    plan["legs"] = legs
    save_json(d / "plan.json", plan)
    tot_m = sum(l["distance_m"] for l in legs)
    tot_s = sum(l["time_s"] for l in legs)
    for l in legs:
        flag = "  <-- complex: consider a waypoint" if len(l["maneuvers"]) > 14 or l["distance_m"] > 1500 else ""
        print(f"{l['id']} {l['from']:>5} → {l['to']:<5} {l['distance_m']:>5} m {l['time_s']/60:5.1f} min "
              f"{len(l['maneuvers']):>2} maneuvers{flag}")
    print(f"TOTAL walk {tot_m/1000:.2f} km, {tot_s/60:.0f} min at {speed} km/h")


def _wpm(meta) -> float:
    return float(meta.get("wpm") or 150)


def cmd_budget(a):
    """Time budget: walk + Σ(narration + buffer + interior) vs duration_min.

    --distribute assigns narration_min to stops proportionally to `weight`
    (default 3) from the time left after walking, buffers and interiors.
    It then writes words_target for stops (narration_min × wpm) and legs
    (nav_fill × walk minutes × wpm).
    """
    d = tour_dir(a.tour)
    plan = load_json(d / "plan.json")
    meta, stops, legs = plan["meta"], plan["stops"], plan["legs"]
    if not legs:
        die("run `route` first")
    wpm = _wpm(meta)
    buf = float(meta.get("buffer_min_per_stop", 2))
    walk = sum(l["time_s"] for l in legs) / 60
    intro_min = float(meta.get("intro_min", 4))
    interiors = sum(float(s.get("interior_min", 0)) for s in stops)
    fixed = walk + buf * len(stops) + interiors + intro_min
    if a.distribute:
        avail = float(meta["duration_min"]) - fixed
        if avail <= len(stops) * 3:
            die(f"only {avail:.0f} min left for narration across {len(stops)} stops — drop stops or "
                "shorten the route", 1)
        wsum = sum(float(s.get("weight", 3)) for s in stops)
        for s in stops:
            s["narration_min"] = round(avail * float(s.get("weight", 3)) / wsum, 1)
    for s in stops:
        if s.get("narration_min"):
            s["words_target"] = int(round(float(s["narration_min"]) * wpm, -1))
    for l in legs:
        l["words_target"] = int(round(max(60, a.nav_fill * l["time_s"] / 60 * wpm), -1))
    meta["intro_words_target"] = int(round(intro_min * wpm, -1))
    save_json(d / "plan.json", plan)
    narr = sum(float(s.get("narration_min", 0)) for s in stops)
    total = fixed + narr
    print(f"wpm={wpm:.0f}  walk={walk:.0f}  intro={intro_min:.0f}  buffers={buf*len(stops):.0f}  "
          f"interiors={interiors:.0f}  narration={narr:.0f}  TOTAL={total:.0f} / budget {meta['duration_min']} min "
          f"({100*total/float(meta['duration_min']):.0f}%)")
    for s in stops:
        print(f"  {s['id']} {s['name'][:40]:<40} w={s.get('weight',3)} narr={s.get('narration_min','?')} min "
              f"words={s.get('words_target','?')}")
    for l in legs:
        print(f"  {l['id']} walk={l['time_s']/60:.1f} min nav_words={l['words_target']}")


# UI strings for track titles and map labels, by language family. meta.labels overrides any key.
LABELS = {
    "es": {"intro": "Introducción", "to": "Camino a", "outro": "Cierre", "track": "Pista", "start": "Inicio",
           "stops": "Paradas", "route": "Ruta a pie", "leg": "Tramo", "walk": "a pie", "nav": "Cómo llegar a pie",
           "narr": "Narración", "hours": "Horario"},
    "en": {"intro": "Introduction", "to": "Walk to", "outro": "Farewell", "track": "Track", "start": "Start",
           "stops": "Stops", "route": "Walking route", "leg": "Leg", "walk": "walk", "nav": "Walking directions",
           "narr": "Narration", "hours": "Opening hours"},
    "fr": {"intro": "Introduction", "to": "Vers", "outro": "Conclusion", "track": "Piste", "start": "Départ",
           "stops": "Étapes", "route": "Itinéraire à pied", "leg": "Tronçon", "walk": "à pied",
           "nav": "Itinéraire à pied", "narr": "Narration", "hours": "Horaires"},
    "de": {"intro": "Einführung", "to": "Weg zu", "outro": "Abschluss", "track": "Track", "start": "Start",
           "stops": "Stationen", "route": "Fußweg", "leg": "Abschnitt", "walk": "zu Fuß", "nav": "Fußweg",
           "narr": "Erzählung", "hours": "Öffnungszeiten"},
    "it": {"intro": "Introduzione", "to": "Verso", "outro": "Congedo", "track": "Traccia", "start": "Partenza",
           "stops": "Tappe", "route": "Percorso a piedi", "leg": "Tratto", "walk": "a piedi",
           "nav": "Indicazioni a piedi", "narr": "Narrazione", "hours": "Orari"},
    "pt": {"intro": "Introdução", "to": "Caminho para", "outro": "Despedida", "track": "Faixa", "start": "Início",
           "stops": "Paragens", "route": "Percurso a pé", "leg": "Troço", "walk": "a pé", "nav": "Como chegar a pé",
           "narr": "Narração", "hours": "Horário"},
}


def L(meta, key):
    return (meta.get("labels") or {}).get(key) or LABELS.get(meta["language"][:2], LABELS["en"])[key]


# -------------------------------------------------------------------------- map
def _gmaps_dir(o, dst):
    return ("https://www.google.com/maps/dir/?" +
            urlencode({"api": 1, "origin": f"{o[0]},{o[1]}", "destination": f"{dst[0]},{dst[1]}",
                       "travelmode": "walking"}))


def _track_order(plan):
    """Listening order: intro, then (leg, stop) pairs, then outro."""
    meta = plan["meta"]
    order = [{"id": "T00", "kind": "intro", "title": L(meta, "intro"), "script": "scripts/T00_intro.md"}]
    stop_by_id = {s["id"]: s for s in plan["stops"]}
    for l in plan["legs"]:
        s = stop_by_id[l["to"]]
        order.append({"id": l["id"], "kind": "leg", "title": f"{L(meta, 'to')} {s['name']}", "script": l["script"]})
        order.append({"id": s["id"], "kind": "stop", "title": s["name"],
                      "script": s.get("script", f"scripts/{s['id']}.md")})
    order.append({"id": "T99", "kind": "outro", "title": L(meta, "outro"), "script": "scripts/T99_outro.md"})
    for n, t in enumerate(order, 1):
        t["n"] = n
    return order


def cmd_map(a):
    d = tour_dir(a.tour)
    plan = load_json(d / "plan.json")
    meta, stops, legs = plan["meta"], plan["stops"], plan["legs"]
    tracks = {t["id"]: t for t in _track_order(plan)}
    start = (meta["start"]["lat"], meta["start"]["lon"])
    title = meta.get("title") or f"Audiotour {meta['city']}"
    e = html.escape

    def desc_stop(s, prev):
        t = tracks.get(s["id"], {})
        parts = [f"<b>{L(meta, 'track')} {t.get('n','?'):02}</b> · {e(s.get('kind',''))}"]
        if s.get("summary"):
            parts.append(e(s["summary"]))
        if s.get("narration_min"):
            parts.append(f"{L(meta, 'narr')} ≈ {s['narration_min']:.0f} min")
        if s.get("hours_note"):
            parts.append(L(meta, "hours") + ": " + e(s["hours_note"]))
        if s.get("wikipedia"):
            parts.append(f'<a href="{e(s["wikipedia"])}">Wikipedia</a>')
        parts.append(f'<a href="{e(_gmaps_dir(prev, (s["lat"], s["lon"])))}">{L(meta, 'nav')} (Google Maps)</a>')
        return "<br>".join(parts)

    pm = []
    pm.append(f"""<Placemark><name>00 · {L(meta, "start")}</name><styleUrl>#start</styleUrl>
<description><![CDATA[{e(meta['start_address'])}<br>{L(meta, 'track')} 01 · {L(meta, 'intro')}]]></description>
<Point><coordinates>{start[1]},{start[0]},0</coordinates></Point></Placemark>""")
    prev = start
    for i, s in enumerate(stops, 1):
        pm.append(f"""<Placemark><name>{i:02} · {e(s['name'])}</name><styleUrl>#stop</styleUrl>
<description><![CDATA[{desc_stop(s, prev)}]]></description>
<Point><coordinates>{s['lon']},{s['lat']},0</coordinates></Point></Placemark>""")
        prev = (s["lat"], s["lon"])
    lines = []
    name_by_id = {"START": L(meta, "start"), **{s["id"]: s["name"] for s in stops}}
    for l in legs:
        coords = " ".join(f"{p[1]},{p[0]},0" for p in l["shape"])
        n = tracks.get(l["id"], {}).get("n", 0)
        lines.append(f"""<Placemark><name>{L(meta, 'leg')} {l['id'][1:]} · {e(name_by_id[l['from']])} → {e(name_by_id[l['to']])}</name>
<styleUrl>#route</styleUrl><description><![CDATA[{L(meta, 'track')} {n:02} · {l['distance_m']} m · {l['time_s']/60:.0f} min {L(meta, 'walk')}]]></description>
<LineString><tessellate>1</tessellate><coordinates>{coords}</coordinates></LineString></Placemark>""")
    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>{e(title)}</name>
<description><![CDATA[{e(meta['city'])} · {meta['duration_min']} min · {e(meta['language'])}]]></description>
<Style id="start"><IconStyle><color>ff00b300</color><scale>1.3</scale><Icon><href>https://maps.google.com/mapfiles/kml/paddle/go.png</href></Icon></IconStyle></Style>
<Style id="stop"><IconStyle><color>ff0000ff</color><scale>1.1</scale><Icon><href>https://maps.google.com/mapfiles/kml/paddle/red-circle.png</href></Icon></IconStyle></Style>
<Style id="route"><LineStyle><color>ffd18802</color><width>5</width></LineStyle></Style>
<Folder><name>{L(meta, 'stops')}</name>
{chr(10).join(pm)}
</Folder>
<Folder><name>{L(meta, 'route')}</name>
{chr(10).join(lines)}
</Folder>
</Document></kml>
"""
    mdir = d / "map"
    mdir.mkdir(exist_ok=True)
    (mdir / "tour.kml").write_text(kml, encoding="utf-8")
    with zipfile.ZipFile(mdir / "tour.kmz", "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doc.kml", kml)
    # GPX for offline navigation apps (Organic Maps, OsmAnd, Komoot…)
    wpts = [f'<wpt lat="{start[0]}" lon="{start[1]}"><name>00 {e(L(meta, "start"))}</name></wpt>'] + [
        f'<wpt lat="{s["lat"]}" lon="{s["lon"]}"><name>{i:02} {e(s["name"])}</name></wpt>'
        for i, s in enumerate(stops, 1)]
    trkpts = "".join(f'<trkpt lat="{p[0]}" lon="{p[1]}"/>' for l in legs for p in l["shape"])
    gpx = (f'<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="claude-audiotour" '
           f'xmlns="http://www.topografix.com/GPX/1/1"><metadata><name>{e(title)}</name></metadata>'
           f'{"".join(wpts)}<trk><name>{e(title)}</name><trkseg>{trkpts}</trkseg></trk></gpx>\n')
    (mdir / "tour.gpx").write_text(gpx, encoding="utf-8")
    md = [f"# {title} — {L(meta, 'route')}\n"]
    prev = start
    for l, s in zip(legs, stops):
        md.append(f"- **{L(meta, 'leg')} {l['id'][1:]}** → {s['name']} ({l['distance_m']} m, {l['time_s']/60:.0f} min): "
                  f"{_gmaps_dir(prev, (s['lat'], s['lon']))}")
        prev = (s["lat"], s["lon"])
    (mdir / "links.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"wrote {mdir}/tour.kmz, tour.kml, tour.gpx, links.md "
          f"({len(stops)+1} placemarks, {len(legs)} route lines)")


# -------------------------------------------------------------------------- tts
PAUSES = {"[pausa]": 1.2, "[pausa larga]": 3.0, "[pause]": 1.2, "[long pause]": 3.0}


def script_to_segments(text: str):
    """Markdown script → [("text", str) | ("pause", seconds)].

    Not spoken: '# ' title lines, HTML comments (sources/notes), '---' rules.
    Paragraph breaks become 0.6 s pauses; [pausa]/[pausa larga] explicit pauses.
    Inline markdown emphasis is stripped.
    """
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    segs = []
    for para in re.split(r"\n\s*\n", text):
        lines = [ln for ln in para.strip().splitlines() if ln.strip() and not ln.lstrip().startswith("#")
                 and ln.strip() != "---"]
        if not lines:
            continue
        p = " ".join(ln.strip().lstrip(">-* ").strip() for ln in lines)
        p = re.sub(r"[*_`]+", "", p)
        for piece in re.split(r"(\[pausa larga\]|\[pausa\]|\[long pause\]|\[pause\])", p, flags=re.I):
            if not piece.strip():
                continue
            if piece.lower() in PAUSES:
                segs.append(("pause", PAUSES[piece.lower()]))
            else:
                segs.append(("text", piece.strip()))
        segs.append(("pause", 0.6))
    return segs


def count_words(path: Path) -> int:
    return sum(len(t.split()) for k, t in script_to_segments(path.read_text(encoding="utf-8")) if k == "text")


def _chunks(text: str, limit: int):
    sents = re.split(r"(?<=[.!?…;:])\s+", text)
    buf = ""
    for s in sents:
        if len(buf) + len(s) + 1 > limit and buf:
            yield buf
            buf = s
        else:
            buf = f"{buf} {s}".strip()
    if buf:
        yield buf


SR = 24000  # common sample rate for all backends after conversion


def _to_wav(src: Path, dst: Path):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-ac", "1", "-ar", str(SR),
                    "-sample_fmt", "s16", str(dst)], check=True)


def _silence(dst: Path, sec: float):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"anullsrc=r={SR}:cl=mono", "-t", f"{sec:.2f}", "-sample_fmt", "s16", str(dst)], check=True)


class PiperBackend:
    def __init__(self, locale: str, voice: str, length_scale: float):
        from piper import PiperVoice, SynthesisConfig
        vdir = CACHE / "piper"
        vdir.mkdir(parents=True, exist_ok=True)
        catalog_p = vdir / "voices.json"
        if not catalog_p.exists():
            r = requests.get(f"{PIPER_HF}/voices.json", headers={"User-Agent": UA}, timeout=60)
            r.raise_for_status()
            catalog_p.write_bytes(r.content)
        catalog = load_json(catalog_p)
        key = voice or self.pick(catalog, locale)
        if key not in catalog:
            die(f"piper voice {key!r} not in catalog")
        files = [f for f in catalog[key]["files"] if f.endswith((".onnx", ".onnx.json"))]
        for f in files:
            dst = vdir / Path(f).name
            if not dst.exists():
                print(f"downloading piper voice {Path(f).name} …", file=sys.stderr)
                with requests.get(f"{PIPER_HF}/{quote(f)}", headers={"User-Agent": UA}, stream=True, timeout=300) as r:
                    r.raise_for_status()
                    part = dst.with_name(dst.name + ".part")
                    with open(part, "wb") as fh:
                        for block in r.iter_content(1 << 20):  # decodes gzip transfer-encoding
                            fh.write(block)
                part.replace(dst)
                if dst.stat().st_size != catalog[key]["files"][f]["size_bytes"]:
                    dst.unlink()
                    die(f"size mismatch downloading {f}; retry")
        self.key = key
        self.voice = PiperVoice.load(vdir / f"{key}.onnx")
        self.cfg = SynthesisConfig(length_scale=length_scale)

    @staticmethod
    def pick(catalog, locale):
        loc = locale.replace("-", "_")
        fam = loc.split("_")[0]
        rank = {"high": 0, "medium": 1, "low": 2, "x_low": 3}
        cands = [v for v in catalog.values() if v["language"]["code"] == loc] or \
                [v for v in catalog.values() if v["language"]["family"] == fam]
        if not cands:
            die(f"no piper voice for {locale}")
        cands.sort(key=lambda v: (v["num_speakers"] > 1, rank.get(v["quality"], 9), v["key"]))
        return cands[0]["key"]

    def synth(self, text: str, out: Path):
        tmp = out.with_suffix(".piper.wav")
        with wave.open(str(tmp), "wb") as w:
            self.voice.synthesize_wav(text, w, syn_config=self.cfg)
        _to_wav(tmp, out)
        tmp.unlink()


class ElevenLabsBackend:
    """Untested in this repo's CI (needs ELEVENLABS_API_KEY). 10k-char/request cap per
    secondary sources; chunks are kept at 2500 chars and stitched with previous_text."""
    limit = 2500

    def __init__(self, locale, voice, **_):
        self.key = os.environ.get("ELEVENLABS_API_KEY") or die("ELEVENLABS_API_KEY not set")
        self.voice = voice or os.environ.get("ELEVENLABS_VOICE_ID") or die("set --voice or ELEVENLABS_VOICE_ID")
        self.model = os.environ.get("ELEVENLABS_MODEL", "eleven_multilingual_v2")
        self.prev = ""

    def synth(self, text, out: Path):
        r = requests.post(f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice}",
                          params={"output_format": "mp3_44100_128"},
                          headers={"xi-api-key": self.key, "User-Agent": UA},
                          json={"text": text, "model_id": self.model, "previous_text": self.prev[-1000:]},
                          timeout=300)
        r.raise_for_status()
        tmp = out.with_suffix(".mp3")
        tmp.write_bytes(r.content)
        _to_wav(tmp, out)
        tmp.unlink()
        self.prev = text


class OpenAIBackend:
    """Untested in this repo's CI (needs OPENAI_API_KEY). gpt-4o-mini-tts input cap is
    2000 tokens (OpenAI model page); chunks are kept at 1200 chars."""
    limit = 1200

    def __init__(self, locale, voice, **_):
        self.key = os.environ.get("OPENAI_API_KEY") or die("OPENAI_API_KEY not set")
        self.voice = voice or "onyx"
        self.model = os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
        self.instr = (f"Native {locale} speaker. Warm, erudite museum-guide narration for an educated "
                      "audience; unhurried pace, natural emphasis, clear pronunciation of proper names.")

    def synth(self, text, out: Path):
        r = requests.post("https://api.openai.com/v1/audio/speech",
                          headers={"Authorization": f"Bearer {self.key}", "User-Agent": UA},
                          json={"model": self.model, "voice": self.voice, "input": text,
                                "instructions": self.instr, "response_format": "wav"}, timeout=300)
        r.raise_for_status()
        tmp = out.with_suffix(".oai.wav")
        tmp.write_bytes(r.content)
        _to_wav(tmp, out)
        tmp.unlink()


class EdgeBackend:
    """Microsoft Edge read-aloud voices via edge-tts. Needs WebSockets: does NOT work
    behind the Claude Code cloud proxy; usable on a local machine."""
    limit = 3000

    def __init__(self, locale, voice, **_):
        self.voice = voice or {"es": "es-ES-AlvaroNeural", "en": "en-GB-RyanNeural",
                               "fr": "fr-FR-HenriNeural", "de": "de-DE-ConradNeural",
                               "it": "it-IT-DiegoNeural", "pt": "pt-PT-DuarteNeural"}.get(locale[:2], "")
        if not self.voice:
            die("set --voice for edge backend (see `edge-tts --list-voices`)")

    def synth(self, text, out: Path):
        tmp = out.with_suffix(".mp3")
        subprocess.run(["edge-tts", "--voice", self.voice, "--text", text, "--write-media", str(tmp)], check=True)
        _to_wav(tmp, out)
        tmp.unlink()


def make_backend(meta):
    t = meta.get("tts", {})
    name = t.get("backend", "piper")
    loc = meta["language"]
    if name == "piper":
        return PiperBackend(loc, t.get("voice", ""), float(t.get("length_scale", 1.1)))
    return {"elevenlabs": ElevenLabsBackend, "openai": OpenAIBackend, "edge": EdgeBackend}[name](loc, t.get("voice", ""))


def render_script(backend, script: Path, out_wav: Path):
    segs = script_to_segments(script.read_text(encoding="utf-8"))
    work = out_wav.parent / (out_wav.stem + ".parts")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    parts, n = [], 0
    limit = getattr(backend, "limit", 100000)
    for kind, val in segs:
        n += 1
        p = work / f"{n:05d}.wav"
        if kind == "pause":
            _silence(p, val)
            parts.append(p)
        else:
            for c in _chunks(val, limit):
                p = work / f"{n:05d}.wav"
                backend.synth(c, p)
                parts.append(p)
                n += 1
    lst = work / "list.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in parts))
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", str(out_wav)], check=True, cwd=work)
    shutil.rmtree(work)


def duration_s(p: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def cmd_calibrate(a):
    d = tour_dir(a.tour)
    plan = load_json(d / "plan.json")
    script = d / a.script
    b = make_backend(plan["meta"])
    out = d / "audio" / "raw" / "_calibration.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    render_script(b, script, out)
    words, dur = count_words(script), duration_s(out)
    wpm = words / (dur / 60)
    plan["meta"]["wpm"] = round(wpm, 1)
    if hasattr(b, "key") and isinstance(b.key, str) and plan["meta"]["tts"].get("backend") == "piper":
        plan["meta"]["tts"]["voice"] = b.key
    save_json(d / "plan.json", plan)
    print(f"voice={getattr(b, 'key', '') if plan['meta']['tts']['backend']=='piper' else plan['meta']['tts'].get('voice')} "
          f"words={words} duration={dur:.1f}s wpm={wpm:.1f} (saved to meta.wpm); sample: {out}")


def cmd_tts(a):
    d = tour_dir(a.tour)
    plan = load_json(d / "plan.json")
    b = make_backend(plan["meta"])
    raw = d / "audio" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    only = set(a.only.split(",")) if a.only else None
    for t in _track_order(plan):
        if only and t["id"] not in only:
            continue
        src, out = d / t["script"], raw / f"{t['id']}.wav"
        if not src.exists():
            print(f"skip {t['id']}: missing {t['script']}", file=sys.stderr)
            continue
        stamp = hashlib.sha256((src.read_text(encoding="utf-8") + plan["meta"]["language"] +
                               json.dumps(plan["meta"]["tts"])).encode()).hexdigest()
        sp = out.with_suffix(".sha")
        if out.exists() and sp.exists() and sp.read_text() == stamp and not a.force:
            continue
        t0 = time.time()
        render_script(b, src, out)
        sp.write_text(stamp)
        print(f"{t['n']:02} {t['id']:<4} {duration_s(out)/60:5.1f} min  ({time.time()-t0:.0f}s)  {t['title']}")


def cmd_assemble(a):
    d = tour_dir(a.tour)
    plan = load_json(d / "plan.json")
    meta = plan["meta"]
    title = meta.get("title") or f"Audiotour {meta['city']}"
    raw, dist = d / "audio" / "raw", d / "dist"
    shutil.rmtree(dist, ignore_errors=True)
    (dist / "mp3").mkdir(parents=True)
    tracks = [t for t in _track_order(plan) if (raw / f"{t['id']}.wav").exists()]
    missing = [t["id"] for t in _track_order(plan) if not (raw / f"{t['id']}.wav").exists()]
    if missing:
        die(f"missing rendered audio for {missing}; run `tts` first", 1)
    total = len(tracks)
    norm = d / "audio" / "norm"
    norm.mkdir(exist_ok=True)
    m3u, chapters, t_ms = ["#EXTM3U"], [], 0
    for t in tracks:
        nwav = norm / f"{t['id']}.wav"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(raw / f"{t['id']}.wav"),
                        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", str(SR), "-ac", "1", str(nwav)], check=True)
        fname = f"{t['n']:02d} - {slugify(t['title'])}.mp3"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(nwav), "-codec:a", "libmp3lame",
                        "-b:a", "96k", "-id3v2_version", "3",
                        "-metadata", f"title={t['n']:02d} · {t['title']}", "-metadata", f"album={title}",
                        "-metadata", "artist=Claude Audiotour", "-metadata", f"track={t['n']}/{total}",
                        "-metadata", "genre=Audiobook", str(dist / "mp3" / fname)], check=True)
        dur = duration_s(nwav)
        m3u.append(f"#EXTINF:{int(dur)},{t['n']:02d} · {t['title']}")
        m3u.append(f"mp3/{fname}")
        chapters.append((t_ms, t_ms + int(dur * 1000), f"{t['n']:02d} · {t['title']}"))
        t_ms += int(dur * 1000)
    (dist / "playlist.m3u").write_text("\n".join(m3u) + "\n", encoding="utf-8")
    # single-file audiobook with chapters
    lst = norm / "list.txt"
    lst.write_text("".join(f"file '{t['id']}.wav'\n" for t in tracks))
    ffmeta = [";FFMETADATA1", f"title={title}", "artist=Claude Audiotour", "genre=Audiobook"]
    for s, e_, name in chapters:
        ffmeta += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={s}", f"END={e_}", f"title={name}"]
    (norm / "chapters.txt").write_text("\n".join(ffmeta) + "\n", encoding="utf-8")
    book = dist / f"{meta['slug']}.m4b"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt",
                    "-i", "chapters.txt", "-map_metadata", "1", "-map_chapters", "1", "-c:a", "aac", "-b:a", "64k",
                    "-movflags", "+faststart", str(book)], check=True, cwd=norm)
    for f in ("tour.kmz", "tour.gpx", "links.md"):
        if (d / "map" / f).exists():
            shutil.copy(d / "map" / f, dist / f)
    print(f"dist: {total} MP3 tracks, {book.name} ({t_ms/60000:.0f} min, {len(chapters)} chapters), playlist.m3u")


# ------------------------------------------------------------------------ check
def cmd_check(a):
    """Acceptance check. Prints one line per open item, then PENDING=<n>."""
    d = tour_dir(a.tour)
    plan = load_json(d / "plan.json")
    meta, stops, legs = plan["meta"], plan["stops"], plan["legs"]
    pend = []

    def need(cond, msg):
        if not cond:
            pend.append(msg)

    need(meta.get("start"), "meta.start not geocoded")
    need(len(stops) >= 1, "no stops")
    need(len(legs) == len(stops), "legs out of date: run `route`")
    need(meta.get("wpm"), "meta.wpm not calibrated: run `calibrate`")
    order = _track_order(plan) if legs else []
    tol = a.tolerance
    for t in order:
        p = d / t["script"]
        if not p.exists():
            pend.append(f"{t['id']}: script missing ({t['script']})")
            continue
        w = count_words(p)
        target = None
        if t["kind"] == "stop":
            target = next(s for s in stops if s["id"] == t["id"]).get("words_target")
        elif t["kind"] == "leg":
            target = next(l for l in legs if l["id"] == t["id"]).get("words_target")
        elif t["kind"] == "intro":
            target = meta.get("intro_words_target")
        if target and not (target * (1 - tol) <= w <= target * (1 + tol)):
            pend.append(f"{t['id']}: {w} words vs target {target} (±{int(tol*100)}%)")
        if t["kind"] == "stop":
            fc = d / "research" / f"{t['id']}.factcheck.json"
            if not fc.exists():
                pend.append(f"{t['id']}: fact-check missing")
            else:
                f = load_json(fc)
                if f.get("status") != "pass":
                    pend.append(f"{t['id']}: fact-check status={f.get('status')} "
                                f"({len(f.get('findings', []))} findings)")
                elif f.get("script_sha") != hashlib.sha256(p.read_bytes()).hexdigest()[:16]:
                    pend.append(f"{t['id']}: script changed after fact-check (re-run fact-checker)")
        if a.stage in ("audio", "all"):
            wav = d / "audio" / "raw" / f"{t['id']}.wav"
            if not wav.exists():
                pend.append(f"{t['id']}: audio not rendered")
            else:
                ratio = duration_s(wav) / 60 * float(meta.get("wpm") or 150) / max(1, count_words(p))
                if not 0.7 <= ratio <= 1.4:
                    pend.append(f"{t['id']}: audio length inconsistent with script (ratio {ratio:.2f})")
    if a.stage in ("audio", "all"):
        kmz = d / "map" / "tour.kmz"
        if not kmz.exists():
            pend.append("map: tour.kmz missing")
        else:
            with zipfile.ZipFile(kmz) as z:
                k = z.read("doc.kml").decode()
            need(k.count("<Point>") == len(stops) + 1, "map: placemark count != stops + start")
            need(k.count("<LineString>") == len(legs), "map: route line count != legs")
        book = d / "dist" / f"{meta['slug']}.m4b"
        if not book.exists():
            pend.append("dist: m4b missing (run `assemble`)")
        else:
            r = subprocess.run(["ffprobe", "-v", "error", "-show_chapters", "-of", "json", str(book)],
                               capture_output=True, text=True)
            nch = len(json.loads(r.stdout or "{}").get("chapters", []))
            need(nch == len(order), f"dist: m4b has {nch} chapters, expected {len(order)}")
            need(len(list((d / "dist" / "mp3").glob("*.mp3"))) == len(order), "dist: mp3 count != tracks")
    if legs and meta.get("wpm"):
        walk = sum(l["time_s"] for l in legs) / 60
        listen = sum(count_words(d / t["script"]) for t in order if t["kind"] in ("stop", "intro", "outro")
                     and (d / t["script"]).exists()) / float(meta["wpm"])
        total = walk + listen + float(meta.get("buffer_min_per_stop", 2)) * len(stops) + \
            sum(float(s.get("interior_min", 0)) for s in stops)
        dev = total / float(meta["duration_min"]) - 1
        print(f"# time: walk {walk:.0f} + listen {listen:.0f} + buffers/interiors → {total:.0f} min "
              f"vs {meta['duration_min']} ({dev:+.0%})")
        if order and all((d / t["script"]).exists() for t in order):
            need(abs(dev) <= 0.15, f"time budget off by {dev:+.0%} (allowed ±15%)")
    for p in pend:
        print("OPEN:", p)
    print(f"PENDING={len(pend)}")
    sys.exit(0 if not pend else 1)


# ------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)

    p = sp.add_parser("init", help="scaffold tours/<slug>/ with plan.json")
    p.add_argument("--city", required=True); p.add_argument("--start", required=True)
    p.add_argument("--minutes", type=float, required=True); p.add_argument("--lang", required=True,
                                                                           help="BCP-47, e.g. es-ES, en-GB")
    p.add_argument("--focus"); p.add_argument("--date"); p.add_argument("--start-time")
    p.add_argument("--title"); p.add_argument("--slug")
    p.add_argument("--tts", default=os.environ.get("AUDIOTOUR_TTS", "piper"),
                   choices=["piper", "elevenlabs", "openai", "edge"])
    p.add_argument("--voice"); p.add_argument("--force", action="store_true")
    p.set_defaults(f=cmd_init)

    p = sp.add_parser("geocode", help="Nominatim lookup")
    p.add_argument("query"); p.add_argument("--limit", type=int, default=3); p.add_argument("--lang")
    p.set_defaults(f=cmd_geocode)

    p = sp.add_parser("pois", help="Wikidata candidates around a point, ranked by sitelinks")
    p.add_argument("--lat", type=float, required=True); p.add_argument("--lon", type=float, required=True)
    p.add_argument("--radius-km", type=float, default=1.5); p.add_argument("--lang", default="en")
    p.add_argument("--limit", type=int, default=150); p.add_argument("--min-sitelinks", type=int, default=3)
    p.add_argument("--keep-all", action="store_true", help="do not drop non-place item types")
    p.set_defaults(f=cmd_pois)

    p = sp.add_parser("route", help="Valhalla pedestrian legs START→S1→…; writes plan.legs")
    p.add_argument("tour"); p.add_argument("--optimize", action="store_true",
                                           help="reorder stops (start and last stop fixed)")
    p.add_argument("--open-end", action="store_true", help="with --optimize: let the end float")
    p.set_defaults(f=cmd_route)

    p = sp.add_parser("budget", help="time budget and words targets")
    p.add_argument("tour"); p.add_argument("--distribute", action="store_true")
    p.add_argument("--nav-fill", type=float, default=0.6,
                   help="fraction of walking time filled with speech (default 0.6)")
    p.set_defaults(f=cmd_budget)

    p = sp.add_parser("map", help="write map/tour.kmz, tour.kml, tour.gpx, links.md")
    p.add_argument("tour"); p.set_defaults(f=cmd_map)

    p = sp.add_parser("calibrate", help="render one script, measure words/min, save meta.wpm")
    p.add_argument("tour"); p.add_argument("script", help="path relative to the tour dir")
    p.set_defaults(f=cmd_calibrate)

    p = sp.add_parser("tts", help="render every track script to audio/raw/<id>.wav (cached by content)")
    p.add_argument("tour"); p.add_argument("--only", help="comma-separated track ids")
    p.add_argument("--force", action="store_true"); p.set_defaults(f=cmd_tts)

    p = sp.add_parser("assemble", help="loudness-normalise, MP3 per track, chaptered M4B, playlist")
    p.add_argument("tour"); p.set_defaults(f=cmd_assemble)

    p = sp.add_parser("words", help="count spoken words in a script")
    p.add_argument("script"); p.set_defaults(f=lambda a: print(count_words(Path(a.script))))

    p = sp.add_parser("check", help="acceptance check; prints PENDING=<n>")
    p.add_argument("tour"); p.add_argument("--stage", choices=["scripts", "audio", "all"], default="all")
    p.add_argument("--tolerance", type=float, default=0.25)
    p.set_defaults(f=cmd_check)

    p = sp.add_parser("factcheck-stamp", help="record the sha of the script a fact-check passed")
    p.add_argument("tour"); p.add_argument("stop_id")
    p.set_defaults(f=cmd_stamp)

    a = ap.parse_args()
    a.f(a)


def cmd_stamp(a):
    d = tour_dir(a.tour)
    plan = load_json(d / "plan.json")
    s = next((s for s in plan["stops"] if s["id"] == a.stop_id), None) or die(f"unknown stop {a.stop_id}")
    script = d / s.get("script", f"scripts/{s['id']}.md")
    fc = d / "research" / f"{s['id']}.factcheck.json"
    f = load_json(fc) if fc.exists() else die(f"{fc} missing")
    f["script_sha"] = hashlib.sha256(script.read_bytes()).hexdigest()[:16]
    save_json(fc, f)
    print(f"{a.stop_id}: status={f.get('status')} sha={f['script_sha']}")


if __name__ == "__main__":
    main()
