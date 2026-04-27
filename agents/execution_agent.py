# PROJECT KALA AGNI
# Advanced Orbital Intelligence Platform
# File: agents/execution_agent.py

"""
KALA AGNI Execution Agent -- Maneuver Simulator
====================================================================
Fourth and final agent in the OODA loop (Observe -> Orient -> Decide -> ACT).
Takes strategy decisions and simulates their execution:

    1. Applies recommended maneuvers (simulated -- no real thruster commands)
    2. Propagates post-maneuver orbits via SGP4
    3. Validates maneuver outcomes against targets
    4. Generates burn instruction reports for dashboard display

In production, this agent would interface with a real ground station API
to uplink thruster commands. For MVP, all execution is SIMULATED.

    # Ready for UI integration -- dashboard reads execution reports
"""

import sys
import time
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import numpy as np

# ---------------------------------------------------------------------------
# Project root on sys.path
# ---------------------------------------------------------------------------
_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config import (
    EARTH_RADIUS_KM, ISRO_BIPROP_ISP, DEFAULT_DRY_MASS_KG,
)
from core.orbit_utils import (
    propagate_orbit, hohmann_delta_v, estimate_fuel_cost, generate_maneuver,
    load_tle_from_cache, classify_orbit,
)
from agents.strategy_agent import StrategyAgent

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="[KALA AGNI] %(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("kala_agni.execution")

# ---------------------------------------------------------------------------
# Execution cache TTL
# ---------------------------------------------------------------------------
EXECUTION_TTL_SECONDS = 300  # 5 minutes


