# PROJECT KALA AGNI
# Advanced Orbital Intelligence Platform
# File: data_ingestion/data_collector.py

"""
KALA AGNI Data Collector — Zero-Budget Space Intelligence Pipeline
==================================================================
Ingests satellite TLE data from Celestrak and space weather telemetry
from NOAA/SWPC using only free, public API endpoints.

Data Sources:
    1. Celestrak GP (General Perturbations) TLE catalog — active satellites
    2. NOAA SWPC — planetary K-index (geomagnetic storms)
    3. NOAA SWPC — solar wind plasma parameters
    4. NOAA SWPC — 10.7 cm solar radio flux

Outputs:
    ../data/satellites.json  — filtered Indian constellation + full active TLE fallback
    ../data/space_weather.json — latest combined NOAA space weather snapshot

Next Steps (Phase 2+):
    - Plug parsed TLEs into sgp4 or poliastro for orbital propagation
    - Feed space weather into GNN collision-risk model
    - Stream mode with websocket listeners for real-time Kp alerts
"""

import json
import os
import re
import sys
import time
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ─── DEPENDENCY CHECK ────────────────────────────────────────────────────────
try:
    import requests
except ImportError:
    print("ERROR: 'requests' library is required. Install via: pip install requests")
    sys.exit(1)

# ─── LOGGING ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[KALA AGNI] %(asctime)s │ %(levelname)-8s │ %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("kala_agni.data_collector")

# ─── CONSTANTS ───────────────────────────────────────────────────────────────
# Celestrak active-satellite TLE endpoint (public, no key required)
CELESTRAK_TLE_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=TLE"

# NOAA Space Weather Prediction Center endpoints (public JSON APIs)
# Verified against https://services.swpc.noaa.gov/json/ directory listing (2026-04)
NOAA_KP_INDEX_URL = "https://services.swpc.noaa.gov/json/planetary_k_index_1m.json"
NOAA_SOLAR_WIND_URL = "https://services.swpc.noaa.gov/json/rtsw/rtsw_wind_1m.json"  # real-time solar wind
NOAA_SOLAR_FLUX_URL = "https://services.swpc.noaa.gov/json/f107_cm_flux.json"  # F10.7 solar radio flux

# Indian constellation keyword filters (case-insensitive, word-boundary match)
# Covers: communication, navigation (NavIC/IRNSS), Earth observation, scientific,
#         and emerging private-sector launchers.
# NOTE: We use regex word-boundary (\b) matching to avoid false positives like
#       LAGEOS→EOS, LATINSAT→INSAT, etc.
INDIAN_SAT_KEYWORDS = [
    "GSAT", "IRNSS", "NAVIC", "INSAT", "CARTOSAT", "RISAT",
    "OCEANSAT", "SCATSAT", "RESOURCESAT", "HYSIS", "EOS",
    "PIXEL", "DHRUVA", "ADITYA", "NISAR", "NVS",
    "AGN",       # Agnikul internal payloads
    "SKYROOT",   # Skyroot Aerospace
    "AGNIKUL",   # Agnikul Cosmos launches
]

# Pre-compile regex patterns for word-boundary matching (built once at import)
_INDIAN_SAT_PATTERNS = [re.compile(r'\b' + kw, re.IGNORECASE) for kw in INDIAN_SAT_KEYWORDS]

# Paths — resolved relative to THIS file's parent so it works from any CWD
_THIS_DIR = Path(__file__).resolve().parent
DATA_DIR = _THIS_DIR.parent / "data"
CACHE_DIR = DATA_DIR / "cache"

SATELLITES_FILE = DATA_DIR / "satellites.json"
SPACE_WEATHER_FILE = DATA_DIR / "space_weather.json"

# Cache TTL (seconds) — 1 hour keeps Celestrak happy and data fresh enough for MVP
CACHE_TTL_SECONDS = 3600

# HTTP settings — be a good citizen on public APIs
REQUEST_TIMEOUT = 15          # seconds
# FIXED: Celestrak now requires User-Agent header (was returning 403)
REQUEST_HEADERS = {
    "User-Agent": "KalaAgni-MVP/1.0 (Space Situational Awareness Platform)",
    "Accept": "text/plain, application/json",
}


