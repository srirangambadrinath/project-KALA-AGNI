import streamlit as st

def render_agent_flow_html(active_agent="Perception"):
    base_style = """
    <style>
    .flow-container {
        display: flex; justify-content: space-between; align-items: center;
        background: radial-gradient(circle at center, rgba(60,20,10,0.95) 0%, rgba(15,5,0,1) 100%);
        padding: 30px; border-radius: 15px; border: 2px solid #aa3300;
        margin-bottom: 30px;
        box-shadow: inset 0 0 50px rgba(255, 69, 0, 0.4), 0 10px 30px rgba(255, 69, 0, 0.3);
        position: relative; overflow: hidden;
    }
    .flow-container::before {
        content: ''; position: absolute; top:0; left:0; right:0; bottom:0;
        background: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E");
        opacity: 0.15; pointer-events: none; mix-blend-mode: color-dodge;
    }
    .agent-box {
        position: relative; z-index: 10;
        padding: 20px 30px; background: rgba(30, 5, 0, 0.9); border-radius: 10px;
        color: #cc6633; font-family: 'Courier New', monospace; font-size: 1.3rem; text-align: center; font-weight: bold;
        border: 2px solid #662211; transition: all 0.3s ease-out;
        box-shadow: 0 5px 15px rgba(0,0,0,0.5);
    }
    .agent-active {
        color: #000000 !important; background: linear-gradient(135deg, #ff8c00, #ffcc00) !important;
        border: 3px solid #ffffff !important;
        box-shadow: 0 0 60px #ff7700, inset 0 0 25px #ffffff !important;
        text-shadow: none !important;
        transform: scale(1.2) translateY(-5px);
    }
    .agent-active span {
        color: #000000 !important;
    }
    .flow-arrow {
        color: #ff4500; font-size: 50px; font-weight: bold; z-index: 10;
        text-shadow: 0 0 20px #ff0000;
        position: relative; transition: all 0.3s;
    }
    .arrow-active {
        color: #ffd700; text-shadow: 0 0 40px #ffd700;
        transform: scale(1.3);
    }
    .arrow-active::after {
        content: '🔥'; font-size: 35px; position: absolute; top: -35px; left: 10%;
        animation: floatUp 0.6s infinite alternate ease-in-out; text-shadow: none; filter: drop-shadow(0 0 15px #ffd700);
    }
    @keyframes floatUp { 
        0% { transform: translateY(0) scale(1); opacity: 0.8; } 
        100% { transform: translateY(-15px) scale(1.3); opacity: 1; } 
    }
    </style>
    """
    
    html = f"""{base_style}
    <div class="flow-container">
        <div class="agent-box {'agent-active' if active_agent == 'Perception' else ''}">👁️ OBSERVE<br/><br/><span style="font-size:0.9em;color:#ffaa00;">PERCEPTION<br/>AGENT</span></div>
        <div class="flow-arrow {'arrow-active' if active_agent in ['Risk','Strategy','Execution'] else ''}">→</div>
        <div class="agent-box {'agent-active' if active_agent == 'Risk' else ''}">⚠️ ORIENT<br/><br/><span style="font-size:0.9em;color:#ffaa00;">RISK<br/>AGENT</span></div>
        <div class="flow-arrow {'arrow-active' if active_agent in ['Strategy','Execution'] else ''}">→</div>
        <div class="agent-box {'agent-active' if active_agent == 'Strategy' else ''}">♟️ DECIDE<br/><br/><span style="font-size:0.9em;color:#ffaa00;">STRATEGY<br/>AGENT</span></div>
        <div class="flow-arrow {'arrow-active' if active_agent == 'Execution' else ''}">→</div>
        <div class="agent-box {'agent-active' if active_agent == 'Execution' else ''}">🚀 ACT<br/><br/><span style="font-size:0.9em;color:#ffaa00;">EXECUTION<br/>AGENT</span></div>
    </div>
    """
    return html

def render_agent_flow(active_agent="Perception"):
    st.markdown(render_agent_flow_html(active_agent), unsafe_allow_html=True)
