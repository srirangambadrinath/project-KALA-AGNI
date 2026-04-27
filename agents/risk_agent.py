# PROJECT KALA AGNI
# Advanced Orbital Intelligence Platform
# File: agents/risk_agent.py

"""
KALA AGNI Risk Agent -- Threat Assessment Engine
====================================================================
Second agent in the OODA loop (Observe -> ORIENT -> Decide -> Act).
Consumes the Perception Agent's state and produces a risk assessment:

    1. Conjunction risks (close approaches between Indian sats and all objects)
    2. Space weather risks (geomagnetic storms, radiation, LEO drag)
    3. Constellation vulnerability scoring (0-100 composite)
    4. Top threats ranked by severity
    5. Overall risk level classification

Consumers of this agent's output:
    - agents/strategy_agent.py   -> uses risk assessment to plan maneuvers
    - agents/command_brain.py    -> reads risk report for autonomous decisions
    - dashboard/app.py           -> risk heatmaps and alert panels

    # Feeds into Execution Agent (strategy_agent -> execution pipeline)
"""

import sys
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Project root on sys.path
# ---------------------------------------------------------------------------
_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config import (
    CONJUNCTION_THRESHOLD_KM, CONJUNCTION_CRITICAL_KM,
    EARTH_RADIUS_KM, INDIAN_SAT_KEYWORDS,
)
from core.orbit_utils import (
    load_tle_from_cache, find_close_approaches, propagate_orbit,
    hohmann_delta_v, estimate_fuel_cost,
)
from agents.perception_agent import PerceptionAgent

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="[KALA AGNI] %(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("kala_agni.risk")

# ---------------------------------------------------------------------------
# Risk cache TTL
# ---------------------------------------------------------------------------
RISK_TTL_SECONDS = 300  # 5 minutes


