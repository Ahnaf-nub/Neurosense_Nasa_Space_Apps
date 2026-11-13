"""Forest Detective backend. Run:  FIRMS_KEY=xxxx uvicorn main:app --reload"""
import os, io, csv, json, time, threading, pathlib, math, tempfile
import httpx as requests
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from analysis import analyse
from trend import analyse_monthly, stats_annual, VARS
from geo import Geo

import re

def _load_env():
    """Read KEY=VALUE lines from .env next to this file (no extra package needed)."""
    f = pathlib.Path(__file__).resolve().parent / ".env"
    found = {}
    if f.exists():
        for line in f.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                found[k.replace("export ", "").strip()] = v.strip().strip('"').strip("'")
    for k, v in found.items(): os.environ.setdefault(k, v)
    for name in ("FIRMS_KEY", "FIRMS_MAP_KEY", "MAP_KEY", "NASA_FIRMS_KEY", "FIRMS_API_KEY", "NASA_API_KEY", "API_KEY"):
        if os.getenv(name): return os.environ[name], name
    for k, v in found.items():                      # fall back to any 32-char hex value (FIRMS keys look like that)
        if re.fullmatch(r"[0-9a-fA-F]{32}", v): return v, k
    return "", ""

FIRMS_KEY, _KEYNAME = _load_env()
print("FIRMS key:", ("loaded from " + _KEYNAME) if FIRMS_KEY else "NOT FOUND (put FIRMS_KEY=... in .env next to main.py)")
BASE = pathlib.Path(__file__).resolve().parent
CACHE = BASE / "cache"; CACHE.mkdir(exist_ok=True)
STATIC = BASE / "static"
MODIS = "https://modis.ornl.gov/rst/api/v1"

@asynccontextmanager
async def lifespan(app):
    # Worldwide requests are on demand; never crawl every land cell at startup.
    # Only the small city list is fetched in the background so the country picker is ready quickly.
    def warm():
        try: GEO.load()
        except Exception as e: print("City database not loaded yet:", type(e).__name__)
    threading.Thread(target=warm, daemon=True).start()
    yield

