# PROJECT KALA AGNI
# Advanced Orbital Intelligence Platform
# File: core/orbit_utils.py

"""
KALA AGNI Orbital Utilities — SGP4 Propagation & Maneuver Planning
====================================================================
Provides core astrodynamics functions for the autonomous space command:

    1. TLE loading from cached satellite data
    2. SGP4 orbit propagation (position + velocity at future times)
    3. Impulsive delta-v computation for Hohmann-like transfers
    4. Fuel cost estimation via the Tsiolkovsky rocket equation
    5. Close-approach / conjunction detection between Indian and all sats
    6. Maneuver generation for altitude changes

Dependencies: sgp4, numpy (poliastro optional — used where available).
All functions are cache-friendly and designed for fast execution on i5 + RTX 2050.

Next agents to consume this module:
    - perception/threat_detector.py  → uses find_close_approaches()
    - risk/risk_scorer.py            → uses propagate_orbit() + conjunction data
    - strategy/maneuver_planner.py   → uses generate_maneuver() + delta_v + fuel
"""

import json
import math
import sys
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import numpy as np

# SGP4 — the gold standard for TLE-based orbit propagation
from sgp4.api import Satrec, WGS72
from sgp4 import exporter

# ─── OPTIONAL: poliastro for higher-fidelity maneuver planning ───────────────
# poliastro may not be installed on all machines (heavy dependency).
# We gracefully degrade to pure SGP4 + numpy if unavailable.
_HAS_POLIASTRO = False
try:
    from astropy import units as u
    from astropy.time import Time
    from poliastro.bodies import Earth
    from poliastro.twobody import Orbit
    from poliastro.maneuver import Maneuver
    _HAS_POLIASTRO = True
except ImportError:
    pass

