import streamlit as st
import time
import pandas as pd
from pathlib import Path
from ui.components.agent_flow_visual import render_agent_flow_html
from command_brain import CommandBrain
from ui.components.cinematic_intro import show_intro

# ========================= CONFIG =========================
st.set_page_config(
    page_title="KALA AGNI",
    layout="wide",
    page_icon="🛰️",
    initial_sidebar_state="collapsed"
)

# ========================= INTRO TRANSITION LOGIC =========================
if 'intro_done' not in st.session_state:
    st.session_state.intro_done = False

if not st.session_state.intro_done:
    show_intro()
    time.sleep(5.5)  # Let CSS out-fade animation run completely
    st.session_state.intro_done = True
    st.rerun()  # Forces a silent and smooth re-render without refreshing the browser

# ========================= PREMIUM DARK THEME =========================
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;900&display=swap');

    .stApp {
        background-color: #060a10;
        color: #e0e6ed;
        font-family: 'Inter', -apple-system, sans-serif;
    }
    h1, h2, h3, h4, h5, h6 {
        color: #00e5ff;
        font-family: 'Inter', sans-serif;
        font-weight: 700;
        letter-spacing: 2px;
    }

    /* Command Brain Input — electric cyan glow */
    input[type="text"] {
        background-color: #0d1a2a !important;
        color: #e0e6ed !important;
        border: 2px solid rgba(0, 229, 255, 0.4) !important;
        border-radius: 12px !important;
        font-size: 1.4rem !important;
        padding: 16px !important;
        font-weight: 600 !important;
        font-family: 'Inter', sans-serif !important;
        box-shadow: 0 0 30px rgba(0, 229, 255, 0.15) !important;
        transition: all 0.3s ease !important;
    }
    input[type="text"]::placeholder { color: rgba(0, 229, 255, 0.4) !important; font-weight: 400; }
    input[type="text"]:focus {
        border-color: #00e5ff !important;
        box-shadow: 0 0 40px rgba(0, 229, 255, 0.3) !important;
    }

    .data-panel {
        background: linear-gradient(180deg, rgba(8,18,32,0.95) 0%, rgba(4,10,20,0.95) 100%);
        border: 1px solid rgba(0, 229, 255, 0.15);
        padding: 20px;
        border-radius: 14px;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
        backdrop-filter: blur(12px);
    }
    .metric-value {
        font-size: 2.4rem;
        color: #00e5ff;
        text-shadow: 0 0 12px rgba(0, 229, 255, 0.4);
        font-weight: 700;
    }

    .stDataFrame {
        background-color: #0a1018;
        border: 1px solid rgba(0, 229, 255, 0.1);
        border-radius: 10px;
    }

    .risk-critical { color: #ef4444; text-shadow: 0 0 12px #ef4444; }
    .risk-high     { color: #ff6a00; text-shadow: 0 0 12px #ff6a00; }
    .risk-medium   { color: #f59e0b; text-shadow: 0 0 12px #f59e0b; }
    .risk-low      { color: #10b981; text-shadow: 0 0 12px #10b981; }
</style>
""", unsafe_allow_html=True)


# ========================= HEADER =========================
st.markdown("""
<div style="display: flex; justify-content: center; align-items: center;
            border-bottom: 1px solid rgba(0,229,255,0.15); padding: 20px 0; margin-bottom: 28px;">
    <div style="text-align:center;">
        <h1 style="margin:0; font-size:2.8rem; letter-spacing:16px; color:#fff;
                   text-shadow: 0 0 30px rgba(0,229,255,0.35);">KALA AGNI</h1>
        <div style="font-size:0.85rem; color:rgba(0,229,255,0.6); letter-spacing:8px;
                    font-weight:300; margin-top:8px;">
            ADVANCED ORBITAL INTELLIGENCE PLATFORM
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# ========================= CORE BRAIN =========================
@st.cache_resource
def get_brain():
    return CommandBrain()

brain = get_brain()

# Auto refresh
st.markdown('<script>setTimeout(() => window.parent.location.reload(), 30000);</script>', unsafe_allow_html=True)

# ========================= COMMAND BRAIN INPUT =========================
cmd = st.text_input("🛰️ COMMAND INPUT",
                    placeholder="e.g., Show current status | Avoid storm for RISAT-1 | Station keep GSAT-2")

flow_placeholder = st.empty()

state = brain.perception.get_current_state()
sats = state.get('indian_constellation', [])

if cmd:
    agents = ["Perception", "Risk", "Strategy", "Execution"]
    for agent in agents:
        flow_placeholder.markdown(render_agent_flow_html(agent), unsafe_allow_html=True)
        time.sleep(0.6)

    response = brain.process_command(cmd)
    intent = response.get("intent", "STATUS")

    active_map = {"STATUS": "Perception", "RISK": "Risk", "STRATEGY": "Strategy", "EXECUTE": "Execution", "MANEUVER": "Execution"}
    active_agent = active_map.get(intent, "Perception")
    flow_placeholder.markdown(render_agent_flow_html(active_agent), unsafe_allow_html=True)

    st.markdown("### 🛰️ COMMAND EXECUTION REPORT")
    st.info(f"**Intent**: `{intent}` | **Target**: `{response.get('satellite', 'All Assets')}`")

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["💬 Natural Reply", "👁️ Perception", "⚠️ Risk", "♟️ Strategy", "🚀 Execution"])

    risk_eval = brain.risk.assess_risks(state)
    strat = brain.strategy.generate_strategy(risk_eval, state)
    report = brain.execution.execute_strategy(strat)

    with tab1: st.code(response.get("natural_reply", str(response)), language="markdown")
    with tab2: st.code(brain.perception.generate_perception_summary(state), language="markdown")
    with tab3: st.code(brain.risk.generate_risk_report(risk_eval), language="markdown")
    with tab4: st.code(brain.strategy.generate_strategy_summary(strat), language="markdown")
    with tab5: st.code(brain.execution.generate_execution_summary(report), language="markdown")

else:
    # Default Dashboard
    flow_placeholder.markdown(render_agent_flow_html("Perception"), unsafe_allow_html=True)

    st.markdown("### 🛰️ LIVE CONSTELLATION OVERVIEW")
    col1, col2, col3, col4 = st.columns(4)

    risk_eval = brain.risk.assess_risks(state)
    strat = brain.strategy.generate_strategy(risk_eval, state)
    wx = state.get('space_weather_impact', {})

    with col1:
        st.markdown("<div class='data-panel'><h4>👁️ Perception</h4>", unsafe_allow_html=True)
        st.markdown(f"Tracked Sats: <span class='metric-value'>{len(sats)}</span>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        st.markdown("<div class='data-panel'><h4>☀️ Space Weather</h4>", unsafe_allow_html=True)
        st.markdown(f"Kp Index: <span class='metric-value'>{wx.get('kp_index', 0)}</span>", unsafe_allow_html=True)
        st.markdown(f"Drag Risk: <span style='color:#f59e0b'>{wx.get('leo_drag_risk', 'LOW')}</span>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with col3:
        risk_level = risk_eval.get('overall_risk_level', 'LOW')
        risk_class = f"risk-{risk_level.lower()}"
        st.markdown("<div class='data-panel'><h4>⚠️ Risk Level</h4>", unsafe_allow_html=True)
        st.markdown(f"Threat: <span class='metric-value {risk_class}'>{risk_level}</span>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with col4:
        st.markdown("<div class='data-panel'><h4>♟️ Strategy</h4>", unsafe_allow_html=True)
        st.markdown(f"Posture: <span class='metric-value'>{strat.get('overall_posture', 'SUPERVISED')}</span>", unsafe_allow_html=True)
        st.markdown(f"Pending Maneuvers: <b>{len(strat.get('recommended_maneuvers', []))}</b>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("#### 🔭 CONSTELLATION TELEMETRY")
    if sats:
        df = pd.DataFrame(sats)
        cols = ['name', 'norad_id', 'orbit_class', 'altitude_km', 'speed_kms']
        st.dataframe(df[cols], use_container_width=True, height=420)

# ========================= 3D SATELLITE ORBIT VISUALIZER =========================
st.markdown("---")
st.markdown("### 🌍 3D LIVE SATELLITE ORBIT VISUALIZER")

sat_names = [s.get('name', 'Unknown') for s in sats] if sats else ["RISAT-1", "GSAT-2", "Cartosat-3"]
selected_sat = st.selectbox("Select Target Satellite for Live Tracking", sat_names)

three_html = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{
            margin: 0; overflow: hidden; background-color: #060a10;
            display: flex; justify-content: center; align-items: center;
            border: 1px solid rgba(0,229,255,0.15); border-radius: 14px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.4);
        }}
        #canvas-container {{ width: 100%; height: 600px; }}
        .overlay {{
            position: absolute; top: 15px; left: 20px;
            color: #00e5ff; font-family: 'Inter', sans-serif;
            font-size: 14px; font-weight: 500; letter-spacing: 1px;
            z-index: 10;
        }}
        .overlay .sat-name {{ font-size: 18px; font-weight: 700; }}
        .overlay .sat-status {{ color: rgba(255,255,255,0.4); font-size: 11px; letter-spacing: 3px; }}
    </style>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
</head>
<body>
    <div class="overlay">
        <div class="sat-name">🛰️ {selected_sat}</div>
        <div class="sat-status">ACTIVE REAL-TIME TRACKING</div>
    </div>
    <script>
        let scene, camera, renderer, earth, orbit, satellite;
        let t = 0;

        function init() {{
            scene = new THREE.Scene();
            camera = new THREE.PerspectiveCamera( 45, window.innerWidth / window.innerHeight, 0.1, 1000 );
            camera.position.set(0, 8, 16);
            camera.lookAt(0, 0, 0);

            renderer = new THREE.WebGLRenderer({{ antialias: true, alpha: true }});
            renderer.setSize( window.innerWidth, window.innerHeight );
            renderer.setClearColor(0x060a10, 1);
            document.body.appendChild( renderer.domElement );

            // Earth — cyan wireframe
            const earthGeo = new THREE.SphereGeometry( 4, 48, 48 );
            const earthMat = new THREE.MeshBasicMaterial({{ color: 0x00e5ff, wireframe: true, transparent: true, opacity: 0.35 }});
            earth = new THREE.Mesh( earthGeo, earthMat );
            scene.add( earth );

            // Atmosphere glow
            const atmoGeo = new THREE.SphereGeometry( 4.15, 48, 48 );
            const atmoMat = new THREE.MeshBasicMaterial({{ color: 0x00e5ff, transparent: true, opacity: 0.06 }});
            const atmo = new THREE.Mesh( atmoGeo, atmoMat );
            scene.add( atmo );

            // Target Orbit ring
            const orbitGeo = new THREE.RingGeometry( 6, 6.04, 128 );
            const orbitMat = new THREE.MeshBasicMaterial({{ color: 0x00e5ff, side: THREE.DoubleSide, transparent: true, opacity: 0.25 }});
            orbit = new THREE.Mesh( orbitGeo, orbitMat );
            orbit.rotation.x = Math.PI / 2 - 0.3;
            orbit.rotation.y = 0.4;
            scene.add( orbit );

            // Live Satellite Dot
            const satGeo = new THREE.SphereGeometry( 0.2, 16, 16 );
            const satMat = new THREE.MeshBasicMaterial({{ color: 0xffffff }});
            satellite = new THREE.Mesh( satGeo, satMat );

            // Orange glow
            const glowGeo = new THREE.SphereGeometry( 0.5, 16, 16 );
            const glowMat = new THREE.MeshBasicMaterial({{ color: 0xff8c00, transparent: true, opacity: 0.6, blending: THREE.AdditiveBlending }});
            const glow = new THREE.Mesh( glowGeo, glowMat );
            satellite.add(glow);

            orbit.add( satellite );

            window.addEventListener( 'resize', onWindowResize, false );
            animate();
        }}

        function onWindowResize() {{
            camera.aspect = window.innerWidth / window.innerHeight;
            camera.updateProjectionMatrix();
            renderer.setSize( window.innerWidth, window.innerHeight );
        }}

        function animate() {{
            requestAnimationFrame( animate );
            earth.rotation.y += 0.002;
            t += 0.01;
            satellite.position.x = 6.02 * Math.cos(t);
            satellite.position.y = 6.02 * Math.sin(t);
            satellite.position.z = 0;
            renderer.render( scene, camera );
        }}

        init();
    </script>
</body>
</html>
"""
st.components.v1.html(three_html, height=600)

st.caption("KALA AGNI • Advanced Orbital Intelligence Platform")