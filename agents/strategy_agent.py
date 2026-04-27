# PROJECT KALA AGNI
# Advanced Orbital Intelligence Platform
# File: agents/strategy_agent.py

"""
KALA AGNI Strategy Agent -- Command Decision Engine
====================================================================
Third agent in the OODA loop (Observe -> Orient -> DECIDE -> Act).
Consumes Risk Agent assessments and Perception state to produce
actionable strategies:

    1. Recommended maneuvers (collision avoidance, station-keeping)
    2. Priority action list (ranked by urgency)
    3. Fuel impact estimation (Tsiolkovsky-based)
    4. Execution timeline with go/no-go windows
    5. Confidence scoring for autonomous execution

Consumers of this agent's output:
    - agents/command_brain.py    -> final approval / autonomous execution
    - dashboard/app.py           -> strategy display panels
    # Feeds into Execution Agent (command_brain -> thruster commands)
"""

import sys
import time
import logging
from datetime import datetime, timezone, timedelta
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
    EARTH_RADIUS_KM, CONJUNCTION_THRESHOLD_KM,
    DEFAULT_DRY_MASS_KG, ISRO_BIPROP_ISP,
    CONJUNCTION_CRITICAL_KM, MANEUVER_LEAD_TIME_HOURS,
)
from core.orbit_utils import (
    generate_maneuver, hohmann_delta_v, estimate_fuel_cost,
)
from agents.perception_agent import PerceptionAgent
from agents.risk_agent import RiskAgent

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="[KALA AGNI] %(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("kala_agni.strategy")

# ---------------------------------------------------------------------------
# Strategy cache TTL
# ---------------------------------------------------------------------------
STRATEGY_TTL_SECONDS = 300  # 5 minutes


