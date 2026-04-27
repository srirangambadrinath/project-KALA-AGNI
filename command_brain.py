# PROJECT KALA AGNI
# Advanced Orbital Intelligence Platform
# File: command_brain.py

"""
KALA AGNI Command Brain -- The Autonomous Mind
====================================================================
The central orchestrator that closes the full OODA loop:

    Perception -> Risk -> Strategy -> Execution -> COMMAND BRAIN

Accepts natural-language commands from the operator (or dashboard),
routes them through the agent chain, and returns rich responses
with both structured data and human-readable summaries.

For MVP, command parsing uses keyword + fuzzy matching (no LLM needed).
Production version can plug in an LLM for complex intent parsing.

    # Ready for UI integration -- Streamlit dashboard calls process_command()
"""

import sys
import re
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Project root on sys.path
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config import APP_TITLE, APP_VERSION, INDIAN_SAT_KEYWORDS
from agents.perception_agent import PerceptionAgent
from agents.risk_agent import RiskAgent
from agents.strategy_agent import StrategyAgent
from agents.execution_agent import ExecutionAgent
from core.orbit_utils import generate_maneuver, propagate_orbit, load_tle_from_cache

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="[KALA AGNI] %(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("kala_agni.brain")

# ---------------------------------------------------------------------------
# Fire-themed terminal formatting
# ---------------------------------------------------------------------------
FIRE_HEADER = r"""
    ██╗  ██╗ █████╗ ██╗      █████╗      █████╗  ██████╗ ███╗   ██╗██╗
    ██║ ██╔╝██╔══██╗██║     ██╔══██╗    ██╔══██╗██╔════╝ ████╗  ██║██║
    █████╔╝ ███████║██║     ███████║    ███████║██║  ███╗██╔██╗ ██║██║
    ██╔═██╗ ██╔══██║██║     ██╔══██║    ██╔══██║██║   ██║██║╚██╗██║██║
    ██║  ██╗██║  ██║███████╗██║  ██║    ██║  ██║╚██████╔╝██║ ╚████║██║
    ╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝    ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝╚═╝
"""

FIRE_DIVIDER = ">" * 60
EMBER_DIVIDER = "-" * 56


# ═══════════════════════════════════════════════════════════════════════════════
# COMMAND INTENT PARSING (keyword-based for MVP)
# ═══════════════════════════════════════════════════════════════════════════════

# Command intents and their keyword triggers
COMMAND_PATTERNS = {
    "STATUS": {
        "keywords": [
            "status", "show", "report", "overview", "current",
            "health", "constellation", "sitrep", "brief",
        ],
        "description": "Show current constellation status and perception report.",
    },
    "RISK": {
        "keywords": [
            "risk", "threat", "danger", "vulnerability", "assess",
            "conjunction", "collision", "close approach",
        ],
        "description": "Run risk assessment and show threats.",
    },
    "WEATHER": {
        "keywords": [
            "weather", "storm", "kp", "solar", "flux", "wind",
            "geomagnetic", "radiation", "drag",
        ],
        "description": "Show space weather conditions and impact.",
    },
    "MANEUVER": {
        "keywords": [
            "maneuver", "burn", "avoid", "evade", "station keep",
            "raise", "lower", "transfer", "hohmann", "delta-v",
            "station-keep", "stationkeep",
        ],
        "description": "Plan or execute a maneuver for a satellite.",
    },
    "STRATEGY": {
        "keywords": [
            "strategy", "plan", "recommend", "advise", "what should",
            "next steps", "action", "priority",
        ],
        "description": "Generate full strategy briefing.",
    },
    "EXECUTE": {
        "keywords": [
            "execute", "fire", "go", "apply", "commit",
            "simulate", "run maneuver",
        ],
        "description": "Execute (simulate) recommended maneuvers.",
    },
    "TRACK": {
        "keywords": [
            "track", "find", "locate", "where is", "position",
            "propagate", "orbit",
        ],
        "description": "Track a specific satellite's position.",
    },
    "HELP": {
        "keywords": ["help", "commands", "what can you do", "?"],
        "description": "Show available commands.",
    },
}


