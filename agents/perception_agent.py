# PROJECT KALA AGNI
# Advanced Orbital Intelligence Platform
# File: agents/perception_agent.py

"""
KALA AGNI Perception Agent -- Constellation Observer
================================================================
First agent in the OODA (Observe-Orient-Decide-Act) loop.
Builds a rich, real-time picture of the Indian space constellation by:

    1. Loading cached satellite TLEs + space weather telemetry
    2. Batch-propagating all Indian satellites to current positions via SGP4
    3. Classifying constellation health (GEO/MEO/LEO breakdown)
    4. Evaluating space weather impact on orbital operations
    5. Generating a natural-language perception summary for the Command Brain

Consumers of this agent's output:
    - agents/risk_agent.py       -> feeds get_current_state() into risk scoring
    - agents/strategy_agent.py   -> uses perception to decide on maneuvers
    - dashboard/app.py           -> visualize_constellation_status() powers the UI
    - agents/command_brain.py    -> reads generate_perception_summary() for decisions

Performance target: Full perception cycle < 2 seconds on i5 + 16 GB RAM.
"""

import sys
import time
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from collections import Counter

import numpy as np

# ---------------------------------------------------------------------------
# Project root on sys.path so imports work from any CWD
# ---------------------------------------------------------------------------
_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config import (
    SATELLITES_CACHE, SPACE_WEATHER_CACHE, EARTH_RADIUS_KM,
    CACHE_TTL_SECONDS, CONJUNCTION_THRESHOLD_KM,
    INDIAN_SAT_KEYWORDS, ORBIT_CLASSES, APP_TITLE,
)
from core.orbit_utils import (
    load_tle_from_cache, propagate_orbit, classify_orbit,
    find_close_approaches, _build_satrec, _datetime_to_jd,
)
from data_ingestion.data_collector import (
    get_indian_constellation, get_space_weather,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="[KALA AGNI] %(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("kala_agni.perception")

# ---------------------------------------------------------------------------
# Perception cache TTL -- 5 minutes (much shorter than data cache because
# orbital positions change fast, but re-propagating 116 sats is still cheap)
# ---------------------------------------------------------------------------
PERCEPTION_TTL_SECONDS = 300  # 5 minutes


class PerceptionAgent:
    """
    The Perception Agent observes the Indian space constellation in real-time
    and builds a situational awareness picture for downstream agents.

    Usage:
        agent = PerceptionAgent()
        state = agent.get_current_state()
        summary = agent.generate_perception_summary()
    """

    def __init__(self, refresh_data: bool = False):
        """
        Initialize the perception agent by loading satellite and weather data.

        Parameters:
            refresh_data: If True, force-refresh from Celestrak/NOAA
                          (otherwise uses cached data if fresh).
        """
        logger.info("Perception Agent initializing...")
        t0 = time.perf_counter()

        # --- Load satellite constellation ---
        try:
            self._sat_cache = load_tle_from_cache()
            self.indian_sats = self._sat_cache.get("indian_satellites", [])
            self.all_sats = self._sat_cache.get("all_active_satellites", [])
        except FileNotFoundError:
            logger.warning("No satellite cache found. Attempting live fetch...")
            self.indian_sats = get_indian_constellation(refresh=refresh_data)
            self._sat_cache = load_tle_from_cache()
            self.all_sats = self._sat_cache.get("all_active_satellites", [])

        # --- Load space weather ---
        try:
            self.space_weather = get_space_weather(refresh=refresh_data)
        except Exception as e:
            logger.error("Space weather load failed: %s", e)
            self.space_weather = {}

        # --- Internal perception cache ---
        self._perception_cache = None
        self._perception_cache_time = None

        elapsed = time.perf_counter() - t0
        logger.info(
            "Perception Agent ready: %d Indian sats, %d total sats (%.2f s)",
            len(self.indian_sats), len(self.all_sats), elapsed
        )

    # ===================================================================
    # CORE: Full constellation state snapshot
    # ===================================================================

    def get_current_state(self, force_refresh: bool = False) -> dict:
        """
        Build and return the complete perception state of the Indian constellation.

        Returns a rich dict consumed by Risk Agent, Strategy Agent, and Dashboard:
            {
                "timestamp": str,
                "indian_constellation": [...],         # each sat with current pos/vel
                "total_indian_sats": int,
                "propagation_failures": int,
                "constellation_health": {...},         # GEO/MEO/LEO breakdown
                "space_weather_impact": {...},         # Kp, storm, flux
                "active_maneuvers_needed": int,        # placeholder
                "perception_cycle_ms": float,
            }

        Uses a 5-minute internal cache to avoid redundant SGP4 propagation.
        """
        # --- Check perception cache ---
        if (not force_refresh
                and self._perception_cache is not None
                and self._perception_cache_time is not None):
            age = time.time() - self._perception_cache_time
            if age < PERCEPTION_TTL_SECONDS:
                logger.debug("Perception cache hit (age %.1f s).", age)
                return self._perception_cache

        t0 = time.perf_counter()
        now = datetime.now(timezone.utc)

        # --- Batch propagate all Indian satellites to NOW ---
        constellation_state = self._batch_propagate(self.indian_sats)

        # --- Classify constellation health ---
        health = self._compute_constellation_health(constellation_state)

        # --- Evaluate space weather impact ---
        weather_impact = self._evaluate_space_weather()

        # --- Placeholder: maneuvers needed (Risk Agent will populate this) ---
        # For now, flag any satellite with altitude < 300 km (LEO drag risk)
        maneuvers_needed = sum(
            1 for s in constellation_state
            if s.get("altitude_km", 99999) < 300 and s.get("orbit_class") == "LEO"
        )

        elapsed_ms = (time.perf_counter() - t0) * 1000

        state = {
            "timestamp": now.isoformat(),
            "indian_constellation": constellation_state,
            "total_indian_sats": len(self.indian_sats),
            "propagated_count": len(constellation_state),
            "propagation_failures": len(self.indian_sats) - len(constellation_state),
            "constellation_health": health,
            "space_weather_impact": weather_impact,
            "active_maneuvers_needed": maneuvers_needed,
            "perception_cycle_ms": round(elapsed_ms, 2),
        }

        # --- Update perception cache ---
        self._perception_cache = state
        self._perception_cache_time = time.time()

        logger.info(
            "Perception cycle complete: %d sats propagated in %.1f ms.",
            len(constellation_state), elapsed_ms
        )
        return state

    # ===================================================================
    # BATCH PROPAGATION -- fast SGP4 for all Indian sats
    # ===================================================================

    def _batch_propagate(self, satellites: list[dict]) -> list[dict]:
        """
        Propagate all satellites to the current time using SGP4.
        Optimized for speed: builds Satrec objects once, single JD computation.

        Returns list of enriched sat dicts with current position/velocity.
        """
        now = datetime.now(timezone.utc)
        jd, fr = _datetime_to_jd(now)
        results = []

        for sat in satellites:
            try:
                satrec = _build_satrec(sat)
                error_code, position, velocity = satrec.sgp4(jd, fr)

                if error_code != 0:
                    logger.debug(
                        "SGP4 error %d for %s -- skipping.",
                        error_code, sat.get("name", "?")
                    )
                    continue

                pos = np.array(position)
                vel = np.array(velocity)
                altitude = float(np.linalg.norm(pos) - EARTH_RADIUS_KM)
                speed = float(np.linalg.norm(vel))

                results.append({
                    "name": sat["name"],
                    "norad_id": sat["norad_id"],
                    "catalog_number": sat.get("catalog_number", sat["norad_id"]),
                    "position_km": pos.tolist(),
                    "velocity_kms": vel.tolist(),
                    "altitude_km": round(altitude, 3),
                    "speed_kms": round(speed, 6),
                    "orbit_class": classify_orbit(altitude),
                    "epoch": sat.get("epoch", ""),
                    "time_utc": now.isoformat(),
                })

            except Exception as e:
                logger.debug("Failed to propagate %s: %s", sat.get("name", "?"), e)
                continue

        return results

    # ===================================================================
    # CONSTELLATION HEALTH -- orbit class breakdown + anomaly flags
    # ===================================================================

    def _compute_constellation_health(self, constellation: list[dict]) -> dict:
        """
        Analyze the constellation by orbit class (GEO/MEO/LEO/HEO),
        keyword group, and flag any anomalies.

        Returns:
            {
                "by_orbit_class": {"GEO": 45, "MEO": 12, "LEO": 30, ...},
                "by_keyword": {"GSAT": 59, "IRNSS": 10, ...},
                "mean_altitude_km": float,
                "min_altitude_km": float,
                "max_altitude_km": float,
                "anomalies": [...],    # sats with unexpected orbit class
                "overall_status": str, # "NOMINAL" | "DEGRADED" | "CRITICAL"
            }
        """
        if not constellation:
            return {
                "by_orbit_class": {},
                "by_keyword": {},
                "mean_altitude_km": 0,
                "min_altitude_km": 0,
                "max_altitude_km": 0,
                "anomalies": [],
                "overall_status": "CRITICAL",
            }

        # Orbit class distribution
        orbit_counts = Counter(s["orbit_class"] for s in constellation)

        # Keyword group distribution
        keyword_counts = Counter()
        for s in constellation:
            name_upper = s["name"].upper()
            for kw in INDIAN_SAT_KEYWORDS:
                if kw in name_upper:
                    keyword_counts[kw] += 1
                    break

        # Altitude statistics
        altitudes = [s["altitude_km"] for s in constellation]
        mean_alt = float(np.mean(altitudes))
        min_alt = float(np.min(altitudes))
        max_alt = float(np.max(altitudes))

        # Anomaly detection: flag sats in unexpected orbit classes
        anomalies = []
        for s in constellation:
            # GEO sats (GSAT, INSAT) should be near 35,786 km
            if any(kw in s["name"].upper() for kw in ["GSAT", "INSAT"]):
                if s["orbit_class"] not in ("GEO", "HEO"):
                    # Some GSAT are in transfer orbits -- not truly anomalous
                    # but worth flagging for awareness
                    if s["altitude_km"] < 30000:
                        anomalies.append({
                            "satellite": s["name"],
                            "expected_class": "GEO",
                            "actual_class": s["orbit_class"],
                            "altitude_km": s["altitude_km"],
                            "flag": "POSSIBLE_TRANSFER_ORBIT",
                        })

            # LEO sats below 250 km are in danger of re-entry
            if s["altitude_km"] < 250 and s["orbit_class"] == "LEO":
                anomalies.append({
                    "satellite": s["name"],
                    "expected_class": "LEO",
                    "actual_class": "DECAY_RISK",
                    "altitude_km": s["altitude_km"],
                    "flag": "LOW_ALTITUDE_WARNING",
                })

        # Overall status
        if any(a["flag"] == "LOW_ALTITUDE_WARNING" for a in anomalies):
            overall = "DEGRADED"
        elif len(anomalies) > len(constellation) * 0.1:
            overall = "DEGRADED"
        else:
            overall = "NOMINAL"

        return {
            "by_orbit_class": dict(orbit_counts.most_common()),
            "by_keyword": dict(keyword_counts.most_common()),
            "mean_altitude_km": round(mean_alt, 1),
            "min_altitude_km": round(min_alt, 1),
            "max_altitude_km": round(max_alt, 1),
            "anomalies": anomalies,
            "anomaly_count": len(anomalies),
            "overall_status": overall,
        }

    # ===================================================================
    # SPACE WEATHER IMPACT ASSESSMENT
    # ===================================================================

    def _evaluate_space_weather(self) -> dict:
        """
        Evaluate space weather conditions and their impact on the constellation.

        Assesses:
            - Geomagnetic storms (Kp index) -> atmospheric drag on LEO
            - Solar flux (F10.7) -> radiation environment
            - Solar wind -> magnetosphere compression

        Returns:
            {
                "kp_index": float,
                "kp_timestamp": str,
                "storm_level": str,
                "storm_description": str,
                "solar_flux_sfu": float,
                "solar_wind_speed_kms": float,
                "leo_drag_risk": str,       # "LOW" | "MODERATE" | "HIGH" | "SEVERE"
                "radiation_risk": str,
                "overall_impact": str,
            }
        """
        # --- Kp index ---
        kp_data = self.space_weather.get("kp_index", [])
        latest_kp = self.space_weather.get("latest_kp", {})

        kp_val = 0.0
        kp_time = "N/A"
        if latest_kp:
            raw_kp = (latest_kp.get("kp_index")
                      or latest_kp.get("kp")
                      or latest_kp.get("Kp")
                      or 0)
            try:
                kp_val = float(raw_kp)
            except (ValueError, TypeError):
                kp_val = 0.0
            kp_time = latest_kp.get("time_tag", "N/A")

        # Classify storm level (NOAA G-scale)
        if kp_val < 3:
            storm_level = "QUIET"
            storm_desc = "No geomagnetic storm. Nominal operations."
        elif kp_val < 5:
            storm_level = "UNSETTLED"
            storm_desc = "Minor geomagnetic activity. Monitor LEO drag."
        elif kp_val < 6:
            storm_level = "G1_MINOR"
            storm_desc = "G1 minor storm. Increased drag on LEO assets below 500 km."
        elif kp_val < 7:
            storm_level = "G2_MODERATE"
            storm_desc = "G2 moderate storm. Drag correction burns may be needed for LEO."
        elif kp_val < 8:
            storm_level = "G3_STRONG"
            storm_desc = "G3 strong storm. Surface charging risk on GEO sats. LEO drag elevated."
        elif kp_val < 9:
            storm_level = "G4_SEVERE"
            storm_desc = "G4 severe storm! Possible single-event upsets. Prepare contingency maneuvers."
        else:
            storm_level = "G5_EXTREME"
            storm_desc = "G5 EXTREME storm! All sats at risk. Activate emergency protocols."

        # --- LEO drag risk (directly tied to Kp) ---
        if kp_val < 3:
            leo_drag = "LOW"
        elif kp_val < 5:
            leo_drag = "MODERATE"
        elif kp_val < 7:
            leo_drag = "HIGH"
        else:
            leo_drag = "SEVERE"

        # --- Solar flux (F10.7) ---
        flux_data = self.space_weather.get("solar_flux", [])
        solar_flux_sfu = 0.0
        if flux_data and isinstance(flux_data, list) and len(flux_data) > 0:
            latest_flux = flux_data[-1] if isinstance(flux_data[-1], dict) else {}
            try:
                solar_flux_sfu = float(
                    latest_flux.get("flux") or latest_flux.get("f107") or 0
                )
            except (ValueError, TypeError):
                solar_flux_sfu = 0.0

        # Radiation risk from solar flux
        if solar_flux_sfu < 100:
            radiation_risk = "LOW"
        elif solar_flux_sfu < 150:
            radiation_risk = "MODERATE"
        elif solar_flux_sfu < 200:
            radiation_risk = "HIGH"
        else:
            radiation_risk = "SEVERE"

        # --- Solar wind speed ---
        wind_data = self.space_weather.get("solar_wind", [])
        wind_speed = 0.0
        if wind_data and isinstance(wind_data, list) and len(wind_data) > 0:
            latest_wind = wind_data[-1] if isinstance(wind_data[-1], dict) else {}
            try:
                wind_speed = float(
                    latest_wind.get("proton_speed")
                    or latest_wind.get("speed")
                    or latest_wind.get("bulk_speed")
                    or 0
                )
            except (ValueError, TypeError):
                wind_speed = 0.0

        # --- Overall impact ---
        risk_scores = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "SEVERE": 3}
        max_risk = max(
            risk_scores.get(leo_drag, 0),
            risk_scores.get(radiation_risk, 0),
        )
        overall = {0: "NOMINAL", 1: "ELEVATED", 2: "HIGH", 3: "SEVERE"}[max_risk]

        return {
            "kp_index": kp_val,
            "kp_timestamp": kp_time,
            "kp_readings_available": len(kp_data),
            "storm_level": storm_level,
            "storm_description": storm_desc,
            "solar_flux_sfu": solar_flux_sfu,
            "solar_wind_speed_kms": round(wind_speed, 1),
            "leo_drag_risk": leo_drag,
            "radiation_risk": radiation_risk,
            "overall_impact": overall,
        }

    # ===================================================================
    # NATURAL LANGUAGE PERCEPTION SUMMARY
    # ===================================================================

    def generate_perception_summary(self, state: Optional[dict] = None) -> str:
        """
        Generate a natural English summary suitable for the Command Brain agent.

        This is the "spoken brief" a human mission director would give:
            - Constellation status
            - Space weather conditions
            - Any anomalies or threats
            - Recommended posture

        Returns a multi-line string.
        """
        if state is None:
            state = self.get_current_state()

        health = state["constellation_health"]
        weather = state["space_weather_impact"]
        ts = state["timestamp"]

        # --- Header ---
        lines = [
            f"KALA AGNI PERCEPTION REPORT -- {ts[:19]} UTC",
            "=" * 56,
            "",
        ]

        # --- Constellation ---
        lines.append(
            f"CONSTELLATION STATUS: {health['overall_status']}"
        )
        lines.append(
            f"  {state['propagated_count']} of {state['total_indian_sats']} "
            f"Indian satellites successfully tracked."
        )
        if state["propagation_failures"] > 0:
            lines.append(
                f"  WARNING: {state['propagation_failures']} satellites "
                f"failed SGP4 propagation (stale TLE data)."
            )

        # Orbit class summary
        orbit = health.get("by_orbit_class", {})
        if orbit:
            parts = [f"{cls}: {n}" for cls, n in orbit.items()]
            lines.append(f"  Orbit distribution: {', '.join(parts)}")

        lines.append(
            f"  Altitude range: {health['min_altitude_km']:.0f} km "
            f"to {health['max_altitude_km']:.0f} km "
            f"(mean: {health['mean_altitude_km']:.0f} km)"
        )

        # Anomalies
        if health["anomalies"]:
            lines.append(f"  ANOMALIES DETECTED: {health['anomaly_count']}")
            for a in health["anomalies"][:3]:
                lines.append(
                    f"    - {a['satellite']}: {a['flag']} "
                    f"(alt {a['altitude_km']:.0f} km, expected {a['expected_class']})"
                )
        lines.append("")

        # --- Space Weather ---
        lines.append(f"SPACE WEATHER: {weather['overall_impact']}")
        lines.append(
            f"  Kp Index: {weather['kp_index']:.1f} ({weather['storm_level']})"
        )
        lines.append(f"  {weather['storm_description']}")
        if weather["solar_flux_sfu"] > 0:
            lines.append(
                f"  Solar Flux (F10.7): {weather['solar_flux_sfu']:.1f} SFU "
                f"-- Radiation risk: {weather['radiation_risk']}"
            )
        if weather["solar_wind_speed_kms"] > 0:
            lines.append(
                f"  Solar Wind: {weather['solar_wind_speed_kms']:.0f} km/s"
            )
        lines.append(f"  LEO Drag Risk: {weather['leo_drag_risk']}")
        lines.append("")

        # --- Maneuvers ---
        if state["active_maneuvers_needed"] > 0:
            lines.append(
                f"MANEUVERS NEEDED: {state['active_maneuvers_needed']} "
                f"satellite(s) require orbital adjustment."
            )
        else:
            lines.append("MANEUVERS NEEDED: None at this time.")
        lines.append("")

        # --- Recommended posture ---
        if weather["overall_impact"] == "SEVERE":
            posture = "ALERT: Activate emergency watch. Prepare contingency maneuvers."
        elif weather["overall_impact"] == "HIGH":
            posture = "HEIGHTENED: Increase monitoring cadence. Pre-plan avoidance burns."
        elif weather["overall_impact"] == "ELEVATED":
            posture = "WATCH: Monitor space weather trends. Routine operations continue."
        else:
            posture = "NORMAL: All systems nominal. Routine monitoring active."

        lines.append(f"RECOMMENDED POSTURE: {posture}")
        lines.append("")
        lines.append(
            f"Perception cycle completed in {state['perception_cycle_ms']:.1f} ms."
        )

        return "\n".join(lines)

    # ===================================================================
    # UI VISUALIZATION DATA
    # ===================================================================

    def visualize_constellation_status(self, state: Optional[dict] = None) -> dict:
        """
        Return a simplified dict for the Streamlit dashboard UI.

        Structured for easy consumption by Plotly charts and st.metric widgets.
        The dashboard will call this and render without further processing.

        Returns:
            {
                "kpi_cards": [...],        # list of {label, value, delta, color}
                "orbit_distribution": {},  # for pie/donut chart
                "keyword_breakdown": {},   # for bar chart
                "altitude_histogram_data": [...],  # raw altitudes for histogram
                "weather_gauges": {...},   # for gauge widgets
                "anomaly_table": [...],    # for st.dataframe
                "satellite_table": [...],  # for constellation viewer
            }

        Next agent note:
            dashboard/app.py should call agent.visualize_constellation_status()
            in its main render loop and map each key to a Streamlit widget.
        """
        if state is None:
            state = self.get_current_state()

        health = state["constellation_health"]
        weather = state["space_weather_impact"]

        # --- KPI cards for top-of-dashboard metrics ---
        kpi_cards = [
            {
                "label": "Indian Satellites Tracked",
                "value": state["propagated_count"],
                "delta": f"{state['total_indian_sats']} total",
                "color": "gold",
            },
            {
                "label": "Constellation Status",
                "value": health["overall_status"],
                "delta": f"{health['anomaly_count']} anomalies",
                "color": "green" if health["overall_status"] == "NOMINAL" else "orange",
            },
            {
                "label": "Kp Index",
                "value": f"{weather['kp_index']:.1f}",
                "delta": weather["storm_level"],
                "color": (
                    "green" if weather["kp_index"] < 3
                    else "yellow" if weather["kp_index"] < 5
                    else "orange" if weather["kp_index"] < 7
                    else "red"
                ),
            },
            {
                "label": "Space Weather Impact",
                "value": weather["overall_impact"],
                "delta": f"LEO drag: {weather['leo_drag_risk']}",
                "color": (
                    "green" if weather["overall_impact"] == "NOMINAL"
                    else "yellow" if weather["overall_impact"] == "ELEVATED"
                    else "orange" if weather["overall_impact"] == "HIGH"
                    else "red"
                ),
            },
            {
                "label": "Maneuvers Needed",
                "value": state["active_maneuvers_needed"],
                "delta": "pending" if state["active_maneuvers_needed"] > 0 else "none",
                "color": "red" if state["active_maneuvers_needed"] > 0 else "green",
            },
        ]

        # --- Altitude histogram raw data ---
        altitudes = [
            s["altitude_km"] for s in state["indian_constellation"]
            if s.get("altitude_km") is not None
        ]

        # --- Satellite table for constellation viewer ---
        sat_table = [
            {
                "Name": s["name"],
                "NORAD": s["norad_id"],
                "Alt (km)": round(s["altitude_km"], 1),
                "Speed (km/s)": round(s["speed_kms"], 3),
                "Orbit": s["orbit_class"],
            }
            for s in state["indian_constellation"]
        ]

        return {
            "kpi_cards": kpi_cards,
            "orbit_distribution": health.get("by_orbit_class", {}),
            "keyword_breakdown": health.get("by_keyword", {}),
            "altitude_histogram_data": altitudes,
            "weather_gauges": {
                "kp_index": weather["kp_index"],
                "solar_flux_sfu": weather["solar_flux_sfu"],
                "solar_wind_kms": weather["solar_wind_speed_kms"],
                "storm_level": weather["storm_level"],
            },
            "anomaly_table": health.get("anomalies", []),
            "satellite_table": sat_table,
            "perception_cycle_ms": state["perception_cycle_ms"],
        }

    # ===================================================================
    # INSTANCE TEST METHOD (callable via p.main())
    # ===================================================================

    def main(self):
        """Test function for terminal verification"""
        print("[KALA AGNI] Perception Agent initializing...")
        self.__init__()  # ensure fresh load
        print("[KALA AGNI] Perception Agent ready: {} Indian sats".format(len(self.get_current_state()["indian_constellation"])))
        state = self.get_current_state()
        print("[KALA AGNI] Sample GSAT-1 position:", state.get("sample_position", "N/A"))
        print("[KALA AGNI] Space weather impact:", state.get("space_weather_impact", "N/A"))
        print("[KALA AGNI] Natural English Perception Report:")
        print(self.generate_perception_summary())
        print("[KALA AGNI] Perception test complete.")


