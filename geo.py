"""World cities from GeoNames (CC BY 4.0): every country, all places with population > 5,000.
Pure standard library so it can be tested offline. Data is downloaded once into the cache folder."""
import io, math, pathlib, threading, zipfile

CITIES_URL = "https://download.geonames.org/export/dump/cities5000.zip"
COUNTRIES_URL = "https://download.geonames.org/export/dump/countryInfo.txt"

class Geo:
    def __init__(self, cache_dir, fetch):
        """fetch(url, dest_path) must download url to dest_path (and raise on failure)."""
        self.dir = pathlib.Path(cache_dir); self.fetch = fetch; self.lock = threading.Lock()
        self.cities = None; self.by_cc = {}; self.countries = []; self.names = {}

    def load(self):
        with self.lock:
            if self.cities is not None: return
            zpath, cpath = self.dir / "cities5000.zip", self.dir / "countryInfo.txt"
            if not zpath.exists(): self.fetch(CITIES_URL, zpath)
            if not cpath.exists(): self.fetch(COUNTRIES_URL, cpath)
            self._parse(zpath, cpath)

    def _parse(self, zpath, cpath):
        names = {}
        for line in cpath.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#"):
                p = line.split("\t")
                if len(p) > 4: names[p[0]] = p[4]
        rows = []
        with zipfile.ZipFile(zpath) as z:
            member = next(n for n in z.namelist() if n.lower().endswith(".txt"))
            with z.open(member) as f:
                for raw in io.TextIOWrapper(f, encoding="utf-8"):
                    p = raw.rstrip("\n").split("\t")
                    if len(p) < 15: continue
                    try: la, lo, pop = float(p[4]), float(p[5]), int(p[14] or 0)
                    except ValueError: continue
                    if math.isfinite(la) and math.isfinite(lo): rows.append((p[1], la, lo, p[8], pop, p[2]))
        rows.sort(key=lambda c: -c[4])                      # biggest first: lets queries stop early
        by_cc = {}
        for c in rows: by_cc.setdefault(c[3], []).append(c)
        countries = []
        for cc, lst in by_cc.items():
            lats, lons = sorted(c[1] for c in lst), sorted(c[2] for c in lst)
            n = len(lst); a, b = (int(n * .03), max(int(n * .03), int(n * .97) - 1)) if n >= 20 else (0, n - 1)
            countries.append({"cc": cc, "name": names.get(cc, cc), "n": n,
                              "bbox": [round(lons[a], 3), round(lats[a], 3), round(lons[b], 3), round(lats[b], 3)]})
        countries.sort(key=lambda c: c["name"])
        self.cities, self.by_cc, self.countries, self.names = rows, by_cc, countries, names

    def _out(self, c):
        return {"name": c[0], "lat": c[1], "lon": c[2], "cc": c[3], "country": self.names.get(c[3], c[3]), "pop": c[4]}

    def in_view(self, w, s, e, n, min_pop=0, limit=300, cc=""):
        """Biggest places inside a map window (handles a window crossing the antimeridian)."""
        self.load()
        src = self.by_cc.get(cc.upper(), []) if cc else self.cities
        spans = [(w, e)] if w <= e else [(w, 180.0), (-180.0, e)]
        out = []
        for c in src:
            if c[4] < min_pop: break
            if s <= c[1] <= n and any(a <= c[2] <= b for a, b in spans):
                out.append(self._out(c))
                if len(out) >= limit: break
        return out

    def search(self, q, limit=10):
        """Find cities by name (accent-insensitive via GeoNames' ASCII name). 'London, Canada' narrows by country."""
        self.load()
        q = q.strip().lower(); country = ""
        if "," in q: q, country = [x.strip() for x in q.split(",", 1)]
        if not q: return []
        starts, inside = [], []
        for c in self.cities:                                   # already sorted by population, biggest first
            if country and not (self.names.get(c[3], "").lower().startswith(country) or c[3].lower() == country): continue
            n, a = c[0].lower(), c[5].lower()
            if n.startswith(q) or a.startswith(q): starts.append(c)
            elif len(inside) < limit and (q in n or q in a): inside.append(c)
            if len(starts) >= limit: break
        return [self._out(c) for c in (starts + inside)[:limit]]

    def of_country(self, cc, limit=500):
        self.load()
        lst = self.by_cc.get(cc.upper())
        if lst is None: return None
        return [self._out(c) for c in lst[:limit]], len(lst)
