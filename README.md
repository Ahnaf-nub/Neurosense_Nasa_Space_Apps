# Forest Detective

**Is the tree cover around this city really changing, and is the change statistically significant?**

Forest Detective is a web app built by **Team Neurosense** (Dhaka, Bangladesh) for the **NASA Space Apps Challenge 2026**, challenge *Be an Earth System Trend Detective*. Search any city in the world, or click the map, and the app loads NASA satellite and climate records for that place, plots how each variable has changed, and tests whether the change is significant. It also forecasts tree cover to 2035 and checks whether tree loss lines up with hot or dry years.

- **Live app:** https://neurosense-nasa-space-apps.vercel.app/
- **Video:** https://youtu.be/lfcNLXE0tKM

> **Read this first.** Results are statistical *associations* from about 25 yearly points for a small area (roughly 2 to 3 km) around the selected point. They are not proof of cause and not city-wide statistics. The app says so on screen.

## How it answers the challenge

The challenge asks for a tool that shows **what** is changing, **where**, **how much**, and whether the change is **significant**.

| Question | In Forest Detective |
|---|---|
| What is changing? | **Trend Lab** scans 10 variables: mean, maximum and minimum temperature, rainfall, humidity, wind speed, surface sunlight, surface and root-zone soil wetness, and tree cover. Each has a plain-language definition. |
| Where? | Any city worldwide (every place above 5,000 people) or any clicked point. |
| How much? | Rate of change per decade with a 95% confidence interval, plus a time-series chart. |
| Significant? | OLS regression t-test **and** Mann-Kendall test with Sen's slope. A trend is called *significant* only when both agree at p < 0.05, *borderline* when one does. |

Demo buttons (for example Manaus rainfall, Berlin warming, Sydney soil wetness) show how the tool works.

## Features

- **Trend Lab**: variable scan, time series, rate per decade, confidence interval, two significance tests.
- **Forecast**: tree cover to 2035 with an 80% range, checked on the last 3 years of data.
- **Cause analysis**: does tree loss fall in hot or dry years more than chance would predict? If not, the app says planting alone will not hold the forest.
- **Live fire context**: NASA FIRMS detections from the last 5 days inside a 25 km box around the ranger.
- **Navigation-style map**: city and country names are placed like a navigation app (biggest first, never overlapping), with smaller towns appearing as you zoom in. Choose any country to see all its cities.
- **Detective game**: each place becomes a case file. Examine evidence, name a likely cause, see the model's verdict, then dig and plant. An animated ranger walks the map; a quiz and points make it a teaching tool.
- **Accessibility**: skippable intro (Esc or button), reduced-motion support, mobile action buttons.

## Data

| Data | Source | Used for |
|---|---|---|
| Tree cover, yearly, 250 m (MOD44B) | NASA MODIS via [ORNL DAAC MODIS web service](https://modis.ornl.gov/data/modis_webservice.html); product page at [LP DAAC](https://lpdaac.usgs.gov/products/mod44bv061/) | Tree-cover trend, forecast, cause analysis |
| Temperature, rainfall, humidity, wind, sunlight, soil wetness | [NASA POWER](https://power.larc.nasa.gov/) | Trend Lab, climate anomalies |
| Active fires (VIIRS) | [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/) | Live fire context |
| Satellite imagery layers | [NASA GIBS](https://www.earthdata.nasa.gov/gibs) | MODIS daily and vegetation-index map layers |
| Cities (`cities5000`) | [GeoNames](https://www.geonames.org/) (CC BY 4.0) | Search, labels, country list |
| Base map | [Esri World Imagery](https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer) | Satellite background |

The tree-cover value is the median of a small window (about 1 km each way) around the selected point, not a city average.

## Methods

1. **Trend tests** run on annual means (which also removes the seasonal cycle). OLS slope with t-test and 95% confidence interval; Mann-Kendall test with Sen's slope.
2. **Forecast**: ridge regression on year, temperature anomaly, rainfall anomaly and last year's rainfall. The 80% range comes from a residual bootstrap. It is checked against a simple "repeat last year" baseline on the last 3 years.
3. **Cause analysis**: share of tree-cover loss that falls in hot or dry years, compared with the share expected by chance using a circular-shift permutation test. Labelled *climate* only when the excess is large and p ≤ 0.15, *mixed* for a smaller excess, otherwise *human pressure / no climate signal*.

### Honest limits

- About 25 yearly points per place, and 250 m satellite pixels.
- MODIS tree cover also counts plantations and farm trees, not only natural forest.
- In an early validation run on 64 Bangladesh cells, forecast error on 3 held-out years was about ±4.2 points against ±4.3 for repeating the last year (the model won in 48% of cells), and the cause test passed in 14% of cells, about what chance alone gives. Treat forecasts and cause labels as **indicative** until checked against ground surveys.
- No claim is made about city boundaries or census areas.

## Run locally

Python 3.10 or newer.

```bash
python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
python -m pip install -r requirements.txt
```

Create a `.env` file next to `main.py` (get a free key at https://firms.modaps.eosdis.nasa.gov/api/map_key/):

```
FIRMS_KEY=your_key_here
```

Start the server and open http://127.0.0.1:8000 (do not open `index.html` directly):

```bash
python -m uvicorn main:app --reload
```

The first run downloads the GeoNames city list (about 5 MB) into `cache/`, so it needs internet. NASA data always needs internet. The first request for a new place can take about 30 seconds while tree-cover data is fetched. Everything is cached afterwards.

### Controls

| Key | Action |
|---|---|
| WASD / arrow keys, or click the map | Move the ranger |
| C | Open the case file |
| E | Dig and plant (after solving the case) |
| Q | Quiz |
| F | Refresh fires |

## Project structure

```
main.py          FastAPI app and NASA data requests
analysis.py      Forecast and cause analysis
trend.py         Trend statistics (OLS t-test, Mann-Kendall, Sen's slope)
geo.py           GeoNames city database and search
paths.py         Writable cache folder (works on read-only hosts)
static/          Front end: index.html, intro.js, ranger.js, images, intro video
test_*.py/.cjs   Offline tests
```

### API

| Endpoint | Returns |
|---|---|
| `GET /api/trend?lat&lon&vars=all` | Trend statistics for the variables at a point |
| `GET /api/forest?lat&lon` | Tree-cover series, forecast, 80% range, cause verdict |
| `GET /api/fires` | FIRMS detections near the ranger |
| `GET /api/cities?q=` | City search ("London, Canada" narrows by country) |
| `GET /api/countries`, `/api/country-cities?cc=`, `/api/places?w&s&e&n` | Country list, a country's cities, cities in a map window |

## Team

**Team Neurosense**, Dhaka, Bangladesh. Built for the NASA Space Apps Challenge 2026.