# =======================================================================
# MAIN -- Standalone test
# =======================================================================

def main():
    """
    Self-test: Initialize perception agent, build constellation state,
    and print the full perception report.
    """
    import io
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    print()
    print("=" * 72)
    print("  KALA AGNI Perception Agent -- Self Test")
    print("=" * 72)

    # --- 1. Initialize ---
    print("\n" + "-" * 52)
    print("  TEST 1: Agent Initialization")
    print("-" * 52)
    agent = PerceptionAgent()
    print(f"  Perception Agent initialized.")
    print(f"  Indian satellites: {len(agent.indian_sats)}")
    print(f"  Total cached sats: {len(agent.all_sats)}")

    # --- 2. Get current state ---
    print("\n" + "-" * 52)
    print("  TEST 2: Get Current State (full propagation)")
    print("-" * 52)
    state = agent.get_current_state()
    print(f"  Propagated: {state['propagated_count']} / {state['total_indian_sats']}")
    print(f"  Failures:   {state['propagation_failures']}")
    print(f"  Cycle time: {state['perception_cycle_ms']:.1f} ms")

    # --- 3. GSAT-1 current position ---
    print("\n" + "-" * 52)
    print("  TEST 3: Sample Satellite Position")
    print("-" * 52)
    gsat1 = None
    for s in state["indian_constellation"]:
        if "GSAT-1" == s["name"].strip():
            gsat1 = s
            break
    if gsat1 is None and state["indian_constellation"]:
        gsat1 = state["indian_constellation"][0]
        print(f"  (GSAT-1 not found, showing: {gsat1['name']})")

    if gsat1:
        print(f"  Satellite : {gsat1['name']}")
        print(f"  NORAD ID  : {gsat1['norad_id']}")
        print(f"  Altitude  : {gsat1['altitude_km']:.1f} km")
        print(f"  Speed     : {gsat1['speed_kms']:.4f} km/s")
        print(f"  Orbit     : {gsat1['orbit_class']}")
        pos = gsat1['position_km']
        print(f"  Position  : [{pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f}] km (TEME)")

    # --- 4. Constellation health ---
    print("\n" + "-" * 52)
    print("  TEST 4: Constellation Health")
    print("-" * 52)
    health = state["constellation_health"]
    print(f"  Overall : {health['overall_status']}")
    print(f"  Orbit distribution:")
    for cls, n in health["by_orbit_class"].items():
        print(f"    {cls:10s} : {n}")
    print(f"  Altitude range: {health['min_altitude_km']:.0f} - {health['max_altitude_km']:.0f} km")
    print(f"  Anomalies: {health['anomaly_count']}")

    # --- 5. Space weather impact ---
    print("\n" + "-" * 52)
    print("  TEST 5: Space Weather Impact")
    print("-" * 52)
    wx = state["space_weather_impact"]
    print(f"  Kp Index     : {wx['kp_index']:.1f} ({wx['storm_level']})")
    print(f"  Storm        : {wx['storm_description']}")
    print(f"  Solar Flux   : {wx['solar_flux_sfu']:.1f} SFU")
    print(f"  Solar Wind   : {wx['solar_wind_speed_kms']:.0f} km/s")
    print(f"  LEO Drag     : {wx['leo_drag_risk']}")
    print(f"  Radiation    : {wx['radiation_risk']}")
    print(f"  Overall      : {wx['overall_impact']}")

    # --- 6. Natural language summary ---
    print("\n" + "-" * 52)
    print("  TEST 6: Perception Report (Natural Language)")
    print("-" * 52)
    summary = agent.generate_perception_summary(state)
    # Indent for readability
    for line in summary.split("\n"):
        print(f"  {line}")

    # --- 7. UI visualization data ---
    print("\n" + "-" * 52)
    print("  TEST 7: Dashboard Data Structure")
    print("-" * 52)
    viz = agent.visualize_constellation_status(state)
    print(f"  KPI cards: {len(viz['kpi_cards'])}")
    for card in viz["kpi_cards"]:
        print(f"    {card['label']:30s} : {card['value']}  ({card['delta']})")
    print(f"  Satellite table rows: {len(viz['satellite_table'])}")
    print(f"  Anomaly table rows:   {len(viz['anomaly_table'])}")

    # --- 8. Cache test ---
    print("\n" + "-" * 52)
    print("  TEST 8: Perception Cache (second call should be instant)")
    print("-" * 52)
    t0 = time.perf_counter()
    state2 = agent.get_current_state()
    t1 = time.perf_counter()
    print(f"  Second call: {(t1-t0)*1000:.2f} ms (cache hit)")

    print()
    print("=" * 72)
    print("  KALA AGNI Perception Agent test complete.")
    print("  Next: Risk Agent -> Strategy Agent -> Command Brain -> Dashboard")
    print("=" * 72)
    print()


if __name__ == "__main__":
    main()