class RiskAgent:
    """
    The Risk Agent evaluates threats to the Indian space constellation
    and produces actionable risk assessments for the Strategy Agent.

    Usage:
        perception = PerceptionAgent()
        risk = RiskAgent(perception)
        assessment = risk.assess_risks()
        report = risk.generate_risk_report()
    """

    def __init__(self, perception_agent: Optional[PerceptionAgent] = None):
        """
        Initialize the Risk Agent.

        Parameters:
            perception_agent: A PerceptionAgent instance (creates one if None).
        """
        logger.info("Risk Agent initializing...")
        t0 = time.perf_counter()

        if perception_agent is None:
            self.perception = PerceptionAgent()
        else:
            self.perception = perception_agent

        # Load satellite cache for conjunction checks
        try:
            self._sat_cache = load_tle_from_cache()
        except FileNotFoundError:
            self._sat_cache = {}

        # Internal risk cache
        self._risk_cache = None
        self._risk_cache_time = None

        elapsed = time.perf_counter() - t0
        logger.info("Risk Agent ready (%.2f s)", elapsed)

    # ===================================================================
    # CORE: Full risk assessment
    # ===================================================================

    def assess_risks(
        self,
        perception_state: Optional[dict] = None,
        force_refresh: bool = False
    ) -> dict:
        """
        Produce a comprehensive risk assessment of the Indian constellation.

        Returns:
            {
                "timestamp": str,
                "conjunction_risks": {...},
                "space_weather_risks": {...},
                "constellation_vulnerability_score": float (0-100),
                "top_threats": [...],
                "overall_risk_level": str,
                "risk_cycle_ms": float,
            }

        Uses a 5-minute cache to avoid redundant conjunction scans.
        # Feeds into Execution Agent via strategy_agent.generate_strategy()
        """
        # --- Cache check ---
        if (not force_refresh
                and self._risk_cache is not None
                and self._risk_cache_time is not None):
            age = time.time() - self._risk_cache_time
            if age < RISK_TTL_SECONDS:
                logger.debug("Risk cache hit (age %.1f s).", age)
                return self._risk_cache

        t0 = time.perf_counter()

        # Get perception state
        if perception_state is None:
            perception_state = self.perception.get_current_state()

        # --- 1. Conjunction risks ---
        conjunction = self._assess_conjunctions(perception_state)

        # --- 2. Space weather risks ---
        weather_risks = self._assess_weather_risks(perception_state)

        # --- 3. Constellation vulnerability ---
        vulnerability = self._compute_vulnerability_score(
            perception_state, conjunction, weather_risks
        )

        # --- 4. Top threats (sorted by severity) ---
        top_threats = self._rank_threats(
            perception_state, conjunction, weather_risks
        )

        # --- 5. Overall risk level ---
        overall = self._classify_overall_risk(vulnerability, top_threats)

        elapsed_ms = (time.perf_counter() - t0) * 1000

        assessment = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "conjunction_risks": conjunction,
            "space_weather_risks": weather_risks,
            "constellation_vulnerability_score": vulnerability,
            "top_threats": top_threats,
            "overall_risk_level": overall,
            "risk_cycle_ms": round(elapsed_ms, 2),
        }

        # Update cache
        self._risk_cache = assessment
        self._risk_cache_time = time.time()

        logger.info(
            "Risk assessment complete: score=%.1f, level=%s (%.1f ms)",
            vulnerability, overall, elapsed_ms
        )
        return assessment

    # ===================================================================
    # 1. CONJUNCTION RISK ASSESSMENT
    # ===================================================================

    def _assess_conjunctions(self, perception_state: dict) -> dict:
        """
        Scan for close approaches between Indian satellites and all tracked objects.

        Uses a fast 30-minute look-ahead with 5 steps for MVP.
        Production version should use 72-hour window with kd-tree acceleration.

        Returns:
            {
                "total_close_approaches": int,
                "critical_events": [...],   # distance < 1 km
                "warning_events": [...],    # distance < 10 km
                "closest_approach_km": float,
                "most_at_risk_satellite": str,
                "scan_window_minutes": float,
            }
        """
        indian_sats = self._sat_cache.get("indian_satellites", [])
        all_sats = self._sat_cache.get("all_active_satellites", [])

        # Use a subset for MVP speed (full constellation scan)
        # For 116 vs 189 sats, brute force is fine at 5 time steps
        scan_minutes = 30.0
        scan_steps = 5

        try:
            approaches = find_close_approaches(
                indian_sats=indian_sats,
                all_sats=all_sats if all_sats else indian_sats,
                threshold_km=CONJUNCTION_THRESHOLD_KM,
                propagation_minutes=scan_minutes,
                steps=scan_steps,
            )
        except Exception as e:
            logger.error("Conjunction scan failed: %s", e)
            approaches = []

        critical = [a for a in approaches if a["risk_level"] == "CRITICAL"]
        warnings = [a for a in approaches if a["risk_level"] == "WARNING"]

        closest = approaches[0]["min_distance_km"] if approaches else float("inf")
        most_at_risk = approaches[0]["sat1_name"] if approaches else "None"

        return {
            "total_close_approaches": len(approaches),
            "critical_events": critical[:10],  # cap for report size
            "warning_events": warnings[:20],
            "closest_approach_km": round(closest, 3) if closest < float("inf") else None,
            "most_at_risk_satellite": most_at_risk,
            "scan_window_minutes": scan_minutes,
            "scan_steps": scan_steps,
        }

    # ===================================================================
    # 2. SPACE WEATHER RISK ASSESSMENT
    # ===================================================================

    def _assess_weather_risks(self, perception_state: dict) -> dict:
        """
        Evaluate space weather as a risk factor for the constellation.

        Translates raw weather data into operational risk categories:
            - LEO drag risk (can cause unplanned orbit decay)
            - Radiation risk (single-event upsets, solar panel degradation)
            - Communication risk (ionospheric disturbance)
            - GEO surface charging risk

        Returns dict with risk factors and scores.
        """
        wx = perception_state.get("space_weather_impact", {})
        health = perception_state.get("constellation_health", {})

        kp = wx.get("kp_index", 0)
        flux = wx.get("solar_flux_sfu", 0)
        wind = wx.get("solar_wind_speed_kms", 0)
        leo_drag = wx.get("leo_drag_risk", "LOW")

        # Count LEO satellites (most affected by drag)
        orbit_dist = health.get("by_orbit_class", {})
        leo_count = orbit_dist.get("LEO", 0)
        geo_count = orbit_dist.get("GEO", 0)

        # --- LEO drag threat ---
        drag_score = 0
        if kp >= 7:
            drag_score = 90
        elif kp >= 5:
            drag_score = 60
        elif kp >= 3:
            drag_score = 30
        else:
            drag_score = 10
        # Scale by number of LEO assets at risk
        drag_score = min(100, drag_score + leo_count)

        # --- Radiation threat ---
        rad_score = 0
        if flux >= 200:
            rad_score = 80
        elif flux >= 150:
            rad_score = 50
        elif flux >= 100:
            rad_score = 25
        else:
            rad_score = 10

        # --- Communication disruption ---
        comm_score = 0
        if kp >= 7:
            comm_score = 70
        elif kp >= 5:
            comm_score = 40
        elif kp >= 3:
            comm_score = 15

        # --- GEO surface charging ---
        geo_charge_score = 0
        if kp >= 6 and geo_count > 0:
            geo_charge_score = min(80, 20 + geo_count)
        elif kp >= 4 and geo_count > 0:
            geo_charge_score = min(50, 10 + geo_count)

        # Composite weather risk (weighted average)
        composite = (
            drag_score * 0.35 +
            rad_score * 0.25 +
            comm_score * 0.20 +
            geo_charge_score * 0.20
        )

        return {
            "kp_index": kp,
            "solar_flux_sfu": flux,
            "solar_wind_kms": wind,
            "leo_satellites_at_risk": leo_count,
            "geo_satellites_at_risk": geo_count,
            "drag_risk_score": round(drag_score, 1),
            "radiation_risk_score": round(rad_score, 1),
            "communication_risk_score": round(comm_score, 1),
            "geo_charging_risk_score": round(geo_charge_score, 1),
            "composite_weather_risk": round(composite, 1),
            "leo_drag_level": leo_drag,
        }

    # ===================================================================
    # 3. VULNERABILITY SCORING (0-100)
    # ===================================================================

    def _compute_vulnerability_score(
        self,
        perception_state: dict,
        conjunction: dict,
        weather_risks: dict,
    ) -> float:
        """
        Compute a composite vulnerability score (0-100) for the constellation.

        Weighted factors:
            - Conjunction risk: 40%
            - Space weather risk: 30%
            - Constellation health: 20%
            - Propagation reliability: 10%

        Score interpretation:
            0-25:  LOW risk
            25-50: MEDIUM risk
            50-75: HIGH risk
            75-100: CRITICAL risk
        """
        # --- Conjunction score (0-100) ---
        n_approaches = conjunction.get("total_close_approaches", 0)
        n_critical = len(conjunction.get("critical_events", []))
        closest = conjunction.get("closest_approach_km") or 1000

        conj_score = 0
        if n_critical > 0:
            conj_score = min(100, 80 + n_critical * 5)
        elif n_approaches > 0:
            conj_score = min(70, n_approaches * 10)
        if closest < 1.0:
            conj_score = 100
        elif closest < 5.0:
            conj_score = max(conj_score, 80)
        elif closest < 10.0:
            conj_score = max(conj_score, 50)

        # --- Weather score ---
        weather_score = weather_risks.get("composite_weather_risk", 0)

        # --- Health score (invert: NOMINAL=0, DEGRADED=40, CRITICAL=80) ---
        health_status = perception_state.get(
            "constellation_health", {}
        ).get("overall_status", "NOMINAL")
        anomaly_count = perception_state.get(
            "constellation_health", {}
        ).get("anomaly_count", 0)

        health_score = 0
        if health_status == "CRITICAL":
            health_score = 80
        elif health_status == "DEGRADED":
            health_score = 40
        health_score = min(100, health_score + anomaly_count)

        # --- Propagation reliability ---
        total = perception_state.get("total_indian_sats", 1)
        propagated = perception_state.get("propagated_count", total)
        failure_rate = (total - propagated) / max(total, 1) * 100
        prop_score = min(100, failure_rate * 5)

        # --- Weighted composite ---
        composite = (
            conj_score * 0.40 +
            weather_score * 0.30 +
            health_score * 0.20 +
            prop_score * 0.10
        )
        return round(min(100, composite), 1)

    # ===================================================================
    # 4. THREAT RANKING
    # ===================================================================

    def _rank_threats(
        self,
        perception_state: dict,
        conjunction: dict,
        weather_risks: dict,
    ) -> list[dict]:
        """
        Build a ranked list of all identified threats, sorted by severity.

        Each threat is a dict:
            {
                "threat_type": str,
                "severity": "LOW"/"MEDIUM"/"HIGH"/"CRITICAL",
                "severity_score": float (0-100),
                "description": str,
                "affected_assets": list[str],
                "recommended_action": str,
            }

        # Feeds into Execution Agent via strategy_agent
        """
        threats = []

        # --- Conjunction threats ---
        for event in conjunction.get("critical_events", []):
            threats.append({
                "threat_type": "CONJUNCTION_CRITICAL",
                "severity": "CRITICAL",
                "severity_score": 95,
                "description": (
                    f"Critical conjunction: {event['sat1_name']} and "
                    f"{event['sat2_name']} at {event['min_distance_km']:.3f} km "
                    f"in {event['minutes_from_now']:.0f} min"
                ),
                "affected_assets": [event["sat1_name"], event["sat2_name"]],
                "recommended_action": "IMMEDIATE: Execute collision avoidance maneuver.",
            })

        for event in conjunction.get("warning_events", [])[:5]:
            threats.append({
                "threat_type": "CONJUNCTION_WARNING",
                "severity": "HIGH",
                "severity_score": 65,
                "description": (
                    f"Close approach: {event['sat1_name']} and "
                    f"{event['sat2_name']} at {event['min_distance_km']:.1f} km "
                    f"in {event['minutes_from_now']:.0f} min"
                ),
                "affected_assets": [event["sat1_name"]],
                "recommended_action": "MONITOR: Prepare avoidance maneuver if distance decreases.",
            })

        # --- Space weather threats ---
        kp = weather_risks.get("kp_index", 0)
        if kp >= 7:
            threats.append({
                "threat_type": "GEOMAGNETIC_STORM_SEVERE",
                "severity": "CRITICAL",
                "severity_score": 85,
                "description": f"Severe geomagnetic storm (Kp={kp:.0f}). All orbits affected.",
                "affected_assets": ["ALL_LEO", "ALL_GEO"],
                "recommended_action": "ALERT: Activate emergency protocols. Prepare drag compensation.",
            })
        elif kp >= 5:
            threats.append({
                "threat_type": "GEOMAGNETIC_STORM",
                "severity": "HIGH" if kp >= 6 else "MEDIUM",
                "severity_score": 55 + (kp - 5) * 15,
                "description": (
                    f"Geomagnetic storm (Kp={kp:.0f}). LEO drag elevated, "
                    f"{weather_risks.get('leo_satellites_at_risk', 0)} LEO sats at risk."
                ),
                "affected_assets": ["ALL_LEO"],
                "recommended_action": "HEIGHTENED: Monitor LEO altitude decay. Pre-plan burns.",
            })

        if weather_risks.get("radiation_risk_score", 0) >= 50:
            threats.append({
                "threat_type": "RADIATION_ELEVATED",
                "severity": "MEDIUM",
                "severity_score": weather_risks["radiation_risk_score"],
                "description": (
                    f"Elevated solar radiation (F10.7={weather_risks['solar_flux_sfu']:.0f} SFU). "
                    "Risk of single-event upsets on sensitive payloads."
                ),
                "affected_assets": ["ALL_GEO", "ALL_MEO"],
                "recommended_action": "WATCH: Review payload safe-mode thresholds.",
            })

        # --- Constellation health threats ---
        anomalies = perception_state.get(
            "constellation_health", {}
        ).get("anomalies", [])
        low_alt_sats = [
            a for a in anomalies if a.get("flag") == "LOW_ALTITUDE_WARNING"
        ]
        if low_alt_sats:
            names = [a["satellite"] for a in low_alt_sats[:3]]
            threats.append({
                "threat_type": "ORBITAL_DECAY",
                "severity": "HIGH",
                "severity_score": 70,
                "description": (
                    f"{len(low_alt_sats)} satellite(s) below safe altitude: "
                    f"{', '.join(names)}"
                ),
                "affected_assets": names,
                "recommended_action": "URGENT: Plan altitude-raise maneuver.",
            })

        prop_failures = perception_state.get("propagation_failures", 0)
        if prop_failures > 0:
            threats.append({
                "threat_type": "TRACKING_LOSS",
                "severity": "MEDIUM",
                "severity_score": min(60, prop_failures * 10),
                "description": (
                    f"{prop_failures} satellite(s) failed SGP4 propagation. "
                    "TLE data may be stale."
                ),
                "affected_assets": ["UNKNOWN"],
                "recommended_action": "REFRESH: Update TLE data from Celestrak.",
            })

        # Sort by severity score descending
        threats.sort(key=lambda t: t["severity_score"], reverse=True)
        return threats

    # ===================================================================
    # 5. OVERALL RISK CLASSIFICATION
    # ===================================================================

    def _classify_overall_risk(
        self, vulnerability_score: float, threats: list[dict]
    ) -> str:
        """
        Classify the overall risk level based on vulnerability score and threats.

        Returns: "LOW", "MEDIUM", "HIGH", or "CRITICAL"
        """
        # Any CRITICAL threat forces CRITICAL level
        if any(t["severity"] == "CRITICAL" for t in threats):
            return "CRITICAL"

        if vulnerability_score >= 75:
            return "CRITICAL"
        elif vulnerability_score >= 50:
            return "HIGH"
        elif vulnerability_score >= 25:
            return "MEDIUM"
        else:
            return "LOW"

    # ===================================================================
    # NATURAL LANGUAGE RISK REPORT
    # ===================================================================

    def generate_risk_report(self, assessment: Optional[dict] = None) -> str:
        """
        Generate a natural English risk briefing for Command Brain.

        Returns a multi-line string suitable for terminal display or
        dashboard text panel.
        """
        if assessment is None:
            assessment = self.assess_risks()

        conj = assessment["conjunction_risks"]
        wx = assessment["space_weather_risks"]
        vuln = assessment["constellation_vulnerability_score"]
        level = assessment["overall_risk_level"]
        threats = assessment["top_threats"]
        ts = assessment["timestamp"]

        lines = [
            f"KALA AGNI RISK ASSESSMENT -- {ts[:19]} UTC",
            "=" * 56,
            "",
            f"OVERALL RISK LEVEL: {level}",
            f"Vulnerability Score: {vuln:.1f} / 100",
            "",
        ]

        # --- Conjunction summary ---
        lines.append("CONJUNCTION ANALYSIS:")
        lines.append(
            f"  Scan window: {conj['scan_window_minutes']:.0f} min, "
            f"{conj['scan_steps']} steps"
        )
        lines.append(f"  Close approaches detected: {conj['total_close_approaches']}")
        if conj["closest_approach_km"] is not None:
            lines.append(f"  Closest approach: {conj['closest_approach_km']:.3f} km")
            lines.append(f"  Most at-risk satellite: {conj['most_at_risk_satellite']}")
        n_crit = len(conj.get("critical_events", []))
        n_warn = len(conj.get("warning_events", []))
        lines.append(f"  Critical events: {n_crit}  |  Warning events: {n_warn}")
        lines.append("")

        # --- Space weather risks ---
        lines.append("SPACE WEATHER RISK FACTORS:")
        lines.append(f"  Kp Index: {wx['kp_index']:.0f}  |  LEO drag: {wx['leo_drag_level']}")
        lines.append(
            f"  Drag risk:     {wx['drag_risk_score']:5.1f} / 100  "
            f"({wx['leo_satellites_at_risk']} LEO sats)"
        )
        lines.append(f"  Radiation risk: {wx['radiation_risk_score']:5.1f} / 100")
        lines.append(f"  Comms risk:     {wx['communication_risk_score']:5.1f} / 100")
        lines.append(f"  GEO charging:   {wx['geo_charging_risk_score']:5.1f} / 100")
        lines.append(
            f"  Composite weather risk: {wx['composite_weather_risk']:.1f} / 100"
        )
        lines.append("")

        # --- Top threats ---
        lines.append(f"TOP THREATS ({len(threats)}):")
        if threats:
            for i, t in enumerate(threats[:5], 1):
                lines.append(
                    f"  {i}. [{t['severity']:8s}] {t['threat_type']}"
                )
                lines.append(f"     {t['description']}")
                lines.append(f"     Action: {t['recommended_action']}")
        else:
            lines.append("  No active threats identified.")
        lines.append("")

        lines.append(
            f"Risk assessment completed in {assessment['risk_cycle_ms']:.1f} ms."
        )

        return "\n".join(lines)

    # ===================================================================
    # INSTANCE TEST METHOD
    # ===================================================================

    def main(self):
        """Test function for terminal verification."""
        print("[KALA AGNI] Risk Agent initializing...")
        assessment = self.assess_risks(force_refresh=True)
        print(f"[KALA AGNI] Risk level: {assessment['overall_risk_level']}")
        print(f"[KALA AGNI] Vulnerability score: {assessment['constellation_vulnerability_score']}")
        print(f"[KALA AGNI] Top threats: {len(assessment['top_threats'])}")
        print("[KALA AGNI] Risk Report:")
        print(self.generate_risk_report(assessment))
        print("[KALA AGNI] Risk assessment complete.")