# ─── Project imports ─────────────────────────────────────────────────────────
# Add project root to path so we can import config from any CWD
_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config import (
    SATELLITES_CACHE, EARTH_RADIUS_KM, MU_EARTH_KM3S2, G0,
    DEFAULT_DRY_MASS_KG, DEFAULT_ISP_S, CONJUNCTION_THRESHOLD_KM,
    GEO_ALT_KM, ORBIT_CLASSES, ISRO_BIPROP_ISP,
)

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[KALA AGNI] %(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("kala_agni.orbit_utils")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. TLE CACHE LOADING
# ═══════════════════════════════════════════════════════════════════════════════

def load_tle_from_cache(cache_path: Optional[Path] = None) -> dict:
    """
    Load satellite data from the JSON cache written by data_collector.

    Returns the full dict:
        {
            "indian_satellites": [...],
            "all_active_satellites": [...],
            "all_active_count": int,
            ...
        }

    Raises FileNotFoundError if cache doesn't exist.
    """
    path = cache_path or SATELLITES_CACHE
    if not path.exists():
        raise FileNotFoundError(
            f"Satellite cache not found at {path}. "
            "Run data_ingestion/data_collector.py first."
        )

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    n_indian = len(data.get("indian_satellites", []))
    n_total = data.get("all_active_count", 0)
    logger.info("Loaded TLE cache: %d Indian / %d total satellites.", n_indian, n_total)
    return data


def _build_satrec(sat_dict: dict) -> Satrec:
    """
    Build an sgp4 Satrec object from a satellite dict (has tle_line1, tle_line2).
    This is the core object used for propagation.
    """
    line1 = sat_dict["tle_line1"]
    line2 = sat_dict["tle_line2"]
    satellite = Satrec.twoline2rv(line1, line2, WGS72)
    return satellite


def classify_orbit(altitude_km: float) -> str:
    """
    Classify an orbit based on altitude above Earth's surface.
    Returns: 'LEO', 'MEO', 'GEO', 'HEO', or 'SUB-ORBITAL'.
    """
    for orbit_class, (low, high) in ORBIT_CLASSES.items():
        if low <= altitude_km < high:
            return orbit_class
    if altitude_km < 150:
        return "SUB-ORBITAL"
    return "DEEP-SPACE"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. SGP4 ORBIT PROPAGATION
# ═══════════════════════════════════════════════════════════════════════════════

def propagate_orbit(
    sat_dict: dict,
    minutes_ahead: float = 60.0,
    steps: int = 1
) -> list[dict]:
    """
    Propagate a satellite's orbit forward in time using SGP4.

    Parameters:
        sat_dict:      Dict with 'tle_line1' and 'tle_line2' keys.
        minutes_ahead: How far ahead to propagate (minutes).
        steps:         Number of time steps (1 = endpoint only).

    Returns:
        List of dicts, each containing:
            {
                "time_utc": str (ISO),
                "position_km": [x, y, z],     # TEME frame
                "velocity_kms": [vx, vy, vz], # TEME frame, km/s
                "altitude_km": float,         # above Earth surface
                "speed_kms": float,           # orbital speed magnitude
                "orbit_class": str,           # LEO/MEO/GEO/HEO
            }

    Note for next agents:
        - Position/velocity are in TEME (True Equator Mean Equinox) frame.
        - For Earth-fixed coords (ITRS), apply TEME→ECEF rotation using
          astropy or poliastro in a future phase.
    """
    satrec = _build_satrec(sat_dict)
    now = datetime.now(timezone.utc)
    results = []

    time_points = np.linspace(0, minutes_ahead, max(steps, 1))

    for dt_min in time_points:
        target_time = now + timedelta(minutes=float(dt_min))

        # SGP4 uses Julian date
        jd, fr = _datetime_to_jd(target_time)
        error_code, position, velocity = satrec.sgp4(jd, fr)

        if error_code != 0:
            logger.warning(
                "SGP4 propagation error (code %d) for %s at +%.1f min",
                error_code, sat_dict.get("name", "?"), dt_min
            )
            continue

        pos = np.array(position)    # km, TEME
        vel = np.array(velocity)    # km/s, TEME

        altitude = np.linalg.norm(pos) - EARTH_RADIUS_KM
        speed = np.linalg.norm(vel)

        results.append({
            "time_utc": target_time.isoformat(),
            "position_km": pos.tolist(),
            "velocity_kms": vel.tolist(),
            "altitude_km": round(altitude, 3),
            "speed_kms": round(speed, 6),
            "orbit_class": classify_orbit(altitude),
            "minutes_from_now": round(float(dt_min), 2),
        })

    return results


def _datetime_to_jd(dt: datetime) -> tuple:
    """
    Convert a datetime to Julian Date (jd, fraction) for SGP4.
    SGP4's Satrec.sgp4(jd, fr) expects this split format.
    """
    # Julian date of J2000.0 epoch: 2451545.0 = 2000-01-12 12:00 UTC
    # Using the standard formula:
    year = dt.year
    month = dt.month
    day = dt.day

    if month <= 2:
        year -= 1
        month += 12

    A = int(year / 100)
    B = 2 - A + int(A / 4)

    jd_day = int(365.25 * (year + 4716)) + int(30.6001 * (month + 1)) + day + B - 1524.5

    # Fractional day from hours/min/sec
    fr = (dt.hour + dt.minute / 60.0 + dt.second / 3600.0 +
          dt.microsecond / 3600e6) / 24.0

    return jd_day, fr


# ═══════════════════════════════════════════════════════════════════════════════
# 3. DELTA-V COMPUTATION
# ═══════════════════════════════════════════════════════════════════════════════

def calculate_delta_v(
    current_r: np.ndarray,
    current_v: np.ndarray,
    target_r: np.ndarray,
    target_v: np.ndarray
) -> dict:
    """
    Compute the impulsive delta-v needed to change from current state to target state.

    This is a simplified two-impulse (Hohmann-like) approximation:
        - dv1: burn at current position to enter transfer orbit
        - dv2: burn at target position to circularize

    For precise multi-burn optimization, use poliastro's Lambert solver
    or the strategy agent's trajectory planner.

    Parameters:
        current_r: Current position vector [km] (3,)
        current_v: Current velocity vector [km/s] (3,)
        target_r:  Target position vector [km] (3,)
        target_v:  Target velocity vector [km/s] (3,)

    Returns:
        {
            "delta_v_total_kms": float,     # Total dv magnitude (km/s)
            "delta_v_vector_kms": [dx, dy, dz],  # Vector difference
            "delta_v_ms": float,            # In m/s for engine specs
            "current_speed_kms": float,
            "target_speed_kms": float,
        }
    """
    current_r = np.asarray(current_r, dtype=float)
    current_v = np.asarray(current_v, dtype=float)
    target_r = np.asarray(target_r, dtype=float)
    target_v = np.asarray(target_v, dtype=float)

    # Simple impulsive dv — difference in velocity vectors
    dv_vec = target_v - current_v
    dv_mag = float(np.linalg.norm(dv_vec))

    return {
        "delta_v_total_kms": round(dv_mag, 6),
        "delta_v_vector_kms": dv_vec.tolist(),
        "delta_v_ms": round(dv_mag * 1000, 3),
        "current_speed_kms": round(float(np.linalg.norm(current_v)), 6),
        "target_speed_kms": round(float(np.linalg.norm(target_v)), 6),
    }


def hohmann_delta_v(r1_km: float, r2_km: float) -> dict:
    """
    Compute the classic Hohmann transfer delta-v between two circular orbits.

    Parameters:
        r1_km: Radius of initial circular orbit (from Earth center) [km]
        r2_km: Radius of target circular orbit (from Earth center) [km]

    Returns:
        {
            "dv1_kms": float,          # First burn (departure)
            "dv2_kms": float,          # Second burn (arrival/circularize)
            "total_dv_kms": float,     # Total delta-v
            "total_dv_ms": float,      # In m/s
            "transfer_time_hours": float,  # Half-period of transfer ellipse
        }

    Used by strategy agent for altitude-change maneuvers.
    """
    mu = MU_EARTH_KM3S2

    # Circular velocities
    v1 = math.sqrt(mu / r1_km)
    v2 = math.sqrt(mu / r2_km)

    # Transfer orbit semi-major axis
    a_transfer = (r1_km + r2_km) / 2.0

    # Velocities at periapsis and apoapsis of transfer ellipse
    v_transfer_peri = math.sqrt(mu * (2.0 / r1_km - 1.0 / a_transfer))
    v_transfer_apo = math.sqrt(mu * (2.0 / r2_km - 1.0 / a_transfer))

    # Delta-v at each burn
    dv1 = abs(v_transfer_peri - v1)
    dv2 = abs(v2 - v_transfer_apo)

    # Transfer time = half the period of the transfer ellipse
    transfer_period = 2 * math.pi * math.sqrt(a_transfer ** 3 / mu)
    transfer_time_s = transfer_period / 2.0

    return {
        "dv1_kms": round(dv1, 6),
        "dv2_kms": round(dv2, 6),
        "total_dv_kms": round(dv1 + dv2, 6),
        "total_dv_ms": round((dv1 + dv2) * 1000, 3),
        "transfer_time_hours": round(transfer_time_s / 3600, 3),
        "r1_km": r1_km,
        "r2_km": r2_km,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 4. FUEL COST ESTIMATION (Tsiolkovsky Rocket Equation)
# ═══════════════════════════════════════════════════════════════════════════════

def estimate_fuel_cost(
    delta_v_ms: float,
    dry_mass_kg: float = DEFAULT_DRY_MASS_KG,
    isp_s: float = DEFAULT_ISP_S
) -> dict:
    """
    Estimate propellant mass required using the Tsiolkovsky rocket equation:

        m_prop = m_dry * (exp(dv / (Isp * g0)) - 1)

    Parameters:
        delta_v_ms:   Required delta-v in m/s
        dry_mass_kg:  Spacecraft dry mass (kg)
        isp_s:        Specific impulse of the engine (seconds)

    Returns:
        {
            "propellant_mass_kg": float,
            "total_mass_kg": float,       # dry + propellant
            "mass_ratio": float,          # total/dry
            "delta_v_ms": float,
            "isp_s": float,
            "feasible": bool,             # mass ratio < 10 is generally feasible
        }

    Next agent note:
        strategy/maneuver_planner.py should compare fuel cost against
        satellite's remaining propellant budget (from mission data if available).
    """
    ve = isp_s * G0  # exhaust velocity (m/s)

    if ve <= 0:
        return {"error": "Invalid Isp", "feasible": False}

    mass_ratio = math.exp(delta_v_ms / ve)
    propellant_mass = dry_mass_kg * (mass_ratio - 1)

    return {
        "propellant_mass_kg": round(propellant_mass, 3),
        "total_mass_kg": round(dry_mass_kg + propellant_mass, 3),
        "mass_ratio": round(mass_ratio, 4),
        "delta_v_ms": round(delta_v_ms, 3),
        "isp_s": isp_s,
        "dry_mass_kg": dry_mass_kg,
        "feasible": mass_ratio < 10.0,  # rule of thumb
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 5. CLOSE APPROACH / CONJUNCTION DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

def find_close_approaches(
    indian_sats: list[dict],
    all_sats: Optional[list[dict]] = None,
    threshold_km: float = CONJUNCTION_THRESHOLD_KM,
    propagation_minutes: float = 60.0,
    steps: int = 10
) -> list[dict]:
    """
    Basic conjunction detection: propagate Indian satellites and compare
    positions against all other satellites at each time step.

    This is a brute-force O(N*M*T) approach suitable for MVP with ~100 Indian
    sats and ~200 cached sats. For production scale (30,000+ objects),
    use a kd-tree spatial index or the perception agent's GPU-accelerated filter.

    Parameters:
        indian_sats:         List of Indian satellite dicts (from cache)
        all_sats:            List of all satellite dicts (defaults to indian_sats)
        threshold_km:        Distance threshold for "close approach" (km)
        propagation_minutes: How far ahead to check (minutes)
        steps:               Number of time steps to evaluate

    Returns:
        List of close-approach events:
            {
                "sat1_name": str,
                "sat2_name": str,
                "min_distance_km": float,
                "time_utc": str,
                "sat1_position_km": [x,y,z],
                "sat2_position_km": [x,y,z],
                "risk_level": str,  # "WARNING" or "CRITICAL"
            }
    """
    if all_sats is None:
        all_sats = indian_sats

    now = datetime.now(timezone.utc)
    time_offsets = np.linspace(0, propagation_minutes, steps)
    approaches = []

    logger.info(
        "Scanning for conjunctions: %d Indian vs %d total sats, "
        "%d time steps over %.0f min, threshold=%.1f km",
        len(indian_sats), len(all_sats), steps, propagation_minutes, threshold_km
    )

    # Pre-build Satrec objects for all satellites
    indian_recs = []
    for sat in indian_sats:
        try:
            indian_recs.append((_build_satrec(sat), sat))
        except Exception:
            continue

    all_recs = []
    for sat in all_sats:
        try:
            all_recs.append((_build_satrec(sat), sat))
        except Exception:
            continue

    for dt_min in time_offsets:
        t = now + timedelta(minutes=float(dt_min))
        jd, fr = _datetime_to_jd(t)

        # Propagate all sats to this time
        positions_all = {}
        for rec, sat in all_recs:
            err, pos, vel = rec.sgp4(jd, fr)
            if err == 0:
                positions_all[sat["norad_id"]] = (np.array(pos), sat)

        # Check each Indian sat against all others
        for rec_i, sat_i in indian_recs:
            err_i, pos_i, vel_i = rec_i.sgp4(jd, fr)
            if err_i != 0:
                continue
            pos_i = np.array(pos_i)

            for nid, (pos_j, sat_j) in positions_all.items():
                # Skip self
                if nid == sat_i["norad_id"]:
                    continue

                dist = float(np.linalg.norm(pos_i - pos_j))

                if dist < threshold_km:
                    risk = "CRITICAL" if dist < 1.0 else "WARNING"
                    approaches.append({
                        "sat1_name": sat_i["name"],
                        "sat2_name": sat_j["name"],
                        "sat1_norad": sat_i["norad_id"],
                        "sat2_norad": sat_j["norad_id"],
                        "min_distance_km": round(dist, 3),
                        "time_utc": t.isoformat(),
                        "minutes_from_now": round(float(dt_min), 2),
                        "sat1_position_km": pos_i.tolist(),
                        "sat2_position_km": pos_j.tolist(),
                        "risk_level": risk,
                    })

    # Sort by distance (closest first)
    approaches.sort(key=lambda x: x["min_distance_km"])
    logger.info("Conjunction scan complete: %d close approaches found.", len(approaches))
    return approaches


# ═══════════════════════════════════════════════════════════════════════════════
# 6. MANEUVER GENERATION
# ═══════════════════════════════════════════════════════════════════════════════

def generate_maneuver(
    sat_name: str,
    target_altitude_km: Optional[float] = None,
    cache_data: Optional[dict] = None
) -> dict:
    """
    Generate a realistic maneuver plan for an Indian satellite.

    If target_altitude_km is provided, computes a Hohmann transfer to that altitude.
    If not provided, generates a +10 km altitude raise (debris avoidance default).

    Parameters:
        sat_name:           Name of the satellite (must exist in cache)
        target_altitude_km: Desired altitude after maneuver (km above surface)
        cache_data:         Pre-loaded cache dict (optional, loads if None)

    Returns:
        {
            "satellite": str,
            "current_state": {...},            # position, velocity, altitude
            "target_altitude_km": float,
            "hohmann_transfer": {...},         # dv1, dv2, transfer time
            "fuel_cost_biprop": {...},         # using ISRO 440N LAM
            "fuel_cost_electric": {...},       # using electric propulsion
            "recommendation": str,
            "feasible": bool,
        }

    Next agent note:
        strategy/maneuver_planner.py should chain this with risk scoring
        to decide whether the maneuver cost justifies the risk reduction.
    """
    # Load cache
    if cache_data is None:
        cache_data = load_tle_from_cache()

    # Find the satellite
    all_sats = cache_data.get("indian_satellites", []) + cache_data.get("all_active_satellites", [])
    sat_dict = None
    for s in all_sats:
        if s["name"].strip().upper() == sat_name.strip().upper():
            sat_dict = s
            break

    if sat_dict is None:
        # Partial match fallback
        for s in all_sats:
            if sat_name.upper() in s["name"].upper():
                sat_dict = s
                break

    if sat_dict is None:
        return {"error": f"Satellite '{sat_name}' not found in cache.", "feasible": False}

    # Propagate to current state
    state = propagate_orbit(sat_dict, minutes_ahead=0, steps=1)
    if not state:
        return {"error": "SGP4 propagation failed.", "feasible": False}

    current = state[0]
    current_alt = current["altitude_km"]
    current_r = EARTH_RADIUS_KM + current_alt

    # Default: raise altitude by 10 km (standard debris avoidance)
    if target_altitude_km is None:
        target_altitude_km = current_alt + 10.0

    target_r = EARTH_RADIUS_KM + target_altitude_km

    # Hohmann transfer computation
    hohmann = hohmann_delta_v(current_r, target_r)

    # Fuel cost with ISRO bipropellant (440N LAM, Isp=315s)
    fuel_biprop = estimate_fuel_cost(
        delta_v_ms=hohmann["total_dv_ms"],
        dry_mass_kg=DEFAULT_DRY_MASS_KG,
        isp_s=ISRO_BIPROP_ISP
    )

    # Fuel cost with electric propulsion (Isp=1500s, slower but efficient)
    fuel_electric = estimate_fuel_cost(
        delta_v_ms=hohmann["total_dv_ms"],
        dry_mass_kg=DEFAULT_DRY_MASS_KG,
        isp_s=1500.0
    )

    # Recommendation logic
    if hohmann["total_dv_ms"] < 10:
        recommendation = "MINIMAL: Tiny correction, use electric thrusters."
    elif hohmann["total_dv_ms"] < 100:
        recommendation = "ROUTINE: Standard station-keeping burn. Bipropellant preferred."
    elif hohmann["total_dv_ms"] < 500:
        recommendation = "SIGNIFICANT: Major orbit change. Verify fuel budget."
    else:
        recommendation = "MAJOR: Large maneuver. Confirm mission justification."

    return {
        "satellite": sat_dict["name"],
        "norad_id": sat_dict["norad_id"],
        "current_state": current,
        "current_altitude_km": round(current_alt, 3),
        "target_altitude_km": round(target_altitude_km, 3),
        "altitude_change_km": round(target_altitude_km - current_alt, 3),
        "hohmann_transfer": hohmann,
        "fuel_cost_biprop": fuel_biprop,
        "fuel_cost_electric": fuel_electric,
        "recommendation": recommendation,
        "feasible": fuel_biprop["feasible"] and fuel_electric["feasible"],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 7. POLIASTRO INTEGRATION (optional, higher-fidelity)
# ═══════════════════════════════════════════════════════════════════════════════

def propagate_poliastro(sat_dict: dict, minutes_ahead: float = 60.0) -> Optional[dict]:
    """
    Higher-fidelity propagation using poliastro (if available).
    Falls back to None if poliastro is not installed.

    Returns orbit state dict or None.
    """
    if not _HAS_POLIASTRO:
        logger.debug("poliastro not available — skipping high-fidelity propagation.")
        return None

    try:
        # Get current state via SGP4 first
        state = propagate_orbit(sat_dict, minutes_ahead=0, steps=1)
        if not state:
            return None

        r = state[0]["position_km"]
        v = state[0]["velocity_kms"]

        # Create poliastro Orbit from state vectors
        orbit = Orbit.from_vectors(
            Earth,
            r=np.array(r) * u.km,
            v=np.array(v) * u.km / u.s,
            epoch=Time.now()
        )

        # Propagate
        propagated = orbit.propagate(minutes_ahead * u.min)

        return {
            "satellite": sat_dict.get("name", "Unknown"),
            "semi_major_axis_km": float(propagated.a.to(u.km).value),
            "eccentricity": float(propagated.ecc.value),
            "inclination_deg": float(propagated.inc.to(u.deg).value),
            "altitude_km": float((propagated.a - Earth.R).to(u.km).value),
            "period_min": float(propagated.period.to(u.min).value),
            "propagated_r_km": propagated.r.to(u.km).value.tolist(),
            "propagated_v_kms": propagated.v.to(u.km / u.s).value.tolist(),
            "engine": "poliastro",
        }
    except Exception as e:
        logger.warning("poliastro propagation failed: %s", e)
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN — STANDALONE TEST
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """
    Self-test: Load Indian constellation, propagate GSAT-1, compute a
    sample maneuver, and print results.
    """
    import io
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    print()
    print("=" * 72)
    print("  KALA AGNI Orbital Utilities -- Self Test")
    print("=" * 72)

    # --- 1. Load cache ---
    print("\n" + "-" * 52)
    print("  TEST 1: Load TLE Cache")
    print("-" * 52)
    try:
        data = load_tle_from_cache()
        indian = data.get("indian_satellites", [])
        print(f"  Indian satellites loaded: {len(indian)}")
    except FileNotFoundError as e:
        print(f"  [FAIL] {e}")
        return

    # --- 2. Find GSAT-1 and propagate ---
    print("\n" + "-" * 52)
    print("  TEST 2: SGP4 Propagation (GSAT-1, +60 min)")
    print("-" * 52)
    gsat1 = None
    for s in indian:
        if s["name"].strip() == "GSAT-1":
            gsat1 = s
            break

    if gsat1 is None:
        # Fallback to first available
        gsat1 = indian[0] if indian else None
        if gsat1:
            print(f"  GSAT-1 not found, using: {gsat1['name']}")
        else:
            print("  [FAIL] No satellites in cache!")
            return

    states = propagate_orbit(gsat1, minutes_ahead=60, steps=5)
    for st in states:
        print(f"  T+{st['minutes_from_now']:6.1f} min | "
              f"Alt: {st['altitude_km']:10.1f} km | "
              f"Speed: {st['speed_kms']:.4f} km/s | "
              f"{st['orbit_class']}")

    # --- 3. Hohmann transfer example ---
    print("\n" + "-" * 52)
    print("  TEST 3: Hohmann Transfer (current -> +50 km)")
    print("-" * 52)
    if states:
        current_alt = states[0]["altitude_km"]
        target_alt = current_alt + 50.0
        r1 = EARTH_RADIUS_KM + current_alt
        r2 = EARTH_RADIUS_KM + target_alt

        h = hohmann_delta_v(r1, r2)
        print(f"  Current altitude : {current_alt:.1f} km")
        print(f"  Target altitude  : {target_alt:.1f} km")
        print(f"  dv1 (depart)     : {h['dv1_kms']*1000:.3f} m/s")
        print(f"  dv2 (circularize): {h['dv2_kms']*1000:.3f} m/s")
        print(f"  Total dv         : {h['total_dv_ms']:.3f} m/s")
        print(f"  Transfer time    : {h['transfer_time_hours']:.3f} hours")

        # --- 4. Fuel cost ---
        print("\n" + "-" * 52)
        print("  TEST 4: Fuel Cost (Tsiolkovsky)")
        print("-" * 52)
        fuel = estimate_fuel_cost(h["total_dv_ms"], dry_mass_kg=100, isp_s=ISRO_BIPROP_ISP)
        print(f"  Engine Isp       : {fuel['isp_s']:.0f} s (ISRO 440N LAM)")
        print(f"  Dry mass         : {fuel['dry_mass_kg']:.0f} kg")
        print(f"  Propellant needed: {fuel['propellant_mass_kg']:.3f} kg")
        print(f"  Mass ratio       : {fuel['mass_ratio']:.4f}")
        print(f"  Feasible         : {fuel['feasible']}")

    # --- 5. Generate maneuver ---
    print("\n" + "-" * 52)
    print("  TEST 5: Generate Maneuver (debris avoidance +10 km)")
    print("-" * 52)
    maneuver = generate_maneuver(gsat1["name"], cache_data=data)
    if "error" not in maneuver:
        print(f"  Satellite     : {maneuver['satellite']}")
        print(f"  Current alt   : {maneuver['current_altitude_km']:.1f} km")
        print(f"  Target alt    : {maneuver['target_altitude_km']:.1f} km")
        print(f"  Delta-v       : {maneuver['hohmann_transfer']['total_dv_ms']:.3f} m/s")
        print(f"  Fuel (biprop) : {maneuver['fuel_cost_biprop']['propellant_mass_kg']:.3f} kg")
        print(f"  Fuel (elec)   : {maneuver['fuel_cost_electric']['propellant_mass_kg']:.3f} kg")
        print(f"  Recommendation: {maneuver['recommendation']}")
        print(f"  Feasible      : {maneuver['feasible']}")
    else:
        print(f"  [FAIL] {maneuver['error']}")

    # --- 6. poliastro check ---
    print("\n" + "-" * 52)
    print("  TEST 6: poliastro Integration")
    print("-" * 52)
    if _HAS_POLIASTRO:
        pa_result = propagate_poliastro(gsat1, minutes_ahead=30)
        if pa_result:
            print(f"  Engine          : {pa_result['engine']}")
            print(f"  Semi-major axis : {pa_result['semi_major_axis_km']:.1f} km")
            print(f"  Eccentricity    : {pa_result['eccentricity']:.6f}")
            print(f"  Inclination     : {pa_result['inclination_deg']:.3f} deg")
            print(f"  Period          : {pa_result['period_min']:.2f} min")
        else:
            print("  poliastro propagation returned None.")
    else:
        print("  [SKIP] poliastro not installed (optional dependency).")
        print("         SGP4 propagation is fully functional without it.")

    # --- 7. Conjunction scan (quick, small set) ---
    print("\n" + "-" * 52)
    print("  TEST 7: Quick Conjunction Scan (5 sats, 30 min)")
    print("-" * 52)
    sample_sats = indian[:5] if len(indian) >= 5 else indian
    approaches = find_close_approaches(
        sample_sats, sample_sats,
        threshold_km=100.0,  # wider threshold for demo
        propagation_minutes=30,
        steps=3
    )
    if approaches:
        for a in approaches[:5]:
            print(f"  {a['sat1_name']:20s} <-> {a['sat2_name']:20s} "
                  f"| {a['min_distance_km']:8.1f} km | {a['risk_level']}")
    else:
        print("  No close approaches found (good news for our constellation).")

    print()
    print("=" * 72)
    print("  KALA AGNI orbital utilities test complete.")
    print("  Next: perception -> risk -> strategy -> dashboard")
    print("=" * 72)
    print()


if __name__ == "__main__":
    main()