# ═══════════════════════════════════════════════════════════════════════════════
# UTILITY HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _ensure_dirs():
    """Create data & cache directories if they don't exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_is_fresh(filepath: Path, ttl: int = CACHE_TTL_SECONDS) -> bool:
    """Return True if *filepath* exists and was modified within *ttl* seconds."""
    if not filepath.exists():
        return False
    age = time.time() - filepath.stat().st_mtime
    return age < ttl


def _save_json(filepath: Path, data) -> None:
    """Atomically write JSON to *filepath* (via tmp rename on POSIX; direct on Windows)."""
    _ensure_dirs()
    tmp = filepath.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str, ensure_ascii=False)
    # os.replace is atomic on most filesystems
    os.replace(tmp, filepath)
    logger.info("Saved → %s (%d bytes)", filepath.name, filepath.stat().st_size)


def _load_json(filepath: Path):
    """Load JSON from *filepath*."""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


class CelestrakDataUnchanged(Exception):
    """Raised when Celestrak returns 403 indicating data hasn't updated since last fetch."""
    pass


def _http_get(url: str, as_json: bool = False, retries: int = 2):
    """
    Fetch *url* with retry logic and rate-limit awareness.
    Returns response text (or parsed JSON if *as_json*).
    Raises on unrecoverable errors.
    """
    last_err = None
    for attempt in range(1, retries + 2):
        try:
            logger.debug("GET %s (attempt %d)", url, attempt)
            resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)

            # Celestrak returns 429 if you hammer it — back off politely
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 10))
                logger.warning("Rate-limited (429). Sleeping %d s ...", wait)
                time.sleep(wait)
                continue

            # FIXED: Celestrak returns 403 with a specific message when data
            # hasn't updated since your last download (their 2-hour cycle).
            # This is NOT an auth failure — it means "use your cache".
            if resp.status_code == 403 and "has not updated" in resp.text:
                logger.info(
                    "Celestrak 403: data unchanged since last download. Using cache."
                )
                raise CelestrakDataUnchanged(resp.text.strip())

            resp.raise_for_status()
            return resp.json() if as_json else resp.text

        except CelestrakDataUnchanged:
            raise  # let caller handle cache fallback
        except requests.exceptions.Timeout:
            logger.warning("Timeout on %s (attempt %d/%d)", url, attempt, retries + 1)
            last_err = "Timeout"
        except requests.exceptions.ConnectionError as e:
            logger.warning("Connection error on %s: %s", url, e)
            last_err = str(e)
        except requests.exceptions.HTTPError as e:
            logger.error("HTTP error on %s: %s", url, e)
            raise
        except Exception as e:
            logger.error("Unexpected error fetching %s: %s", url, e)
            raise

        # Exponential back-off between retries
        time.sleep(2 ** attempt)

    raise ConnectionError(f"Failed to fetch {url} after {retries + 1} attempts: {last_err}")


# ═══════════════════════════════════════════════════════════════════════════════
# TLE PARSING
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_tle_epoch(tle_line1: str) -> datetime:
    """
    Extract the TLE epoch from line 1 and return a timezone-aware UTC datetime.

    TLE epoch format (cols 19-32): YYDDD.DDDDDDDD
        YY  = two-digit year (00-56 → 2000s, 57-99 → 1900s per NORAD convention)
        DDD.DDDDDDDD = fractional day of year

    Future integration point:
        sgp4.api.jday() or astropy.time.Time can replace this for sub-ms precision.
    """
    try:
        epoch_str = tle_line1[18:32].strip()
        year_2d = int(epoch_str[:2])
        day_frac = float(epoch_str[2:])

        # NORAD two-digit year pivot: 57-99 → 1957-1999, 00-56 → 2000-2056
        year = 2000 + year_2d if year_2d < 57 else 1900 + year_2d

        # Jan 1 00:00 UTC + fractional day offset
        epoch = datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=day_frac - 1)
        return epoch
    except (ValueError, IndexError) as e:
        logger.warning("Could not parse TLE epoch from '%s': %s", tle_line1[:33], e)
        return datetime.now(timezone.utc)


def _extract_catalog_number(tle_line1: str) -> str:
    """
    Extract the NORAD catalog number from TLE line 1 (cols 3-7).
    Returns the number as a stripped string (e.g. '25338').
    """
    try:
        return tle_line1[2:7].strip()
    except (IndexError, TypeError):
        return "00000"