def _parse_intent(text: str) -> tuple:
    """
    Parse user text into (intent, satellite_name, params).

    Uses keyword matching with fuzzy satellite name extraction.
    Returns: (intent_str, sat_name_or_None, extra_params_dict)
    """
    text_lower = text.lower().strip()

    # --- Extract satellite name if present ---
    sat_name = None
    # Check for known Indian satellite keywords
    for kw in INDIAN_SAT_KEYWORDS:
        # Match patterns like "GSAT-1", "RISAT-1", "EOS-04"
        pattern = rf'\b({re.escape(kw)}[-\s]?\w*)\b'
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            sat_name = match.group(1).strip().upper()
            break

    # --- Match intent ---
    best_intent = "STATUS"  # default
    best_score = 0

    for intent, config in COMMAND_PATTERNS.items():
        score = 0
        for keyword in config["keywords"]:
            if keyword in text_lower:
                score += len(keyword)  # longer matches score higher
        if score > best_score:
            best_score = score
            best_intent = intent

    # --- Extract altitude if mentioned ---
    params = {}
    alt_match = re.search(r'(\d+)\s*km', text, re.IGNORECASE)
    if alt_match:
        params["target_altitude_km"] = float(alt_match.group(1))

    return best_intent, sat_name, params


class CommandBrain:
    """
    The Command Brain orchestrates the full OODA agent chain and
    responds to natural-language commands.

    Usage:
        brain = CommandBrain()
        response = brain.process_command("Show current status")
        print(response["natural_reply"])

    # Ready for UI integration
    """

    def __init__(self):
        """Initialize the full agent chain."""
        logger.info("Command Brain initializing full agent chain...")
        t0 = time.perf_counter()

        self.perception = PerceptionAgent()
        self.risk = RiskAgent(self.perception)
        self.strategy = StrategyAgent(self.risk, self.perception)
        self.execution = ExecutionAgent(self.strategy)

        # Command history
        self.command_history = []

        elapsed = time.perf_counter() - t0
        logger.info("Command Brain ONLINE (%.2f s)", elapsed)

    # ===================================================================
    # CORE: Process natural-language command
    # ===================================================================

    def process_command(self, user_text: str) -> dict:
        """
        Process a natural-language command through the full OODA loop.

        Parameters:
            user_text: Natural English command string.

        Returns:
            {
                "command": str,
                "intent": str,
                "satellite": str or None,
                "data": dict,        # structured response data
                "reply": str,        # natural language reply (legacy key)
                "natural_reply": str,# natural language reply
                "processing_ms": float,
            }

        # Ready for UI integration -- dashboard passes user input here
        """
        t0 = time.perf_counter()

        intent, sat_name, params = _parse_intent(user_text)
        logger.info(
            "Command: '%s' -> intent=%s, sat=%s",
            user_text[:50], intent, sat_name
        )

        # Route to handler
        handlers = {
            "STATUS": self._handle_status,
            "RISK": self._handle_risk,
            "WEATHER": self._handle_weather,
            "MANEUVER": self._handle_maneuver,
            "STRATEGY": self._handle_strategy,
            "EXECUTE": self._handle_execute,
            "TRACK": self._handle_track,
            "HELP": self._handle_help,
        }

        handler = handlers.get(intent, self._handle_status)
        data, reply = handler(sat_name, params)

        elapsed_ms = (time.perf_counter() - t0) * 1000

        response = {
            "command": user_text,
            "intent": intent,
            "satellite": sat_name,
            "data": data,
            "reply": reply,
            "natural_reply": reply,
            "processing_ms": round(elapsed_ms, 2),
        }

        # Log command
        self.command_history.append({
            "time": datetime.now(timezone.utc).isoformat(),
            "command": user_text,
            "intent": intent,
            "processing_ms": elapsed_ms,
        })

        return response

    # ===================================================================
    # COMMAND HANDLERS
    # ===================================================================

    def _handle_status(self, sat_name, params) -> tuple:
        """Full constellation status."""
        state = self.perception.get_current_state()
        summary = self.perception.generate_perception_summary(state)

        return state, summary

    def _handle_risk(self, sat_name, params) -> tuple:
        """Risk assessment."""
        state = self.perception.get_current_state()
        assessment = self.risk.assess_risks(state)
        report = self.risk.generate_risk_report(assessment)

        return assessment, report

    def _handle_weather(self, sat_name, params) -> tuple:
        """Space weather impact."""
        state = self.perception.get_current_state()
        wx = state.get("space_weather_impact", {})

        lines = [
            "SPACE WEATHER BRIEFING",
            "=" * 40,
            "",
            f"Kp Index:     {wx.get('kp_index', 0):.1f} ({wx.get('storm_level', 'N/A')})",
            f"Storm:        {wx.get('storm_description', 'N/A')}",
            f"Solar Flux:   {wx.get('solar_flux_sfu', 0):.1f} SFU",
            f"Solar Wind:   {wx.get('solar_wind_speed_kms', 0):.0f} km/s",
            f"LEO Drag:     {wx.get('leo_drag_risk', 'N/A')}",
            f"Radiation:    {wx.get('radiation_risk', 'N/A')}",
            f"Overall:      {wx.get('overall_impact', 'N/A')}",
        ]

        return wx, "\n".join(lines)

    def _handle_maneuver(self, sat_name, params) -> tuple:
        """Plan a maneuver for a specific satellite."""
        if not sat_name:
            # No satellite specified -- run full strategy
            return self._handle_strategy(sat_name, params)

        target_alt = params.get("target_altitude_km")

        try:
            if target_alt:
                result = generate_maneuver(sat_name, target_altitude_km=target_alt)
            else:
                result = generate_maneuver(sat_name)
        except Exception as e:
            return {"error": str(e)}, f"Failed to plan maneuver for {sat_name}: {e}"

        if "error" in result:
            return result, f"Maneuver planning failed: {result['error']}"

        lines = [
            f"MANEUVER PLAN: {result['satellite']}",
            "=" * 40,
            "",
            f"Current altitude: {result['current_altitude_km']:.1f} km",
            f"Target altitude:  {result['target_altitude_km']:.1f} km",
            f"Altitude change:  +{result['altitude_change_km']:.1f} km",
            "",
            f"Delta-v required: {result['hohmann_transfer']['total_dv_ms']:.1f} m/s",
            f"  Burn 1 (depart):    {result['hohmann_transfer']['dv1_kms']*1000:.3f} m/s",
            f"  Burn 2 (circularize): {result['hohmann_transfer']['dv2_kms']*1000:.3f} m/s",
            f"Transfer time:    {result['hohmann_transfer']['transfer_time_hours']:.2f} hours",
            "",
            f"Fuel (biprop):    {result['fuel_cost_biprop']['propellant_mass_kg']:.3f} kg",
            f"Fuel (electric):  {result['fuel_cost_electric']['propellant_mass_kg']:.3f} kg",
            f"Feasible:         {result['feasible']}",
            f"Recommendation:   {result['recommendation']}",
        ]

        return result, "\n".join(lines)

    def _handle_strategy(self, sat_name, params) -> tuple:
        """Full strategy generation."""
        plan = self.strategy.generate_strategy()
        summary = self.strategy.generate_strategy_summary(plan)

        return plan, summary

    def _handle_execute(self, sat_name, params) -> tuple:
        """Execute (simulate) strategy."""
        report = self.execution.execute_strategy()
        summary = self.execution.generate_execution_summary(report)

        return report, summary

    def _handle_track(self, sat_name, params) -> tuple:
        """Track a specific satellite."""
        if not sat_name:
            return (
                {"error": "No satellite specified"},
                "Please specify a satellite name. Example: 'Track GSAT-1'"
            )

        # Find satellite in constellation
        state = self.perception.get_current_state()
        constellation = state.get("indian_constellation", [])

        target = None
        for s in constellation:
            if sat_name.upper() in s["name"].upper():
                target = s
                break

        if not target:
            return (
                {"error": f"Satellite '{sat_name}' not found"},
                f"Could not find '{sat_name}' in the Indian constellation."
            )

        pos = target["position_km"]
        lines = [
            f"TRACKING: {target['name']}",
            "=" * 40,
            "",
            f"NORAD ID:   {target['norad_id']}",
            f"Altitude:   {target['altitude_km']:.1f} km",
            f"Speed:      {target['speed_kms']:.4f} km/s",
            f"Orbit:      {target['orbit_class']}",
            f"Position:   [{pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f}] km (TEME)",
            f"Time:       {target['time_utc'][:19]} UTC",
        ]

        return target, "\n".join(lines)

    def _handle_help(self, sat_name, params) -> tuple:
        """Show available commands."""
        lines = [
            "KALA AGNI -- Available Commands",
            "=" * 40,
            "",
        ]
        for intent, config in COMMAND_PATTERNS.items():
            keywords = ", ".join(config["keywords"][:4])
            lines.append(f"  {intent:12s} : {config['description']}")
            lines.append(f"               Keywords: {keywords}")
            lines.append("")

        lines.append("Satellite names are auto-detected:")
        lines.append(f"  e.g., GSAT-1, RISAT-1, IRNSS-1A, EOS-04")
        lines.append("")
        lines.append("Examples:")
        lines.append('  "Show current status"')
        lines.append('  "Track GSAT-1"')
        lines.append('  "Plan maneuver for RISAT-1"')
        lines.append('  "Execute strategy"')

        return {"commands": list(COMMAND_PATTERNS.keys())}, "\n".join(lines)

    def main(self):
        print("[KALA AGNI] Command Brain ONLINE - Running demo commands...")
        test_commands = ["Kala Agni, show current status", "Avoid storm for RISAT-1", "Station keep GSAT-2"]
        for i, cmd in enumerate(test_commands, 1):
            print(f"\n--- Test {i}: {cmd} ---")
            response = self.process_command(cmd)
            print(response.get("natural_reply", response))
        print("\n[KALA AGNI] Command Brain demo complete.")