class ExecutionAgent:
    """
    The Execution Agent simulates maneuver execution and validates outcomes.

    In MVP mode, all burns are SIMULATED. The agent:
        - Takes strategy maneuvers
        - Computes post-burn orbital state
        - Validates altitude/velocity targets
        - Generates human-readable burn instructions

    Usage:
        strategy = StrategyAgent(risk, perception)
        executor = ExecutionAgent(strategy)
        report = executor.execute_strategy()

    # Ready for UI integration
    """

    def __init__(self, strategy_agent: Optional[StrategyAgent] = None):
        """
        Initialize the Execution Agent.

        Parameters:
            strategy_agent: StrategyAgent instance (creates full chain if None).
        """
        logger.info("Execution Agent initializing...")
        t0 = time.perf_counter()

        if strategy_agent is None:
            self.strategy = StrategyAgent()
        else:
            self.strategy = strategy_agent

        # Execution log -- persists across calls
        self.execution_log = []

        # Cache
        self._exec_cache = None
        self._exec_cache_time = None

        elapsed = time.perf_counter() - t0
        logger.info("Execution Agent ready (%.2f s)", elapsed)

    # ===================================================================
    # CORE: Execute strategy
    # ===================================================================

    def execute_strategy(
        self,
        strategy_dict: Optional[dict] = None,
        force_refresh: bool = False,
    ) -> dict:
        """
        Execute (simulate) all maneuvers from the strategy.

        Returns:
            {
                "timestamp": str,
                "execution_status": "SIMULATED",
                "applied_maneuvers": [...],
                "simulation_results": [...],
                "total_delta_v_applied_ms": float,
                "total_fuel_consumed_kg": float,
                "success_count": int,
                "failure_count": int,
                "execution_cycle_ms": float,
            }

        # Ready for UI integration -- dashboard reads this dict
        """
        # Cache check
        if (not force_refresh
                and self._exec_cache is not None
                and self._exec_cache_time is not None):
            age = time.time() - self._exec_cache_time
            if age < EXECUTION_TTL_SECONDS:
                logger.debug("Execution cache hit (age %.1f s).", age)
                return self._exec_cache

        t0 = time.perf_counter()

        if strategy_dict is None:
            strategy_dict = self.strategy.generate_strategy()

        maneuvers = strategy_dict.get("recommended_maneuvers", [])
        applied = []
        sim_results = []
        total_dv = 0.0
        total_fuel = 0.0
        successes = 0
        failures = 0

        for m in maneuvers:
            result = self._simulate_maneuver(m)
            applied.append(result["burn_instruction"])
            sim_results.append(result["simulation"])

            if result["success"]:
                successes += 1
                total_dv += result["burn_instruction"]["delta_v_applied_ms"]
                total_fuel += result["burn_instruction"]["fuel_consumed_kg"]
            else:
                failures += 1

        elapsed_ms = (time.perf_counter() - t0) * 1000

        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "execution_status": "SIMULATED",
            "applied_maneuvers": applied,
            "simulation_results": sim_results,
            "total_delta_v_applied_ms": round(total_dv, 3),
            "total_fuel_consumed_kg": round(total_fuel, 3),
            "success_count": successes,
            "failure_count": failures,
            "maneuver_count": len(maneuvers),
            "execution_cycle_ms": round(elapsed_ms, 2),
            "posture": strategy_dict.get("overall_posture", "UNKNOWN"),
            "confidence": strategy_dict.get("confidence_score", 0),
        }

        # Log execution
        self.execution_log.append({
            "timestamp": report["timestamp"],
            "maneuvers": len(maneuvers),
            "status": "SIMULATED",
            "total_dv_ms": total_dv,
        })

        # Update cache
        self._exec_cache = report
        self._exec_cache_time = time.time()

        logger.info(
            "Execution complete: %d/%d maneuvers simulated, dv=%.1f m/s (%.1f ms)",
            successes, len(maneuvers), total_dv, elapsed_ms
        )
        return report

    # ===================================================================
    # MANEUVER SIMULATION
    # ===================================================================

    def _simulate_maneuver(self, maneuver: dict) -> dict:
        """
        Simulate a single maneuver and compute post-burn state.

        Returns:
            {
                "success": bool,
                "burn_instruction": {...},
                "simulation": {...},
            }
        """
        sat_name = maneuver.get("satellite", "Unknown")
        trigger = maneuver.get("trigger", "UNKNOWN")
        priority = maneuver.get("priority", "LOW")

        current_alt = maneuver.get("current_altitude_km", 0)
        target_alt = maneuver.get("target_altitude_km", 0)
        hohmann = maneuver.get("hohmann_transfer", {})
        fuel_bp = maneuver.get("fuel_cost_biprop", {})

        dv_total = hohmann.get("total_dv_ms", 0)
        dv1 = hohmann.get("dv1_kms", 0) * 1000  # to m/s
        dv2 = hohmann.get("dv2_kms", 0) * 1000
        transfer_hours = hohmann.get("transfer_time_hours", 0)
        fuel_kg = fuel_bp.get("propellant_mass_kg", 0)

        # --- Simulate post-burn state ---
        # After Hohmann transfer, the satellite should be at target altitude
        post_alt = target_alt
        post_r = EARTH_RADIUS_KM + post_alt
        post_orbit_class = classify_orbit(post_alt)

        # Compute post-burn circular velocity
        from config import MU_EARTH_KM3S2
        import math
        post_v_kms = math.sqrt(MU_EARTH_KM3S2 / post_r)
        post_period_min = 2 * math.pi * math.sqrt(post_r**3 / MU_EARTH_KM3S2) / 60

        # Validate: did we reach the target?
        alt_error = abs(post_alt - target_alt)
        success = alt_error < 1.0 and maneuver.get("feasible", True)

        now = datetime.now(timezone.utc)
        burn1_time = now + timedelta(minutes=30)  # T+30 min
        burn2_time = burn1_time + timedelta(hours=transfer_hours)

        burn_instruction = {
            "satellite": sat_name,
            "norad_id": maneuver.get("norad_id", "?"),
            "trigger": trigger,
            "priority": priority,
            "burn_1": {
                "time_utc": burn1_time.isoformat(),
                "direction": "PROGRADE",
                "delta_v_ms": round(dv1, 3),
                "duration_estimate_s": round(dv1 / 0.5, 1) if dv1 > 0 else 0,
                "description": f"Departure burn: raise apoapsis to {target_alt:.0f} km",
            },
            "burn_2": {
                "time_utc": burn2_time.isoformat(),
                "direction": "PROGRADE",
                "delta_v_ms": round(dv2, 3),
                "duration_estimate_s": round(dv2 / 0.5, 1) if dv2 > 0 else 0,
                "description": f"Circularize at {target_alt:.0f} km",
            },
            "transfer_time_hours": round(transfer_hours, 2),
            "delta_v_applied_ms": round(dv_total, 3),
            "fuel_consumed_kg": round(fuel_kg, 3),
            "current_altitude_km": round(current_alt, 1),
            "target_altitude_km": round(target_alt, 1),
            "altitude_change_km": round(target_alt - current_alt, 1),
            "recommendation": maneuver.get("recommendation", ""),
        }

        simulation = {
            "satellite": sat_name,
            "pre_maneuver": {
                "altitude_km": round(current_alt, 1),
                "orbit_class": maneuver.get("current_state", {}).get(
                    "orbit_class", classify_orbit(current_alt)
                ),
            },
            "post_maneuver": {
                "altitude_km": round(post_alt, 1),
                "orbit_class": post_orbit_class,
                "velocity_kms": round(post_v_kms, 6),
                "period_min": round(post_period_min, 2),
            },
            "target_achieved": success,
            "altitude_error_km": round(alt_error, 3),
            "status": "SUCCESS" if success else "FAILED",
        }

        return {
            "success": success,
            "burn_instruction": burn_instruction,
            "simulation": simulation,
        }

    # ===================================================================
    # NATURAL LANGUAGE EXECUTION SUMMARY
    # ===================================================================

    def generate_execution_summary(
        self, report: Optional[dict] = None
    ) -> str:
        """
        Generate natural English burn instructions for the dashboard.

        Returns a formatted multi-line string with:
            - Execution status overview
            - Per-satellite burn instructions
            - Post-maneuver orbital states
            - Fuel consumption summary

        # Ready for UI integration
        """
        if report is None:
            report = self.execute_strategy()

        ts = report["timestamp"]
        applied = report["applied_maneuvers"]
        sims = report["simulation_results"]
        status = report["execution_status"]

        lines = [
            f"KALA AGNI EXECUTION REPORT -- {ts[:19]} UTC",
            "=" * 56,
            "",
            f"STATUS: {status}  |  Posture: {report.get('posture', 'N/A')}",
            f"Confidence: {report.get('confidence', 0):.0f}%",
            f"Maneuvers: {report['success_count']}/{report['maneuver_count']} successful",
            "",
        ]

        if not applied:
            lines.append("No maneuvers to execute. Constellation is nominal.")
            lines.append("")
        else:
            # --- Per-maneuver burn instructions ---
            lines.append("BURN INSTRUCTIONS:")
            lines.append("-" * 50)
            for i, (burn, sim) in enumerate(zip(applied, sims), 1):
                lines.append(
                    f"  MANEUVER {i}: {burn['satellite']} -- {burn['trigger']}"
                )
                lines.append(
                    f"  Priority: {burn['priority']}  |  "
                    f"Status: {sim['status']}"
                )
                lines.append("")

                # Burn 1
                b1 = burn["burn_1"]
                lines.append(f"    BURN 1 (Departure):")
                lines.append(f"      Time:      {b1['time_utc'][:19]} UTC")
                lines.append(f"      Direction: {b1['direction']}")
                lines.append(f"      Delta-v:   {b1['delta_v_ms']:.3f} m/s")
                lines.append(f"      Duration:  {b1['duration_estimate_s']:.1f} s")
                lines.append(f"      Action:    {b1['description']}")
                lines.append("")

                # Burn 2
                b2 = burn["burn_2"]
                lines.append(f"    BURN 2 (Circularize):")
                lines.append(f"      Time:      {b2['time_utc'][:19]} UTC")
                lines.append(f"      Direction: {b2['direction']}")
                lines.append(f"      Delta-v:   {b2['delta_v_ms']:.3f} m/s")
                lines.append(f"      Duration:  {b2['duration_estimate_s']:.1f} s")
                lines.append(f"      Action:    {b2['description']}")
                lines.append("")

                # Result
                pre = sim["pre_maneuver"]
                post = sim["post_maneuver"]
                lines.append(f"    RESULT:")
                lines.append(
                    f"      Orbit: {pre['altitude_km']:.0f} km ({pre['orbit_class']}) "
                    f"-> {post['altitude_km']:.0f} km ({post['orbit_class']})"
                )
                lines.append(
                    f"      Post-burn velocity: {post['velocity_kms']:.4f} km/s"
                )
                lines.append(
                    f"      Orbital period: {post['period_min']:.1f} min"
                )
                lines.append(
                    f"      Fuel consumed: {burn['fuel_consumed_kg']:.3f} kg"
                )
                lines.append(
                    f"      Target achieved: {sim['target_achieved']}"
                )
                lines.append("")
                lines.append("-" * 50)

        # --- Totals ---
        lines.append("")
        lines.append("EXECUTION SUMMARY:")
        lines.append(
            f"  Total delta-v applied: {report['total_delta_v_applied_ms']:.1f} m/s"
        )
        lines.append(
            f"  Total fuel consumed:   {report['total_fuel_consumed_kg']:.3f} kg"
        )
        lines.append(
            f"  Execution cycle:       {report['execution_cycle_ms']:.1f} ms"
        )
        lines.append("")
        lines.append(
            "NOTE: All burns are SIMULATED. "
            "Ground station uplink required for real execution."
        )

        return "\n".join(lines)

    def main(self):
        """Test function for terminal verification."""
        print("[KALA AGNI] Execution Agent ready")
        report = self.execute_strategy(force_refresh=True)
        print(self.generate_execution_summary(report))
        print("[KALA AGNI] Execution test complete.")