def _is_indian_satellite(name: str) -> bool:
    """Check if satellite name matches any Indian constellation keyword (word-boundary, case-insensitive)."""
    return any(pat.search(name) for pat in _INDIAN_SAT_PATTERNS)


def _parse_tle_text(raw_text: str) -> list[dict]:
    """
    Parse Celestrak TLE text (3-line format) into a list of satellite dicts.

    Format per satellite:
        Line 0: Satellite name (up to 24 chars, may have leading/trailing spaces)
        Line 1: TLE line 1 (starts with '1 ')
        Line 2: TLE line 2 (starts with '2 ')

    Returns list of dicts with keys:
        name, catalog_number, norad_id, tle_line1, tle_line2, epoch, is_indian
    """
    lines = [l.rstrip() for l in raw_text.strip().splitlines() if l.strip()]
    satellites = []

    i = 0
    while i < len(lines) - 2:
        # Heuristic: TLE line 1 starts with '1 ', line 2 starts with '2 '
        # The name line is whatever precedes them.
        name_line = lines[i].strip()
        line1 = lines[i + 1].strip()
        line2 = lines[i + 2].strip()

        if line1.startswith("1 ") and line2.startswith("2 "):
            catalog_number = _extract_catalog_number(line1)
            sat = {
                "name": name_line,
                "catalog_number": catalog_number,
                "norad_id": catalog_number,  # same as catalog number for TLE data
                "tle_line1": line1,
                "tle_line2": line2,
                "epoch": _parse_tle_epoch(line1).isoformat(),
                "is_indian": _is_indian_satellite(name_line),
            }
            satellites.append(sat)
            i += 3  # advance past this 3-line group
        else:
            # Malformed group — skip one line and re-try alignment
            logger.debug("Skipping misaligned TLE line at index %d: %s", i, name_line[:40])
            i += 1

    return satellites


# ═══════════════════════════════════════════════════════════════════════════════
# DATA COLLECTION FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def collect_satellite_data(refresh: bool = False) -> dict:
    """
    Fetch & parse active-satellite TLEs from Celestrak.

    Returns a dict:
        {
            "indian_satellites": [...],     # filtered Indian constellation assets
            "all_active_count": int,        # total active sats in catalog
            "all_active_satellites": [...],  # full TLE list (fallback / cross-ref)
            "collected_at": str,            # ISO timestamp
            "source": str,
            "cache_used": bool,
        }

    Caching:
        If satellites.json exists and is < 1 hour old, loads from cache
        unless *refresh* is True (forces a fresh pull).
    """
    _ensure_dirs()

    # ── Cache check ──────────────────────────────────────────────────────────
    if not refresh and _cache_is_fresh(SATELLITES_FILE):
        logger.info("Satellite cache is fresh (< %d s). Loading from disk.", CACHE_TTL_SECONDS)
        cached = _load_json(SATELLITES_FILE)
        cached["cache_used"] = True
        return cached

    # ── Fresh fetch ──────────────────────────────────────────────────────────
    logger.info("Fetching active TLEs from Celestrak ...")
    try:
        raw_tle = _http_get(CELESTRAK_TLE_URL)
    except CelestrakDataUnchanged:
        # Celestrak says data hasn't changed — fall back to cache if available
        if SATELLITES_FILE.exists():
            logger.info("Falling back to existing cache (Celestrak data unchanged).")
            cached = _load_json(SATELLITES_FILE)
            cached["cache_used"] = True
            cached["celestrak_note"] = "data unchanged since last fetch"
            return cached
        else:
            raise RuntimeError(
                "Celestrak says data unchanged but no cache exists. "
                "Wait 2 hours or manually download TLEs."
            )

    all_sats = _parse_tle_text(raw_tle)
    indian_sats = [s for s in all_sats if s["is_indian"]]

    logger.info(
        "Parsed %d active satellites -- %d Indian constellation assets identified.",
        len(all_sats),
        len(indian_sats),
    )

    result = {
        "indian_satellites": indian_sats,
        "all_active_count": len(all_sats),
        "all_active_satellites": all_sats,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "source": CELESTRAK_TLE_URL,
        "cache_used": False,
    }

    # Persist to cache
    _save_json(SATELLITES_FILE, result)
    return result