# =======================================================================
# MAIN -- Interactive test with 3 sample commands
# =======================================================================

def main():
    """Test the Command Brain with 3 sample commands."""
    import io
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace"
        )

    print(FIRE_HEADER)
    print(f"  {APP_TITLE} v{APP_VERSION}")
    print("  Advanced Orbital Intelligence Platform")
    print(f"  {FIRE_DIVIDER}")
    print()

    # --- Initialize Command Brain ---
    print(EMBER_DIVIDER)
    print("  INITIALIZING COMMAND BRAIN...")
    print(EMBER_DIVIDER)
    brain = CommandBrain()
    print()

    # --- Test commands ---
    test_commands = [
        "Kala Agni, show current status",
        "Avoid storm for RISAT-1",
        "Station keep GSAT-2",
    ]

    for i, cmd in enumerate(test_commands, 1):
        print()
        print(FIRE_DIVIDER)
        print(f"  COMMAND {i}: \"{cmd}\"")
        print(FIRE_DIVIDER)
        print()

        response = brain.process_command(cmd)

        print(f"  Intent:      {response['intent']}")
        print(f"  Satellite:   {response['satellite'] or 'N/A'}")
        print(f"  Processing:  {response['processing_ms']:.1f} ms")
        print()
        print(EMBER_DIVIDER)
        print("  RESPONSE:")
        print(EMBER_DIVIDER)
        for line in response["reply"].split("\n"):
            print(f"  {line}")
        print()

    # --- Command history ---
    print()
    print(FIRE_DIVIDER)
    print("  COMMAND HISTORY")
    print(FIRE_DIVIDER)
    for entry in brain.command_history:
        print(
            f"  {entry['time'][:19]} | "
            f"{entry['intent']:12s} | "
            f"{entry['processing_ms']:8.1f} ms | "
            f"{entry['command'][:40]}"
        )

    print()
    print(FIRE_DIVIDER)
    print(f"  {APP_TITLE} -- Command Brain OPERATIONAL")
    print("  Full OODA loop: Perception -> Risk -> Strategy -> Execution")
    print("  Next: Streamlit Dashboard for visual command interface")
    print(FIRE_DIVIDER)
    print()


if __name__ == "__main__":
    main()