# =======================================================================
# MAIN -- Standalone test (chains Perception -> Risk)
# =======================================================================

def main():
    """Full chain test: Perception Agent -> Risk Agent."""
    import io
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    print()
    print("=" * 72)
    print("  KALA AGNI Risk Agent -- Self Test")
    print("=" * 72)

    # --- 1. Init Perception ---
    print("\n" + "-" * 52)
    print("  TEST 1: Initialize Perception + Risk Chain")
    print("-" * 52)
    perception = PerceptionAgent()
    risk_agent = RiskAgent(perception)
    print(f"  Perception: {len(perception.indian_sats)} Indian sats")
    print("  Risk Agent: ready")

    # --- 2. Assess risks ---
    print("\n" + "-" * 52)
    print("  TEST 2: Full Risk Assessment")
    print("-" * 52)
    assessment = risk_agent.assess_risks()
    print(f"  Vulnerability score: {assessment['constellation_vulnerability_score']:.1f}")
    print(f"  Overall risk level:  {assessment['overall_risk_level']}")
    print(f"  Risk cycle time:     {assessment['risk_cycle_ms']:.1f} ms")

    # --- 3. Conjunction results ---
    print("\n" + "-" * 52)
    print("  TEST 3: Conjunction Analysis")
    print("-" * 52)
    conj = assessment["conjunction_risks"]
    print(f"  Close approaches:    {conj['total_close_approaches']}")
    print(f"  Critical events:     {len(conj.get('critical_events', []))}")
    print(f"  Warning events:      {len(conj.get('warning_events', []))}")
    if conj["closest_approach_km"] is not None:
        print(f"  Closest approach:    {conj['closest_approach_km']:.3f} km")

    # --- 4. Weather risks ---
    print("\n" + "-" * 52)
    print("  TEST 4: Space Weather Risks")
    print("-" * 52)
    wx = assessment["space_weather_risks"]
    print(f"  Kp Index:            {wx['kp_index']:.0f}")
    print(f"  Drag risk:           {wx['drag_risk_score']:.0f}/100 ({wx['leo_satellites_at_risk']} LEO sats)")
    print(f"  Radiation risk:      {wx['radiation_risk_score']:.0f}/100")
    print(f"  Composite weather:   {wx['composite_weather_risk']:.1f}/100")

    # --- 5. Top threats ---
    print("\n" + "-" * 52)
    print("  TEST 5: Top Threats")
    print("-" * 52)
    for i, t in enumerate(assessment["top_threats"][:5], 1):
        print(f"  {i}. [{t['severity']:8s}] {t['threat_type']}: {t['description'][:60]}...")

    # --- 6. Full report ---
    print("\n" + "-" * 52)
    print("  TEST 6: Natural Language Risk Report")
    print("-" * 52)
    report = risk_agent.generate_risk_report(assessment)
    for line in report.split("\n"):
        print(f"  {line}")

    # --- 7. Cache test ---
    print("\n" + "-" * 52)
    print("  TEST 7: Risk Cache (second call)")
    print("-" * 52)
    t0 = time.perf_counter()
    _ = risk_agent.assess_risks()
    t1 = time.perf_counter()
    print(f"  Second call: {(t1-t0)*1000:.2f} ms (cache hit)")

    print()
    print("=" * 72)
    print("  KALA AGNI Risk Agent test complete.")
    print("  Next: Strategy Agent -> Command Brain -> Dashboard")
    print("=" * 72)
    print()


if __name__ == "__main__":
    main()
