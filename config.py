# PROJECT KALA AGNI
# Advanced Orbital Intelligence Platform
# File: config.py

"""
KALA AGNI Central Configuration
================================
Single source of truth for paths, constants, theme, and constellation filters.
Every module imports from here — never hardcode values elsewhere.

Design language: Deep space + electric cyan + vibrant orange accents.
"""

from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════════
# PROJECT PATHS
# ═══════════════════════════════════════════════════════════════════════════════

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
MODELS_DIR = PROJECT_ROOT / "models"
LOGS_DIR = PROJECT_ROOT / "logs"

# Cached data files (written by data_collector, read by all downstream modules)
SATELLITES_CACHE = DATA_DIR / "satellites.json"
SPACE_WEATHER_CACHE = DATA_DIR / "space_weather.json"

# Cache TTL in seconds (1 hour — matches Celestrak politeness policy)
CACHE_TTL_SECONDS = 3600


# ═══════════════════════════════════════════════════════════════════════════════
# ASTRODYNAMICS CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

# Earth parameters (WGS84)
EARTH_RADIUS_KM = 6371.0                     # Mean equatorial radius (km)
EARTH_RADIUS_M = EARTH_RADIUS_KM * 1000.0    # In meters for precise calcs
MU_EARTH_KM3S2 = 398600.4418                 # Gravitational parameter (km^3/s^2)
MU_EARTH_M3S2 = 3.986004418e14              # Gravitational parameter (m^3/s^2)
J2_EARTH = 1.08263e-3                        # J2 oblateness perturbation coefficient
EARTH_ROT_RAD_S = 7.2921159e-5               # Earth rotation rate (rad/s)

# Orbital mechanics
G0 = 9.80665                                 # Standard gravity (m/s^2) for Isp calc
LEO_MAX_ALT_KM = 2000.0                      # Low Earth Orbit ceiling
MEO_MAX_ALT_KM = 35786.0                    # Below GEO
GEO_ALT_KM = 35786.0                        # Geostationary altitude
GEO_RADIUS_KM = EARTH_RADIUS_KM + GEO_ALT_KM

# Typical satellite parameters
DEFAULT_DRY_MASS_KG = 100.0                   # Default dry mass for fuel calc
DEFAULT_ISP_S = 300.0                         # Specific impulse (bipropellant)
ISRO_BIPROP_ISP = 315.0                       # 440N LAM engine Isp (315s class)
ISRO_ELECTRIC_ISP = 1500.0                    # Electric propulsion (1500s class)

# Conjunction assessment
CONJUNCTION_THRESHOLD_KM = 10.0               # Close approach warning distance
CONJUNCTION_CRITICAL_KM = 1.0                 # Red alert distance
MANEUVER_LEAD_TIME_HOURS = 24.0               # Minimum planning horizon


# ═══════════════════════════════════════════════════════════════════════════════
# INDIAN CONSTELLATION FILTER
# ═══════════════════════════════════════════════════════════════════════════════
# Word-boundary matched in data_collector.py via regex (\b prefix)
# Update BOTH here and in data_collector if adding new programs

INDIAN_SAT_KEYWORDS = [
    "GSAT",          # Communication satellites (ISRO)
    "IRNSS",         # Indian Regional Navigation Satellite System
    "NAVIC",         # NavIC navigation constellation
    "INSAT",         # Indian National Satellite System
    "CARTOSAT",      # Earth observation / cartography
    "RISAT",         # Radar Imaging Satellite
    "OCEANSAT",      # Ocean & atmospheric studies
    "SCATSAT",       # Scatterometer satellite (wind)
    "RESOURCESAT",   # Natural resource monitoring
    "HYSIS",         # Hyperspectral Imaging Satellite
    "EOS",           # Earth Observation Satellite (new naming)
    "PIXEL",         # First private Indian sat (Pixxel)
    "DHRUVA",        # Dhruva Space payloads
    "ADITYA",        # Solar mission (Aditya-L1)
    "NISAR",         # NASA-ISRO SAR satellite
    "NVS",           # Navigation with Indian Constellation (NVS series)
    "AGN",           # Agnikul payloads
    "SKYROOT",       # Skyroot Aerospace
    "AGNIKUL",       # Agnikul Cosmos
]

# Orbit class boundaries for tagging
ORBIT_CLASSES = {
    "LEO": (150, 2000),        # Low Earth Orbit
    "MEO": (2000, 35000),      # Medium Earth Orbit
    "GEO": (35000, 36500),     # Geostationary/Geosynchronous
    "HEO": (36500, 500000),    # High Earth Orbit / highly elliptical
}


# ═══════════════════════════════════════════════════════════════════════════════
# KALA AGNI THEME — Design System
# ═══════════════════════════════════════════════════════════════════════════════
# Deep space backdrop + electric cyan + vibrant orange accents
# For Streamlit custom CSS injection and Plotly figure theming