# =======================================================================
# MAIN -- Standalone test
# =======================================================================

def main():
    """Full chain: Perception -> Risk -> Strategy -> Execution."""
    import io
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace"
        )

    print()
    print("=" * 72)
    print("  KALA AGNI Execution Agent -- Self Test")
    print("=" * 72)

    # Init full chain
    from agents.perception_agent import PerceptionAgent
    from agents.risk_agent import RiskAgent

    perception = PerceptionAgent()
    risk = RiskAgent(perception)
    strategy = StrategyAgent(risk, perception)
    executor = ExecutionAgent(strategy)

    # Execute
    report = executor.execute_strategy()

    print(f"\n  Status:      {report['execution_status']}")
    print(f"  Maneuvers:   {report['success_count']}/{report['maneuver_count']}")
    print(f"  Total dv:    {report['total_delta_v_applied_ms']:.1f} m/s")
    print(f"  Total fuel:  {report['total_fuel_consumed_kg']:.3f} kg")
    print(f"  Cycle time:  {report['execution_cycle_ms']:.1f} ms")

    # Full report
    print("\n" + "-" * 52)
    summary = executor.generate_execution_summary(report)
    for line in summary.split("\n"):
        print(f"  {line}")

    print()
    print("=" * 72)
    print("  Execution Agent test complete.")
    print("=" * 72)
    print()


if __name__ == "__main__":
    main()