class StrategyAgent:
    """
    The Strategy Agent decides what actions to take based on risk assessment
    and constellation state. Produces executable maneuver plans.

    Usage:
        perception = PerceptionAgent()
        risk = RiskAgent(perception)
        strategy = StrategyAgent(risk, perception)
        plan = strategy.generate_strategy()
        summary = strategy.generate_strategy_summary()
    """

    def __init__(
        self,
        risk_agent: Optional[RiskAgent] = None,
        perception_agent: Optional[PerceptionAgent] = None,
    ):
        """
        Initialize the Strategy Agent.

        Parameters:
            risk_agent:       RiskAgent instance (creates one if None).
            perception_agent: PerceptionAgent instance (creates one if None).
        """
        logger.info("Strategy Agent initializing...")
        t0 = time.perf_counter()

        if perception_agent is None:
            self.perception = PerceptionAgent()
        else:
            self.perception = perception_agent

        if risk_agent is None:
            self.risk = RiskAgent(self.perception)
        else:
            self.risk = risk_agent

        # Internal strategy cache
        self._strategy_cache = None
        self._strategy_cache_time = None

        elapsed = time.perf_counter() - t0
        logger.info("Strategy Agent ready (%.2f s)", elapsed)

    # ===================================================================
    # CORE: Strategy generation
    # ===================================================================

    def generate_strategy(
        self,
        risk_assessment: Optional[dict] = None,
        perception_state: Optional[dict] = None,
        force_refresh: bool = False,
    ) -> dict:
        """
        Generate a complete strategy based on current risk and perception.

        Returns:
            {
                "timestamp": str,
                "recommended_maneuvers": [...],
                "priority_actions": [...],
                "fuel_impact_estimate": {...},
                "execution_timeline": [...],
                "confidence_score": float (0-100),
                "overall_posture": str,
                "strategy_cycle_ms": float,
            }

        # Feeds into Execution Agent for autonomous maneuver execution
        """
        # --- Cache check ---
        if (not force_refresh
                and self._strategy_cache is not None
                and self._strategy_cache_time is not None):
            age = time.time() - self._strategy_cache_time
            if age < STRATEGY_TTL_SECONDS:
                logger.debug("Strategy cache hit (age %.1f s).", age)
                return self._strategy_cache

        t0 = time.perf_counter()

        # Get upstream data
        if perception_state is None:
            perception_state = self.perception.get_current_state()
        if risk_assessment is None:
            risk_assessment = self.risk.assess_risks(perception_state)

        # --- 1. Recommended maneuvers ---
        maneuvers = self._plan_maneuvers(risk_assessment, perception_state)

        # --- 2. Priority actions ---
        actions = self._build_action_list(risk_assessment, maneuvers)

        # --- 3. Fuel impact ---
        fuel_impact = self._estimate_fuel_impact(maneuvers)

        # --- 4. Execution timeline ---
        timeline = self._build_timeline(actions, maneuvers)

        # --- 5. Confidence score ---
        confidence = self._compute_confidence(
            risk_assessment, perception_state, maneuvers
        )

        # --- 6. Overall posture ---
        posture = self._determine_posture(risk_assessment, confidence)

        elapsed_ms = (time.perf_counter() - t0) * 1000

        strategy = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "recommended_maneuvers": maneuvers,
            "priority_actions": actions,
            "fuel_impact_estimate": fuel_impact,
            "execution_timeline": timeline,
            "confidence_score": confidence,
            "overall_posture": posture,
            "risk_level": risk_assessment.get("overall_risk_level", "UNKNOWN"),
            "vulnerability_score": risk_assessment.get(
                "constellation_vulnerability_score", 0
            ),
            "strategy_cycle_ms": round(elapsed_ms, 2),
        }

        # Update cache
        self._strategy_cache = strategy
        self._strategy_cache_time = time.time()

        logger.info(
            "Strategy generated: %d maneuvers, %d actions, confidence=%.0f%% (%.1f ms)",
            len(maneuvers), len(actions), confidence, elapsed_ms
        )
        return strategy

    # ===================================================================
    # 1. MANEUVER PLANNING
    # ===================================================================

    def _plan_maneuvers(
        self, risk_assessment: dict, perception_state: dict
    ) -> list[dict]:
        """
        Plan maneuvers based on identified threats.

        Strategy logic:
            - CRITICAL conjunctions -> immediate collision avoidance (+10 km raise)
            - HIGH orbital decay     -> altitude restoration burn
            - Storm-exposed LEO     -> optional drag compensation burn
            - Routine station-keeping for GEO sats (if drifting)

        Returns list of maneuver dicts from orbit_utils.generate_maneuver().
        # Feeds into Execution Agent
        """
        maneuvers = []
        threats = risk_assessment.get("top_threats", [])
        constellation = perception_state.get("indian_constellation", [])

        # Build name->sat lookup for quick access
        sat_lookup = {s["name"]: s for s in constellation}

        # --- Critical conjunction avoidance ---
        critical_events = risk_assessment.get(
            "conjunction_risks", {}
        ).get("critical_events", [])

        already_planned = set()
        for event in critical_events[:3]:  # cap at 3 emergency maneuvers
            sat_name = event.get("sat1_name", "")
            if sat_name in already_planned:
                continue
            already_planned.add(sat_name)

            try:
                maneuver = generate_maneuver(sat_name)  # default +10 km raise
                if "error" not in maneuver:
                    maneuver["trigger"] = "COLLISION_AVOIDANCE"
                    maneuver["priority"] = "CRITICAL"
                    maneuver["threat_ref"] = (
                        f"Conjunction with {event.get('sat2_name', '?')} "
                        f"at {event.get('min_distance_km', '?'):.3f} km"
                    )
                    maneuvers.append(maneuver)
            except Exception as e:
                logger.warning("Failed to plan maneuver for %s: %s", sat_name, e)

        # --- Altitude restoration for decaying sats ---
        anomalies = perception_state.get(
            "constellation_health", {}
        ).get("anomalies", [])
        decay_sats = [
            a for a in anomalies if a.get("flag") == "LOW_ALTITUDE_WARNING"
        ]
        for anom in decay_sats[:2]:
            sat_name = anom["satellite"]
            if sat_name in already_planned:
                continue
            already_planned.add(sat_name)

            # Raise to 400 km (safe LEO altitude)
            try:
                maneuver = generate_maneuver(sat_name, target_altitude_km=400.0)
                if "error" not in maneuver:
                    maneuver["trigger"] = "ALTITUDE_RESTORATION"
                    maneuver["priority"] = "HIGH"
                    maneuver["threat_ref"] = (
                        f"Altitude decay: {anom['altitude_km']:.0f} km"
                    )
                    maneuvers.append(maneuver)
            except Exception as e:
                logger.warning("Altitude restore failed for %s: %s", sat_name, e)

        # --- Storm drag compensation for LEO sats ---
        wx = risk_assessment.get("space_weather_risks", {})
        if wx.get("drag_risk_score", 0) >= 60:
            # Find lowest LEO satellite not already planned
            leo_sats = [
                s for s in constellation
                if s["orbit_class"] == "LEO" and s["name"] not in already_planned
            ]
            if leo_sats:
                leo_sats.sort(key=lambda s: s["altitude_km"])
                lowest = leo_sats[0]
                try:
                    # Small 5 km raise for drag compensation
                    target_alt = lowest["altitude_km"] + 5.0
                    maneuver = generate_maneuver(
                        lowest["name"], target_altitude_km=target_alt
                    )
                    if "error" not in maneuver:
                        maneuver["trigger"] = "DRAG_COMPENSATION"
                        maneuver["priority"] = "MEDIUM"
                        maneuver["threat_ref"] = (
                            f"Storm drag (Kp={wx.get('kp_index', 0):.0f}), "
                            f"alt={lowest['altitude_km']:.0f} km"
                        )
                        maneuvers.append(maneuver)
                except Exception as e:
                    logger.warning("Drag compensation failed: %s", e)

        # --- GEO station-keeping (if any GEO sat drifting beyond 0.1 deg) ---
        # Placeholder -- full implementation needs longitude tracking
        # For MVP, we just add a note
        geo_sats = [
            s for s in constellation
            if s["orbit_class"] == "GEO" and s["name"] not in already_planned
        ]
        if geo_sats and len(maneuvers) < 5:
            # Pick first GEO sat for a routine station-keeping demo
            try:
                maneuver = generate_maneuver(geo_sats[0]["name"])
                if "error" not in maneuver:
                    maneuver["trigger"] = "STATION_KEEPING"
                    maneuver["priority"] = "LOW"
                    maneuver["threat_ref"] = "Routine GEO maintenance"
                    maneuvers.append(maneuver)
            except Exception:
                pass

        return maneuvers

    # ===================================================================
    # 2. PRIORITY ACTION LIST
    # ===================================================================

    def _build_action_list(
        self, risk_assessment: dict, maneuvers: list[dict]
    ) -> list[dict]:
        """
        Build a prioritized action list from threats and planned maneuvers.

        Each action:
            {
                "priority": int (1=highest),
                "action": str,
                "category": str,
                "deadline_hours": float,
                "status": "PENDING",
            }

        # Feeds into Execution Agent
        """
        actions = []
        priority_counter = 1

        # --- From critical threats ---
        for threat in risk_assessment.get("top_threats", []):
            if threat["severity"] == "CRITICAL":
                actions.append({
                    "priority": priority_counter,
                    "action": threat["recommended_action"],
                    "category": threat["threat_type"],
                    "deadline_hours": 1.0,
                    "status": "PENDING",
                    "severity": "CRITICAL",
                })
                priority_counter += 1

        # --- From maneuvers ---
        for m in maneuvers:
            if m.get("priority") in ("CRITICAL", "HIGH"):
                actions.append({
                    "priority": priority_counter,
                    "action": (
                        f"Execute {m['trigger']} for {m['satellite']}: "
                        f"dv={m['hohmann_transfer']['total_dv_ms']:.1f} m/s, "
                        f"fuel={m['fuel_cost_biprop']['propellant_mass_kg']:.2f} kg"
                    ),
                    "category": m["trigger"],
                    "deadline_hours": (
                        0.5 if m.get("priority") == "CRITICAL" else 4.0
                    ),
                    "status": "PENDING",
                    "severity": m.get("priority", "MEDIUM"),
                })
                priority_counter += 1

        # --- From high threats ---
        for threat in risk_assessment.get("top_threats", []):
            if threat["severity"] == "HIGH":
                actions.append({
                    "priority": priority_counter,
                    "action": threat["recommended_action"],
                    "category": threat["threat_type"],
                    "deadline_hours": 6.0,
                    "status": "PENDING",
                    "severity": "HIGH",
                })
                priority_counter += 1

        # --- General monitoring actions ---
        risk_level = risk_assessment.get("overall_risk_level", "LOW")
        if risk_level in ("HIGH", "CRITICAL"):
            actions.append({
                "priority": priority_counter,
                "action": "Increase TLE refresh cadence to 30-minute intervals.",
                "category": "MONITORING",
                "deadline_hours": 0.5,
                "status": "PENDING",
                "severity": "MEDIUM",
            })
            priority_counter += 1

        if risk_level == "CRITICAL":
            actions.append({
                "priority": priority_counter,
                "action": "Notify Space Command duty officer. Escalate to manual override.",
                "category": "ESCALATION",
                "deadline_hours": 0.25,
                "status": "PENDING",
                "severity": "CRITICAL",
            })
            priority_counter += 1

        # --- Low-priority routine ---
        for m in maneuvers:
            if m.get("priority") in ("MEDIUM", "LOW"):
                actions.append({
                    "priority": priority_counter,
                    "action": (
                        f"Schedule {m['trigger']} for {m['satellite']}: "
                        f"dv={m['hohmann_transfer']['total_dv_ms']:.1f} m/s"
                    ),
                    "category": m["trigger"],
                    "deadline_hours": 24.0,
                    "status": "PENDING",
                    "severity": m.get("priority", "LOW"),
                })
                priority_counter += 1

        return actions

    # ===================================================================
    # 3. FUEL IMPACT ESTIMATION
    # ===================================================================

    def _estimate_fuel_impact(self, maneuvers: list[dict]) -> dict:
        """
        Aggregate fuel costs across all planned maneuvers.

        Returns:
            {
                "total_delta_v_ms": float,
                "total_fuel_biprop_kg": float,
                "total_fuel_electric_kg": float,
                "maneuver_count": int,
                "feasibility": str,  # "ALL_FEASIBLE" / "PARTIAL" / "INFEASIBLE"
                "per_satellite": [...],
            }
        """
        total_dv = 0.0
        total_fuel_biprop = 0.0
        total_fuel_electric = 0.0
        per_sat = []
        all_feasible = True

        for m in maneuvers:
            dv = m.get("hohmann_transfer", {}).get("total_dv_ms", 0)
            fuel_bp = m.get("fuel_cost_biprop", {}).get("propellant_mass_kg", 0)
            fuel_el = m.get("fuel_cost_electric", {}).get("propellant_mass_kg", 0)
            feasible = m.get("feasible", True)

            total_dv += dv
            total_fuel_biprop += fuel_bp
            total_fuel_electric += fuel_el
            if not feasible:
                all_feasible = False

            per_sat.append({
                "satellite": m.get("satellite", "?"),
                "trigger": m.get("trigger", "?"),
                "delta_v_ms": round(dv, 3),
                "fuel_biprop_kg": round(fuel_bp, 3),
                "fuel_electric_kg": round(fuel_el, 3),
                "feasible": feasible,
            })

        if not maneuvers:
            feasibility = "NO_MANEUVERS"
        elif all_feasible:
            feasibility = "ALL_FEASIBLE"
        else:
            feasibility = "PARTIAL"

        return {
            "total_delta_v_ms": round(total_dv, 3),
            "total_fuel_biprop_kg": round(total_fuel_biprop, 3),
            "total_fuel_electric_kg": round(total_fuel_electric, 3),
            "maneuver_count": len(maneuvers),
            "feasibility": feasibility,
            "per_satellite": per_sat,
        }

    # ===================================================================
    # 4. EXECUTION TIMELINE
    # ===================================================================

    def _build_timeline(
        self, actions: list[dict], maneuvers: list[dict]
    ) -> list[dict]:
        """
        Build a time-ordered execution timeline.

        Each entry:
            {
                "time_utc": str,
                "event": str,
                "type": str,  # "MANEUVER" / "MONITOR" / "REPORT"
                "window_hours": float,
            }
        """
        now = datetime.now(timezone.utc)
        timeline = []

        # Immediate: status report
        timeline.append({
            "time_utc": now.isoformat(),
            "event": "Strategy generated. Awaiting Command Brain approval.",
            "type": "REPORT",
            "window_hours": 0,
        })

        # From actions, sorted by deadline
        sorted_actions = sorted(actions, key=lambda a: a["deadline_hours"])

        for act in sorted_actions:
            exec_time = now + timedelta(hours=act["deadline_hours"])
            timeline.append({
                "time_utc": exec_time.isoformat(),
                "event": act["action"][:80],
                "type": act["category"],
                "window_hours": act["deadline_hours"],
            })

        # From maneuvers
        for i, m in enumerate(maneuvers):
            burn_time = now + timedelta(hours=0.5 + i * 2)
            transfer_hrs = m.get("hohmann_transfer", {}).get(
                "transfer_time_hours", 0
            )
            timeline.append({
                "time_utc": burn_time.isoformat(),
                "event": (
                    f"BURN: {m.get('satellite', '?')} -- "
                    f"{m.get('trigger', '?')} "
                    f"(dv={m.get('hohmann_transfer', {}).get('total_dv_ms', 0):.1f} m/s, "
                    f"transfer={transfer_hrs:.1f} hr)"
                ),
                "type": "MANEUVER",
                "window_hours": 0.5 + i * 2,
            })

        # Sort by time
        timeline.sort(key=lambda t: t["time_utc"])

        # End: next assessment cycle
        timeline.append({
            "time_utc": (now + timedelta(hours=2)).isoformat(),
            "event": "Next risk assessment and strategy refresh cycle.",
            "type": "REPORT",
            "window_hours": 2.0,
        })

        return timeline

    # ===================================================================
    # 5. CONFIDENCE SCORING
    # ===================================================================

    def _compute_confidence(
        self,
        risk_assessment: dict,
        perception_state: dict,
        maneuvers: list[dict],
    ) -> float:
        """
        Compute confidence in the generated strategy (0-100%).

        Factors:
            - Data freshness (TLE age)
            - Propagation success rate
            - Maneuver feasibility
            - Risk assessment completeness

        Higher confidence = safer to execute autonomously.
        """
        score = 100.0

        # --- Data freshness ---
        total = perception_state.get("total_indian_sats", 1)
        propagated = perception_state.get("propagated_count", 0)
        prop_rate = propagated / max(total, 1)
        if prop_rate < 0.9:
            score -= (1 - prop_rate) * 30  # up to -30 for poor tracking

        # --- Maneuver feasibility ---
        if maneuvers:
            feasible_count = sum(1 for m in maneuvers if m.get("feasible", True))
            feasibility_rate = feasible_count / len(maneuvers)
            if feasibility_rate < 1.0:
                score -= (1 - feasibility_rate) * 20  # up to -20

        # --- Risk level penalty ---
        risk_level = risk_assessment.get("overall_risk_level", "LOW")
        risk_penalties = {"LOW": 0, "MEDIUM": 5, "HIGH": 15, "CRITICAL": 25}
        score -= risk_penalties.get(risk_level, 0)

        # --- Vulnerability score penalty ---
        vuln = risk_assessment.get("constellation_vulnerability_score", 0)
        if vuln > 50:
            score -= (vuln - 50) * 0.3  # up to -15

        # --- Conjunction count penalty ---
        n_conjunctions = risk_assessment.get(
            "conjunction_risks", {}
        ).get("total_close_approaches", 0)
        if n_conjunctions > 0:
            score -= min(10, n_conjunctions * 2)

        return round(max(0, min(100, score)), 1)

    # ===================================================================
    # 6. POSTURE DETERMINATION
    # ===================================================================

    def _determine_posture(
        self, risk_assessment: dict, confidence: float
    ) -> str:
        """
        Determine the recommended operational posture.

        Returns one of:
            - "AUTONOMOUS"   -> confidence > 80, risk LOW/MEDIUM
            - "SUPERVISED"   -> confidence > 60, risk MEDIUM/HIGH
            - "MANUAL"       -> confidence < 60, or risk CRITICAL
            - "EMERGENCY"    -> risk CRITICAL + critical threats
        """
        risk_level = risk_assessment.get("overall_risk_level", "LOW")
        threats = risk_assessment.get("top_threats", [])
        has_critical = any(t["severity"] == "CRITICAL" for t in threats)

        if risk_level == "CRITICAL" and has_critical:
            return "EMERGENCY"
        elif risk_level == "CRITICAL" or confidence < 60:
            return "MANUAL"
        elif risk_level in ("HIGH", "MEDIUM") or confidence < 80:
            return "SUPERVISED"
        else:
            return "AUTONOMOUS"

    # ===================================================================
    # NATURAL LANGUAGE STRATEGY SUMMARY
    # ===================================================================

    def generate_strategy_summary(self, strategy: Optional[dict] = None) -> str:
        """
        Generate a command-ready natural English strategy briefing.

        Returns a multi-line string for Command Brain or terminal display.
        """
        if strategy is None:
            strategy = self.generate_strategy()

        ts = strategy["timestamp"]
        maneuvers = strategy["recommended_maneuvers"]
        actions = strategy["priority_actions"]
        fuel = strategy["fuel_impact_estimate"]
        timeline = strategy["execution_timeline"]
        confidence = strategy["confidence_score"]
        posture = strategy["overall_posture"]
        risk_level = strategy["risk_level"]

        lines = [
            f"KALA AGNI STRATEGY BRIEFING -- {ts[:19]} UTC",
            "=" * 56,
            "",
            f"OPERATIONAL POSTURE: {posture}",
            f"Risk Level: {risk_level}  |  Confidence: {confidence:.0f}%",
            f"Vulnerability: {strategy['vulnerability_score']:.1f}/100",
            "",
        ]

        # --- Recommended maneuvers ---
        lines.append(f"RECOMMENDED MANEUVERS ({len(maneuvers)}):")
        if maneuvers:
            for i, m in enumerate(maneuvers, 1):
                lines.append(
                    f"  {i}. [{m.get('priority', '?'):8s}] "
                    f"{m.get('trigger', '?')} -- {m['satellite']}"
                )
                lines.append(
                    f"     Alt: {m['current_altitude_km']:.0f} -> "
                    f"{m['target_altitude_km']:.0f} km "
                    f"(+{m['altitude_change_km']:.0f} km)"
                )
                dv = m["hohmann_transfer"]["total_dv_ms"]
                fuel_bp = m["fuel_cost_biprop"]["propellant_mass_kg"]
                lines.append(
                    f"     dv={dv:.1f} m/s | fuel={fuel_bp:.3f} kg | "
                    f"{m.get('recommendation', '')}"
                )
                if m.get("threat_ref"):
                    lines.append(f"     Trigger: {m['threat_ref']}")
        else:
            lines.append("  No maneuvers required at this time.")
        lines.append("")

        # --- Fuel impact ---
        lines.append("FUEL IMPACT:")
        lines.append(f"  Total delta-v:      {fuel['total_delta_v_ms']:.1f} m/s")
        lines.append(f"  Bipropellant fuel:  {fuel['total_fuel_biprop_kg']:.3f} kg")
        lines.append(f"  Electric fuel:      {fuel['total_fuel_electric_kg']:.3f} kg")
        lines.append(f"  Feasibility:        {fuel['feasibility']}")
        lines.append("")

        # --- Priority actions ---
        lines.append(f"PRIORITY ACTIONS ({len(actions)}):")
        for act in actions[:7]:
            deadline = f"T+{act['deadline_hours']:.1f}h"
            lines.append(
                f"  P{act['priority']:d} [{act['severity']:8s}] "
                f"{deadline:8s} | {act['action'][:65]}"
            )
        lines.append("")

        # --- Timeline ---
        lines.append(f"EXECUTION TIMELINE ({len(timeline)} events):")
        for evt in timeline[:8]:
            t_str = evt["time_utc"][11:19]  # HH:MM:SS
            lines.append(
                f"  {t_str} | [{evt['type']:12s}] {evt['event'][:55]}"
            )
        lines.append("")

        # --- Command readiness ---
        if posture == "AUTONOMOUS":
            cmd = "Strategy is cleared for autonomous execution."
        elif posture == "SUPERVISED":
            cmd = "Strategy requires supervisor confirmation before execution."
        elif posture == "MANUAL":
            cmd = "MANUAL CONTROL required. Autonomous execution disabled."
        else:
            cmd = "EMERGENCY PROTOCOL. Command Brain defers to human operator."

        lines.append(f"COMMAND READINESS: {cmd}")
        lines.append("")
        lines.append(
            f"Strategy generated in {strategy['strategy_cycle_ms']:.1f} ms."
        )

        return "\n".join(lines)

    # ===================================================================
    # INSTANCE TEST METHOD
    # ===================================================================

    def main(self):
        """Test function for terminal verification."""
        print("[KALA AGNI] Strategy Agent initializing...")
        strategy = self.generate_strategy(force_refresh=True)
        print(f"[KALA AGNI] Posture: {strategy['overall_posture']}")
        print(f"[KALA AGNI] Confidence: {strategy['confidence_score']:.0f}%")
        print(f"[KALA AGNI] Maneuvers: {len(strategy['recommended_maneuvers'])}")
        print("[KALA AGNI] Strategy Summary:")
        print(self.generate_strategy_summary(strategy))
        print("[KALA AGNI] Strategy generation complete.")