app = FastAPI(title="Forest Detective API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def _get(url, **kw):
    r = requests.get(url, timeout=90, follow_redirects=True, headers={"Accept": "application/json"}, **kw)
    r.raise_for_status(); return r.json()

def _download(url, dest):
    """Stream a file into the cache atomically (used once for the GeoNames city database)."""
    with tempfile.NamedTemporaryFile(dir=CACHE, delete=False) as tmp:
        try:
            with requests.stream("GET", url, timeout=120, follow_redirects=True) as r:
                r.raise_for_status()
                for chunk in r.iter_bytes(): tmp.write(chunk)
        except Exception:
            tmp.close(); os.unlink(tmp.name); raise
    os.replace(tmp.name, dest)

GEO = Geo(CACHE, _download)

def _cached(name, fn):
    f = CACHE / name
    if f.exists() and time.time() - f.stat().st_mtime < 86400 * 7:
        try: return json.loads(f.read_text())
        except (ValueError, OSError): pass
    v = fn()
    # Concurrent readers must never see a partially written JSON file.
    with tempfile.NamedTemporaryFile(mode="w", dir=CACHE, delete=False) as tmp:
        json.dump(v, tmp, allow_nan=False)
    os.replace(tmp.name, f)
    return v

def coordinates(lat, lon):
    if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise HTTPException(422, "Latitude must be -90..90 and longitude -180..180.")

def tree_cover(lat, lon):
    """Yearly MODIS MOD44B Percent Tree Cover (250 m) from the ORNL DAAC MODIS web service (no key)."""
    def go():
        bands = _get(f"{MODIS}/MOD44B/bands")["bands"]
        band = next(b["band"] for b in bands if "tree_cover" in b["band"].lower() and "sd" not in b["band"].lower() and "qual" not in b["band"].lower())
        dates = _get(f"{MODIS}/MOD44B/dates", params={"latitude": lat, "longitude": lon})["dates"]
        out = {}
        for i in range(0, len(dates), 10):
            ch = dates[i:i + 10]
            j = _get(f"{MODIS}/MOD44B/subset", params={"latitude": lat, "longitude": lon, "band": band,
                     "startDate": ch[0]["modis_date"], "endDate": ch[-1]["modis_date"], "kmAboveBelow": 1, "kmLeftRight": 1})
            for s in j["subset"]:
                vals = sorted(v for v in s["data"] if 0 <= v <= 100)   # >100 = water/fill codes
                if vals: out[int(s["calendar_date"][:4])] = vals[len(vals) // 2]
        return out
    d = _cached(f"tc_{lat:.2f}_{lon:.2f}.json", go)
    return sorted((int(k), v) for k, v in d.items())

def climate(lat, lon):
    def go():
        j = _get("https://power.larc.nasa.gov/api/temporal/monthly/point", params={
            "parameters": "T2M,PRECTOTCORR", "community": "AG", "latitude": lat, "longitude": lon,
            "start": 2000, "end": time.gmtime().tm_year - 1, "format": "JSON"})["properties"]["parameter"]
        ys = [y for y in range(2000, time.gmtime().tm_year) if j["T2M"].get(f"{y}13", -999) > -90 and j["PRECTOTCORR"].get(f"{y}13", -999) > -90]
        return {"years": ys, "T2M": [j["T2M"][f"{y}13"] for y in ys], "R": [j["PRECTOTCORR"][f"{y}13"] for y in ys]}
    return _cached(f"pw_{lat:.1f}_{lon:.1f}.json", go)

@app.get("/api/forest")
def forest(lat: float, lon: float):
    coordinates(lat, lon)
    lat, lon = round(lat, 2), round(lon, 2)
    try:
        tc = tree_cover(lat, lon); cl = climate(round(lat * 2) / 2, round(lon * 2) / 2)
        res = analyse([y for y, _ in tc], [v for _, v in tc], cl["years"], cl["T2M"], cl["R"])
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(502, "Satellite service unavailable; please retry later.")
    res.update(lat=lat, lon=lon, source="MODIS MOD44B (ORNL DAAC) + NASA POWER")
    _remember(res)
    return res

_fire = {}
_fire_lock = threading.Lock()
@app.get("/api/fires")
def fires(lat: float = 0, lon: float = 0, radius_km: float = 25):
    coordinates(lat, lon)
    if not FIRMS_KEY:
        raise HTTPException(503, "Add FIRMS_KEY to .env and restart to enable live fires.")
    if not math.isfinite(radius_km) or not 1 <= radius_km <= 100:
        raise HTTPException(422, "Fire window radius must be 1..100 km.")
    # A small city-centred bounding window, not administrative city totals.
    dy = radius_km / 111.32
    dx = min(180, dy / max(0.001, math.cos(math.radians(lat))))
    south, north = max(-90, lat - dy), min(90, lat + dy)
    west, east = lon - dx, lon + dx
    spans = [(west, east)]
    if west < -180: spans = [(west + 360, 180), (-180, east)]
    if east > 180: spans = [(west, 180), (-180, east - 360)]
    key = (round(lat, 2), round(lon, 2), round(radius_km, 2))
    with _fire_lock:
        hit = _fire.get(key)
        if hit and time.time() - hit[0] < 600: return hit[1]
    rows = []
    try:
        for west, east in spans:
            bbox = f"{west},{south},{east},{north}"
            for src in ("VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT"):
                r = requests.get(f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{FIRMS_KEY}/{src}/{bbox}/5", timeout=60, follow_redirects=True)
                r.raise_for_status()
                reader = csv.DictReader(io.StringIO(r.text))
                if not reader.fieldnames or "latitude" not in reader.fieldnames:
                    raise ValueError("Invalid FIRMS response")
                for row in reader:
                    la, lo = float(row["latitude"]), float(row["longitude"])
                    if math.isfinite(la) and math.isfinite(lo):
                        row["satellite_src"] = src; rows.append(row)
    except (requests.HTTPError, ValueError, KeyError):
        raise HTTPException(502, "FIRMS unavailable or key rejected; check configuration and retry.")
    with _fire_lock:
        if len(_fire) >= 32: _fire.clear()
        _fire[key] = (time.time(), rows)
    return rows

# Compatibility endpoint: only locations actually explored, never a global census.
_cells = {}
_lock = threading.Lock()
def _remember(r):
    if not r["forecast"]: return
    c0, c1 = r["cover"][0], r["cover"][-1]
    x = {"lat": r["lat"], "lon": r["lon"], "cover0": c0, "cover1": c1,
         "delta": round(c1-c0, 2), "fc": r["forecast"][-1],
         "fc_delta": round(r["forecast"][-1]-c1, 2), "cause": r["cause"],
         "p": r["cause_p_value"], "mae": r["holdout_mae_pct"],
         "naive": r.get("naive_mae_pct"), "y0": r["years"][0]}
    with _lock:
        if len(_cells) >= 1000: _cells.pop(next(iter(_cells)))
        _cells[(r["lat"],r["lon"])] = x

def _summary(c):
    if not c: return {"n": 0}
    return {"n": len(c), "mean_delta": round(sum(x["delta"] for x in c)/len(c),2),
            "year0": min(x["y0"] for x in c),
            **{k: round(100*sum(x["cause"] == k for x in c)/len(c)) for k in ("climate","human","mixed")}}

@app.get("/api/national")
@app.get("/api/explored")
def national():
    with _lock: c = list(_cells.values())
    return {"running": False, "total":len(c), "done":len(c), "failed":0,
            "skipped":0, "cells":c, "summary":_summary(c), "scope":"explored locations only"}

@app.get("/api/validate")
def validate():
    with _lock: c = list(_cells.values())
    if not c: raise HTTPException(425, "Explore a forest location first")
    maes = sorted(x["mae"] for x in c if x["mae"] is not None)
    out = {"cells": len(c), "median_mae": round(maes[len(maes) // 2], 2) if maes else None,
           "pct_beats_chance": round(100 * sum(1 for x in c if x["p"] is not None and x["p"] <= 0.15) / len(c)), "gfw": None}
    nv = [x for x in c if x.get("naive") is not None and x["mae"] is not None]
    if nv:
        ns = sorted(x["naive"] for x in nv)
        out["median_naive"] = round(ns[len(ns) // 2], 2)
        out["pct_beats_naive"] = round(100 * sum(1 for x in nv if x["mae"] < x["naive"]) / len(nv))
    f = BASE / "gfw_drivers.csv"       # optional: columns lat,lon,driver  (export from Global Forest Watch)
    if f.exists():
        agree = tot = skipped = 0
        for r in list(csv.DictReader(open(f, encoding="utf-8-sig")))[:40]:
            try: m = forest(float(r["lat"]), float(r["lon"]))["cause"]
            except Exception: skipped += 1; continue
            if m == "mixed": skipped += 1; continue
            g = "climate" if "fire" in r["driver"].lower() else "human"   # GFW has no climate class; wildfire is the closest
            tot += 1; agree += (m == g)
        if tot: out["gfw"] = {"agreement": round(100 * agree / tot), "n": tot, "skipped": skipped}
    return out

# ---------------- Trend Lab: any variable, any place, slope + significance ----------------
POWER_ALL = [v for v in VARS if v != "TREECOVER"]
POWER_URL = "https://power.larc.nasa.gov/api/temporal/monthly/point"

def power_monthly(lat, lon):
    def go():
        base = {"community": "AG", "latitude": lat, "longitude": lon, "start": 2001, "end": time.gmtime().tm_year - 1, "format": "JSON"}
        try:
            return _get(POWER_URL, params={**base, "parameters": ",".join(POWER_ALL)})["properties"]["parameter"]
        except Exception as e:
            print("POWER batch failed; retrying individual variables")
            out = {}
            for v in POWER_ALL:
                try: out.update(_get(POWER_URL, params={**base, "parameters": v})["properties"]["parameter"])
                except Exception as e2: print("POWER variable failed:", v)
            return out
    return _cached(f"pwall_{lat:.1f}_{lon:.1f}.json", go)

@app.get("/api/trend")
def trend(lat: float, lon: float, vars: str = "all"):
    coordinates(lat, lon)
    want = POWER_ALL if vars == "all" else [v.strip() for v in vars.split(",") if v.strip()]
    if not want or any(v not in VARS for v in want):
        raise HTTPException(422, "Unknown trend variable")
    res, pw = {}, None
    for v in want:
        try:
            if v == "TREECOVER":
                tc = tree_cover(round(lat, 2), round(lon, 2))
                res[v] = stats_annual(v, [y for y, _ in tc], [x for _, x in tc])
            elif v in VARS:
                if pw is None: pw = power_monthly(round(lat * 2) / 2, round(lon * 2) / 2)
                if v in pw: res[v] = analyse_monthly(v, pw[v])
        except Exception as e: print("trend skipped", v)
    if not res: raise HTTPException(502, "no trend data could be computed for this place")
    return {"lat": lat, "lon": lon, "results": res}

@app.get("/api/cities")
def cities(q: str = ""):
    q = q.strip()
    if not 2 <= len(q) <= 100:
        raise HTTPException(422, "Enter a city name between 2 and 100 characters.")
    res = _geo().search(q, 10)
    return {"results": [{"id": f"{c['cc']}-{c['lat']}-{c['lon']}", "name": c["name"], "country": c["country"], "admin1": "",
                         "lat": c["lat"], "lon": c["lon"], "pop": c["pop"]} for c in res], "attribution": "GeoNames (CC BY 4.0)"}

# ---------------- worldwide countries and cities (GeoNames, CC BY 4.0) ----------------
def _geo():
    try: GEO.load()
    except Exception:
        raise HTTPException(503, "World city data is unavailable. It must be downloaded once (internet needed); retry in a minute.")
    return GEO

def _cc(cc):
    if not re.fullmatch(r"[A-Za-z]{2}", cc or ""): raise HTTPException(422, "Country code must be two letters.")
    return cc.upper()

@app.get("/api/countries")
def countries():
    return {"countries": _geo().countries, "attribution": "GeoNames (CC BY 4.0)"}

@app.get("/api/country-cities")
def country_cities(cc: str, limit: int = 500):
    cc = _cc(cc); res = _geo().of_country(cc, max(1, min(limit, 2000)))
    if res is None: raise HTTPException(404, "No cities for that country code.")
    return {"results": res[0], "total": res[1], "country": GEO.names.get(cc, cc)}

@app.get("/api/places")
def places(w: float, s: float, e: float, n: float, min_pop: int = 0, limit: int = 300, cc: str = ""):
    if not all(math.isfinite(v) for v in (w, s, e, n)) or not (-180 <= w <= 180 and -180 <= e <= 180 and -90 <= s <= n <= 90):
        raise HTTPException(422, "Invalid map window.")
    cc = _cc(cc) if cc else ""
    return {"results": _geo().in_view(w, s, e, n, max(0, min_pop), max(1, min(limit, 600)), cc)}

@app.get("/api/health")
def health(): return {"ok": True, "firms": bool(FIRMS_KEY)}

if STATIC.exists():
    app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")
else:
    print("WARNING: put index.html in", STATIC)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)