def get_indian_constellation(refresh: bool = False) -> list[dict]:
    """
    Convenience function — returns ONLY the Indian satellites.

    Useful for downstream modules (preprocessor, ML engine) that only
    care about our constellation.

    Future: Add orbit-class tagging (GEO/MEO/LEO) using TLE inclination
            and mean motion once sgp4/poliastro are integrated.
    """
    data = collect_satellite_data(refresh=refresh)
    return data["indian_satellites"]


def get_space_weather(refresh: bool = False) -> dict:
    """
    Fetch latest space weather data from NOAA SWPC.

    Returns a dict:
        {
            "kp_index": [...],      # planetary K-index history
            "solar_wind": [...],    # solar wind plasma data
            "solar_flux": [...],    # 10.7 cm flux (F10.7) — may be empty on 404
            "latest_kp": dict,      # most recent Kp reading (convenience)
            "collected_at": str,
            "cache_used": bool,
        }

    Caching:
        If space_weather.json exists and is < 1 hour old, loads from cache
        unless *refresh* is True.
    """
    _ensure_dirs()

    # ── Cache check ──────────────────────────────────────────────────────────
    if not refresh and _cache_is_fresh(SPACE_WEATHER_FILE):
        logger.info("Space weather cache is fresh. Loading from disk.")
        cached = _load_json(SPACE_WEATHER_FILE)
        cached["cache_used"] = True
        return cached

    # ── Fetch Kp index ───────────────────────────────────────────────────────
    logger.info("Fetching planetary K-index from NOAA …")
    try:
        kp_data = _http_get(NOAA_KP_INDEX_URL, as_json=True)
    except Exception as e:
        logger.error("Failed to fetch Kp index: %s", e)
        kp_data = []

    # ── Fetch solar wind ─────────────────────────────────────────────────────
    logger.info("Fetching solar wind data from NOAA …")
    try:
        solar_wind_data = _http_get(NOAA_SOLAR_WIND_URL, as_json=True)
    except Exception as e:
        logger.error("Failed to fetch solar wind: %s", e)
        solar_wind_data = []

    # ── Fetch solar flux (F10.7) — might 404, that's OK ─────────────────────
    logger.info("Fetching 10.7 cm solar flux from NOAA …")
    try:
        solar_flux_data = _http_get(NOAA_SOLAR_FLUX_URL, as_json=True)
    except Exception as e:
        logger.warning("Solar flux endpoint unavailable (non-critical): %s", e)
        solar_flux_data = []

    # ── Extract latest Kp for quick summary ──────────────────────────────────
    latest_kp = {}
    if kp_data and isinstance(kp_data, list):
        latest_kp = kp_data[-1] if kp_data else {}
        # Try to pull the numeric Kp value for display
        kp_val = latest_kp.get("kp_index") or latest_kp.get("kp") or latest_kp.get("Kp")
        if kp_val is not None:
            try:
                kp_numeric = float(kp_val)
                if kp_numeric >= 5:
                    logger.warning(
                        "⚠️  GEOMAGNETIC STORM ALERT — Kp = %.1f (threshold: 5.0). "
                        "Increased drag on LEO assets possible.",
                        kp_numeric,
                    )
            except (ValueError, TypeError):
                pass

    result = {
        "kp_index": kp_data,
        "solar_wind": solar_wind_data,
        "solar_flux": solar_flux_data,
        "latest_kp": latest_kp,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "kp_index": NOAA_KP_INDEX_URL,
            "solar_wind": NOAA_SOLAR_WIND_URL,
            "solar_flux": NOAA_SOLAR_FLUX_URL,
        },
        "cache_used": False,
    }

    _save_json(SPACE_WEATHER_FILE, result)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN — STANDALONE TESTING
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """
    Run the full data collection pipeline and print a diagnostic summary.
    Useful for Day-1 validation and CI smoke tests.
    """
    # Fix Windows console encoding for Unicode/emoji output
    import io
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    print()
    print("=" * 72)
    print("  PROJECT KALA AGNI -- Data Collector v1.0")
    print("  Advanced Orbital Intelligence Platform")
    print("=" * 72)
    print()

    # -- 1. Satellite data -------------------------------------------------
    print("-" * 52)
    print("  PHASE 1: Satellite TLE Ingestion")
    print("-" * 52)
    try:
        sat_data = collect_satellite_data(refresh=False)
        indian = sat_data["indian_satellites"]

        print(f"\n  [SAT] Total active satellites in catalog : {sat_data['all_active_count']}")
        print(f"  [IND] Indian constellation assets found : {len(indian)}")
        print(f"  [DSK] Cache used                        : {sat_data['cache_used']}")
        print(f"  [CLK] Collected at                      : {sat_data['collected_at']}")

        if indian:
            print(f"\n  -- Sample Indian Satellites (first 5) --")
            for sat in indian[:5]:
                print(f"\n    >>  {sat['name']}")
                print(f"       NORAD ID : {sat['norad_id']}")
                print(f"       Epoch    : {sat['epoch']}")
                print(f"       TLE L1   : {sat['tle_line1'][:50]}...")
                print(f"       TLE L2   : {sat['tle_line2'][:50]}...")

            # Quick constellation breakdown by keyword
            print(f"\n  -- Constellation Breakdown --")
            keyword_counts = {}
            for sat in indian:
                for kw, pat in zip(INDIAN_SAT_KEYWORDS, _INDIAN_SAT_PATTERNS):
                    if pat.search(sat["name"]):
                        keyword_counts[kw] = keyword_counts.get(kw, 0) + 1
                        break
            for kw, count in sorted(keyword_counts.items(), key=lambda x: -x[1]):
                print(f"    {kw:15s} : {count}")
        else:
            print("\n  [WARN] No Indian satellites matched! Check keyword filter.")

    except Exception as e:
        logger.error("Satellite ingestion FAILED: %s", e)
        print(f"\n  [FAIL] Satellite data collection failed: {e}")

    # -- 2. Space weather --------------------------------------------------
    print()
    print("-" * 52)
    print("  PHASE 2: Space Weather Telemetry")
    print("-" * 52)
    try:
        weather = get_space_weather(refresh=False)

        kp_count = len(weather.get("kp_index", []))
        sw_count = len(weather.get("solar_wind", []))
        sf_count = len(weather.get("solar_flux", []))

        print(f"\n  [KP ] Kp index readings   : {kp_count}")
        print(f"  [SW ] Solar wind readings  : {sw_count}")
        print(f"  [SF ] Solar flux readings  : {sf_count}")
        print(f"  [DSK] Cache used           : {weather['cache_used']}")
        print(f"  [CLK] Collected at         : {weather['collected_at']}")

        latest_kp = weather.get("latest_kp", {})
        if latest_kp:
            kp_val = latest_kp.get("kp_index") or latest_kp.get("kp") or latest_kp.get("Kp", "N/A")
            kp_time = latest_kp.get("time_tag", "N/A")
            print(f"\n  [KP ] Latest Kp Index     : {kp_val}")
            print(f"        Timestamp           : {kp_time}")

            try:
                kp_numeric = float(kp_val)
                if kp_numeric < 3:
                    print("        Status              : [GREEN] QUIET")
                elif kp_numeric < 5:
                    print("        Status              : [YELLOW] UNSETTLED")
                elif kp_numeric < 7:
                    print("        Status              : [ORANGE] STORM (G1-G2)")
                else:
                    print("        Status              : [RED] SEVERE STORM (G3+)")
            except (ValueError, TypeError):
                print("        Status              : [?] UNKNOWN")

    except Exception as e:
        logger.error("Space weather ingestion FAILED: %s", e)
        print(f"\n  [FAIL] Space weather collection failed: {e}")

    # -- 3. Cache status ---------------------------------------------------
    print()
    print("-" * 52)
    print("  CACHE STATUS")
    print("-" * 52)

    for label, fpath in [("Satellites", SATELLITES_FILE), ("Space Weather", SPACE_WEATHER_FILE)]:
        if fpath.exists():
            age_s = time.time() - fpath.stat().st_mtime
            age_min = age_s / 60
            size_kb = fpath.stat().st_size / 1024
            fresh = "[FRESH]" if age_s < CACHE_TTL_SECONDS else "[STALE]"
            print(f"\n  {label:15s} : {fpath}")
            print(f"                  : {size_kb:.1f} KB | age {age_min:.1f} min | {fresh}")
        else:
            print(f"\n  {label:15s} : [NOT FOUND]")

    print()
    print("=" * 72)
    print("  KALA AGNI data ingestion complete.")
    print("  Next: Run preprocessor -> ML engine -> Dashboard")
    print("=" * 72)
    print()


# --- ENTRY POINT ----------------------------------------------------------
if __name__ == "__main__":
    main()