# =======================================================================
# MAIN -- Full OODA chain test: Perception -> Risk -> Strategy
# =======================================================================

def main():
    """Full chain: Perception -> Risk -> Strategy."""
    import io
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace"
        )

    print()
    print("=" * 72)
    print("  KALA AGNI Strategy Agent -- Full OODA Chain Test")
    print("  Perception -> Risk -> Strategy")
    print("=" * 72)

    # --- 1. Init full chain ---
    print("\n" + "-" * 52)
    print("  PHASE 1: Initialize Agent Chain")
    print("-" * 52)
    t_total = time.perf_counter()

    perception = PerceptionAgent()
    risk = RiskAgent(perception)
    strategy = StrategyAgent(risk, perception)

    print(f"  Perception: {len(perception.indian_sats)} Indian sats")
    print("  Risk Agent: ready")
    print("  Strategy Agent: ready")

    # --- 2. Perception ---
    print("\n" + "-" * 52)
    print("  PHASE 2: Perception")
    print("-" * 52)
    p_state = perception.get_current_state()
    print(f"  Tracked: {p_state['propagated_count']} / {p_state['total_indian_sats']}")
    print(f"  Health: {p_state['constellation_health']['overall_status']}")
    print(f"  Weather: {p_state['space_weather_impact']['storm_level']}")
    print(f"  Cycle: {p_state['perception_cycle_ms']:.1f} ms")

    # --- 3. Risk ---
    print("\n" + "-" * 52)
    print("  PHASE 3: Risk Assessment")
    print("-" * 52)
    r_assess = risk.assess_risks(p_state)
    print(f"  Vulnerability: {r_assess['constellation_vulnerability_score']:.1f}")
    print(f"  Risk level: {r_assess['overall_risk_level']}")
    print(f"  Threats: {len(r_assess['top_threats'])}")
    print(f"  Cycle: {r_assess['risk_cycle_ms']:.1f} ms")

    # --- 4. Strategy ---
    print("\n" + "-" * 52)
    print("  PHASE 4: Strategy Generation")
    print("-" * 52)
    s_plan = strategy.generate_strategy(r_assess, p_state)
    print(f"  Posture: {s_plan['overall_posture']}")
    print(f"  Confidence: {s_plan['confidence_score']:.0f}%")
    print(f"  Maneuvers: {len(s_plan['recommended_maneuvers'])}")
    print(f"  Actions: {len(s_plan['priority_actions'])}")
    print(f"  Timeline events: {len(s_plan['execution_timeline'])}")
    print(f"  Cycle: {s_plan['strategy_cycle_ms']:.1f} ms")

    # --- 5. Full strategy report ---
    print("\n" + "-" * 52)
    print("  PHASE 5: Strategy Briefing (Natural Language)")
    print("-" * 52)
    summary = strategy.generate_strategy_summary(s_plan)
    for line in summary.split("\n"):
        print(f"  {line}")

    # --- 6. Total chain timing ---
    total_ms = (time.perf_counter() - t_total) * 1000
    print("\n" + "-" * 52)
    print("  CHAIN TIMING SUMMARY")
    print("-" * 52)
    print(f"  Perception:  {p_state['perception_cycle_ms']:8.1f} ms")
    print(f"  Risk:        {r_assess['risk_cycle_ms']:8.1f} ms")
    print(f"  Strategy:    {s_plan['strategy_cycle_ms']:8.1f} ms")
    print(f"  Total chain: {total_ms:8.1f} ms")

    # --- 7. Cache test ---
    print("\n" + "-" * 52)
    print("  CACHE TEST (all three agents)")
    print("-" * 52)
    t0 = time.perf_counter()
    _ = perception.get_current_state()
    _ = risk.assess_risks()
    _ = strategy.generate_strategy()
    t1 = time.perf_counter()
    print(f"  Full chain cached call: {(t1-t0)*1000:.2f} ms")

    print()
    print("=" * 72)
    print("  KALA AGNI OODA chain test complete.")
    print("  Perception -> Risk -> Strategy: OPERATIONAL")
    print("  Next: Command Brain -> Dashboard -> Execution")
    print("=" * 72)
    print()


if __name__ == "__main__":
    main()