THEME = {
    # --- Background layers (deep space) ---
    "bg_primary": "#0a0a0f",           # Near-black deep space
    "bg_secondary": "#0f1419",         # Dark panel background
    "bg_card": "#141a22",              # Card/widget background
    "bg_hover": "#1a2332",             # Hover state
    "bg_sidebar": "#0c1015",           # Sidebar darker shade

    # --- Accent (gold-orange-amber) ---
    "accent_gold": "#FFB700",          # Primary gold — headers, highlights
    "accent_saffron": "#FF6B00",       # Vibrant orange — accent color (legacy key name)
    "accent_amber": "#F59E0B",         # Warm amber — secondary accent
    "accent_fire": "#EF4444",          # Fire red — critical alerts
    "accent_ember": "#DC2626",         # Deep ember — danger states

    # --- Status indicators ---
    "status_safe": "#10B981",          # Green — nominal
    "status_caution": "#F59E0B",       # Amber — warning
    "status_warning": "#F97316",       # Orange — elevated risk
    "status_danger": "#EF4444",        # Red — critical
    "status_unknown": "#6B7280",       # Grey — no data

    # --- Text ---
    "text_primary": "#F9FAFB",         # Bright white text
    "text_secondary": "#9CA3AF",       # Muted grey
    "text_accent": "#FFB700",          # Gold highlighted text
    "text_dim": "#4B5563",             # Very dim labels

    # --- Borders & Lines ---
    "border_default": "#1F2937",       # Subtle borders
    "border_accent": "#FFB70033",      # Gold glow border (with alpha)
    "border_alert": "#EF444466",       # Red alert border

    # --- Gradients (CSS strings) ---
    "gradient_fire": "linear-gradient(135deg, #FF6B00 0%, #FFB700 50%, #F59E0B 100%)",
    "gradient_dark": "linear-gradient(180deg, #0a0a0f 0%, #141a22 100%)",
    "gradient_danger": "linear-gradient(135deg, #DC2626 0%, #EF4444 100%)",
    "gradient_sidebar": "linear-gradient(180deg, #0c1015 0%, #0a0a0f 100%)",

    # --- Shadows ---
    "shadow_gold": "0 0 20px rgba(255, 183, 0, 0.3)",
    "shadow_fire": "0 0 30px rgba(255, 107, 0, 0.4)",
    "shadow_card": "0 4px 20px rgba(0, 0, 0, 0.5)",
}

# Plotly-compatible color scale for orbital risk heatmaps
PLOTLY_FIRE_COLORSCALE = [
    [0.0, "#10B981"],    # Safe — green
    [0.25, "#F59E0B"],   # Caution — amber
    [0.5, "#F97316"],    # Warning — orange
    [0.75, "#EF4444"],   # Danger — red
    [1.0, "#DC2626"],    # Critical — deep red
]

# Plotly layout template for consistent dark theme across all charts
PLOTLY_LAYOUT = {
    "paper_bgcolor": THEME["bg_primary"],
    "plot_bgcolor": THEME["bg_secondary"],
    "font": {"color": THEME["text_primary"], "family": "Inter, Segoe UI, sans-serif"},
    "title_font": {"color": THEME["accent_gold"], "size": 18},
    "xaxis": {"gridcolor": THEME["border_default"], "zerolinecolor": THEME["border_default"]},
    "yaxis": {"gridcolor": THEME["border_default"], "zerolinecolor": THEME["border_default"]},
}


# ═══════════════════════════════════════════════════════════════════════════════
# APPLICATION METADATA
# ═══════════════════════════════════════════════════════════════════════════════

APP_TITLE = "KALA AGNI"
APP_SUBTITLE = "Advanced Orbital Intelligence Platform"
APP_VERSION = "1.0.0-mvp"
APP_AUTHOR = "KALA AGNI — Space Situational Awareness"


# ═══════════════════════════════════════════════════════════════════════════════
# DATA SOURCE URLs (centralized — change once, updates everywhere)
# ═══════════════════════════════════════════════════════════════════════════════

CELESTRAK_ACTIVE_URL = (
    "https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=TLE"
)
NOAA_KP_INDEX_URL = "https://services.swpc.noaa.gov/json/planetary_k_index_1m.json"
NOAA_SOLAR_WIND_URL = "https://services.swpc.noaa.gov/json/rtsw/rtsw_wind_1m.json"
NOAA_SOLAR_FLUX_URL = "https://services.swpc.noaa.gov/json/f107_cm_flux.json"


# ═══════════════════════════════════════════════════════════════════════════════
# STREAMLIT CUSTOM CSS (inject via st.markdown)
# ═══════════════════════════════════════════════════════════════════════════════

STREAMLIT_CUSTOM_CSS = f"""
<style>
    /* --- KALA AGNI Dark Fire Theme --- */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    .stApp {{
        background: {THEME['bg_primary']};
        font-family: 'Inter', 'Segoe UI', sans-serif;
    }}

    /* Sidebar */
    [data-testid="stSidebar"] {{
        background: {THEME['gradient_sidebar']};
        border-right: 1px solid {THEME['border_default']};
    }}

    /* Headers */
    h1, h2, h3 {{
        color: {THEME['accent_gold']} !important;
        font-weight: 700;
    }}

    /* Metric cards */
    [data-testid="stMetricValue"] {{
        color: {THEME['text_primary']};
        font-size: 1.8rem;
        font-weight: 600;
    }}

    /* Buttons */
    .stButton > button {{
        background: {THEME['gradient_fire']};
        color: {THEME['bg_primary']};
        border: none;
        border-radius: 8px;
        font-weight: 600;
        padding: 0.5rem 1.5rem;
        transition: all 0.3s ease;
        box-shadow: {THEME['shadow_gold']};
    }}

    .stButton > button:hover {{
        transform: translateY(-2px);
        box-shadow: {THEME['shadow_fire']};
    }}

    /* Dataframes */
    .stDataFrame {{
        border: 1px solid {THEME['border_default']};
        border-radius: 8px;
    }}

    /* Tabs */
    .stTabs [data-baseweb="tab"] {{
        color: {THEME['text_secondary']};
    }}
    .stTabs [aria-selected="true"] {{
        color: {THEME['accent_gold']} !important;
        border-bottom-color: {THEME['accent_gold']} !important;
    }}

    /* Scrollbar */
    ::-webkit-scrollbar {{
        width: 6px;
    }}
    ::-webkit-scrollbar-track {{
        background: {THEME['bg_primary']};
    }}
    ::-webkit-scrollbar-thumb {{
        background: {THEME['accent_gold']}33;
        border-radius: 3px;
    }}
</style>
"""
