"""Forest Detective backend. Run:  FIRMS_KEY=xxxx uvicorn main:app --reload"""
import os, io, csv, json, time, threading, pathlib, requests
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from analysis import analyse

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
BBOX = "88.0,20.5,92.7,26.7"
BASE = pathlib.Path(__file__).resolve().parent
CACHE = BASE / "cache"; CACHE.mkdir(exist_ok=True)
STATIC = BASE / "static"
MODIS = "https://modis.ornl.gov/rst/api/v1"
HOT = [(22.1, 89.2), (22.7, 92.1), (24.9, 91.9), (24.65, 90.05), (21.45, 92.0)]

@asynccontextmanager
async def lifespan(app):
    def run():  # pre-download the five forest hotspots so the first click is fast
        for la, lo in HOT:
            try: forest(la, lo)
            except Exception as e: print("warm-up failed", la, lo, e)
        _start_national()
    threading.Thread(target=run, daemon=True).start()
    yield

app = FastAPI(title="Forest Detective API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def _get(url, **kw):
    r = requests.get(url, timeout=90, headers={"Accept": "application/json"}, **kw)
    r.raise_for_status(); return r.json()

def _cached(name, fn):
    f = CACHE / name
    if f.exists(): return json.loads(f.read_text())
    v = fn(); f.write_text(json.dumps(v)); return v

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
    lat, lon = round(lat, 2), round(lon, 2)
    try:
        tc = tree_cover(lat, lon); cl = climate(round(lat * 2) / 2, round(lon * 2) / 2)
        res = analyse([y for y, _ in tc], [v for _, v in tc], cl["years"], cl["T2M"], cl["R"])
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(502, f"upstream data error: {e}")
    res.update(lat=lat, lon=lon, source="MODIS MOD44B (ORNL DAAC) + NASA POWER")
    return res

_fire = {"t": 0, "d": []}
@app.get("/api/fires")
def fires():
    if not FIRMS_KEY: raise HTTPException(503, "No FIRMS key found. Add FIRMS_KEY=your_key to the .env file next to main.py and restart.")
    if time.time() - _fire["t"] > 600:
        rows, err = [], ""
        for src in ("VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT"):
            try:
                txt = requests.get(f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{FIRMS_KEY}/{src}/{BBOX}/5", timeout=60).text
                got = list(csv.DictReader(io.StringIO(txt)))
                if got and "latitude" in got[0]:
                    for g in got: g["satellite_src"] = src
                    rows += got
                elif "latitude" not in txt[:300]:
                    err = txt[:200].strip() or "empty reply"
            except Exception as e:
                err = str(e)
        if not rows and err: raise HTTPException(502, "FIRMS said: " + err)
        _fire.update(t=time.time(), d=rows)
    return _fire["d"]


# ---------------- national grid (every 0.5 degree cell over Bangladesh) ----------------
from concurrent.futures import ThreadPoolExecutor
OUTLINE = [(88.1,26.2),(88.5,26.5),(89.0,26.4),(89.8,26.1),(89.8,25.3),(90.6,25.2),(91.5,25.2),(92.3,24.9),(92.0,24.3),(91.9,23.6),(91.6,22.9),(92.0,21.9),(92.3,20.7),(92.0,21.2),(91.8,22.3),(91.2,22.6),(90.6,22.2),(90.0,21.8),(89.3,21.8),(88.8,21.7),(88.7,22.5),(88.9,23.2),(88.4,23.8),(88.2,24.5),(88.6,24.9),(88.0,25.4)]
def _inside(la, lo):
    c = False; j = len(OUTLINE) - 1
    for i in range(len(OUTLINE)):
        xi, yi = OUTLINE[i]; xj, yj = OUTLINE[j]
        if (yi > la) != (yj > la) and lo < (xj - xi) * (la - yi) / (yj - yi) + xi: c = not c
        j = i
    return c
def _grid():
    out, la = [], 20.75
    while la <= 26.8:
        lo = 88.25
        while lo <= 92.8:
            if any(_inside(la + dy, lo + dx) for dx in (-.2, 0, .2) for dy in (-.2, 0, .2)): out.append((round(la, 2), round(lo, 2)))
            lo += .5
        la += .5
    return out

NATF = CACHE / "national.json"
_nat = {"running": False, "total": 0, "done": 0, "failed": 0, "skipped": 0, "cells": []}
_lock = threading.Lock()

def _cell(la, lo):
    r = forest(la, lo)
    c0, c1 = r["cover"][0], r["cover"][-1]
    return {"lat": la, "lon": lo, "cover0": c0, "cover1": c1, "delta": round(c1 - c0, 2), "fc": r["forecast"][-1],
            "fc_delta": round(r["forecast"][-1] - c1, 2), "cause": r["cause"], "p": r["cause_p_value"],
            "mae": r["holdout_mae_pct"], "naive": r.get("naive_mae_pct"), "y0": r["years"][0]}

def _build():
    pts = _grid(); _nat.update(running=True, total=len(pts), done=0, failed=0, skipped=0, cells=[])
    def work(p):
        skip = False
        try: x = _cell(*p)
        except HTTPException as e:
            x = None
            if e.status_code == 422: skip = True            # water / no tree-cover data: expected
            else: print("national cell failed", p, e.detail)
        except Exception as e: x = None; print("national cell failed", p, e)
        with _lock:
            _nat["done"] += 1
            if skip: _nat["skipped"] += 1
            elif x is None: _nat["failed"] += 1
            elif max(x["cover0"], x["cover1"]) >= 2: _nat["cells"].append(x)
    with ThreadPoolExecutor(3) as ex: list(ex.map(work, pts))
    NATF.write_text(json.dumps(_nat["cells"])); _nat["running"] = False
    print("national grid done:", len(_nat["cells"]), "cells modelled,", _nat["skipped"], "water/no-tree skipped,", _nat["failed"], "errors")

def _start_national():
    if _nat["running"] or _nat["cells"]: return
    if NATF.exists():
        c = json.loads(NATF.read_text()); _nat.update(cells=c, total=len(c), done=len(c)); return
    if os.getenv("NATIONAL", "1") != "0": _build()

def _summary():
    c = _nat["cells"]
    if not c: return {"n": 0}
    n = len(c); sh = lambda k: round(100 * sum(1 for x in c if x["cause"] == k) / n)
    return {"n": n, "mean_delta": round(sum(x["delta"] for x in c) / n, 2), "year0": c[0]["y0"],
            "climate": sh("climate"), "human": sh("human"), "mixed": sh("mixed")}

@app.get("/api/national")
def national():
    return {"running": _nat["running"], "total": _nat["total"], "done": _nat["done"], "failed": _nat["failed"], "skipped": _nat["skipped"],
            "cells": _nat["cells"], "summary": _summary()}

@app.get("/api/validate")
def validate():
    c = _nat["cells"]
    if not c or _nat["running"]: raise HTTPException(425, "national grid not ready")
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

@app.get("/api/health")
def health(): return {"ok": True, "firms": bool(FIRMS_KEY)}

if STATIC.exists():
    app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")
else:
    print("WARNING: put index.html in", STATIC)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)