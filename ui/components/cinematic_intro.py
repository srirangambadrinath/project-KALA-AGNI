import streamlit as st
import streamlit.components.v1 as components


def show_intro():
    """Premium cinematic intro — commercial space-tech aesthetic.
    
    Zero-gravity floating UI, orbital ring animation, particle field,
    electric cyan + vibrant orange accents on deep space black.
    No government, military, or official national symbols.
    """
    if 'intro_done' not in st.session_state:
        st.session_state.intro_done = False

    if st.session_state.intro_done:
        return

    html_code = """
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;700;900&family=Outfit:wght@300;600;800&display=swap');

        * { margin: 0 !important; padding: 0 !important; box-sizing: border-box; }
        html, body {
            width: 100vw !important;
            height: 100vh !important;
            overflow: hidden !important;
            background: #000 !important;
            font-family: 'Inter', 'Outfit', -apple-system, sans-serif !important;
        }

        /* ── Container ─────────────────────────────────── */
        .intro-container {
            position: fixed !important;
            inset: 0 !important;
            width: 100vw !important;
            height: 100vh !important;
            background: radial-gradient(ellipse 120% 100% at 50% 55%, #030d1a 0%, #000000 70%) !important;
            z-index: 999999 !important;
            display: flex !important;
            flex-direction: column !important;
            justify-content: center !important;
            align-items: center !important;
            animation: introFadeOut 0.8s cubic-bezier(.4,0,.2,1) 5.5s forwards !important;
        }

        /* ── Starfield (CSS-only) ──────────────────────── */
        .starfield, .starfield-deep {
            position: absolute !important;
            inset: 0 !important;
            pointer-events: none !important;
        }
        .starfield {
            background-image:
                radial-gradient(1px 1px at 10% 15%, rgba(0,255,255,0.7), transparent),
                radial-gradient(1px 1px at 25% 80%, rgba(255,255,255,0.5), transparent),
                radial-gradient(1.5px 1.5px at 40% 30%, rgba(0,230,255,0.6), transparent),
                radial-gradient(1px 1px at 55% 65%, rgba(255,255,255,0.4), transparent),
                radial-gradient(1px 1px at 70% 20%, rgba(255,180,60,0.5), transparent),
                radial-gradient(1.5px 1.5px at 85% 75%, rgba(0,255,255,0.5), transparent),
                radial-gradient(1px 1px at 15% 50%, rgba(255,255,255,0.3), transparent),
                radial-gradient(1px 1px at 90% 40%, rgba(255,140,0,0.4), transparent),
                radial-gradient(1px 1px at 60% 90%, rgba(0,200,255,0.4), transparent),
                radial-gradient(1.5px 1.5px at 35% 10%, rgba(255,255,255,0.5), transparent) !important;
            animation: starDrift 60s linear infinite !important;
        }
        .starfield-deep {
            background-image:
                radial-gradient(0.5px 0.5px at 5% 25%, rgba(255,255,255,0.25), transparent),
                radial-gradient(0.5px 0.5px at 20% 70%, rgba(255,255,255,0.2), transparent),
                radial-gradient(0.5px 0.5px at 45% 45%, rgba(0,200,255,0.2), transparent),
                radial-gradient(0.5px 0.5px at 65% 15%, rgba(255,255,255,0.15), transparent),
                radial-gradient(0.5px 0.5px at 80% 55%, rgba(255,255,255,0.2), transparent),
                radial-gradient(0.5px 0.5px at 50% 85%, rgba(0,200,255,0.15), transparent),
                radial-gradient(0.5px 0.5px at 30% 60%, rgba(255,255,255,0.2), transparent) !important;
            animation: starDrift 120s linear infinite reverse !important;
            opacity: 0.6 !important;
        }

        /* ── Orbital Ring ──────────────────────────────── */
        .orbital-ring-wrapper {
            position: relative !important;
            width: 320px !important;
            height: 320px !important;
            display: flex !important;
            justify-content: center !important;
            align-items: center !important;
            margin-bottom: 48px !important;
            animation: floatUp 3s ease-in-out infinite alternate !important;
        }
        .ring-outer {
            position: absolute !important;
            width: 320px !important;
            height: 320px !important;
            border-radius: 50% !important;
            border: 2px solid rgba(0, 255, 255, 0.15) !important;
            box-shadow: 0 0 40px rgba(0,255,255,0.08), inset 0 0 40px rgba(0,255,255,0.04) !important;
            animation: orbitSpin 20s linear infinite !important;
        }
        .ring-outer::before, .ring-outer::after {
            content: '' !important;
            position: absolute !important;
            border-radius: 50% !important;
        }
        .ring-outer::before {
            width: 10px !important;
            height: 10px !important;
            background: #00e5ff !important;
            top: -5px !important;
            left: 50% !important;
            transform: translateX(-50%) !important;
            box-shadow: 0 0 20px #00e5ff, 0 0 40px #00e5ff !important;
        }
        .ring-outer::after {
            width: 6px !important;
            height: 6px !important;
            background: #ff8c00 !important;
            bottom: 20px !important;
            right: 10px !important;
            box-shadow: 0 0 16px #ff8c00, 0 0 32px #ff8c00 !important;
        }

        .ring-mid {
            position: absolute !important;
            width: 240px !important;
            height: 240px !important;
            border-radius: 50% !important;
            border: 1.5px solid rgba(0,230,255,0.12) !important;
            animation: orbitSpin 12s linear infinite reverse !important;
        }
        .ring-mid::before {
            content: '' !important;
            position: absolute !important;
            width: 7px !important;
            height: 7px !important;
            background: #ff6a00 !important;
            border-radius: 50% !important;
            top: -3px !important;
            left: 50% !important;
            transform: translateX(-50%) !important;
            box-shadow: 0 0 14px #ff6a00, 0 0 28px #ff6a00 !important;
        }

        .ring-inner {
            position: absolute !important;
            width: 160px !important;
            height: 160px !important;
            border-radius: 50% !important;
            border: 1px solid rgba(0,200,255,0.08) !important;
            animation: orbitSpin 8s linear infinite !important;
        }
        .ring-inner::before {
            content: '' !important;
            position: absolute !important;
            width: 5px !important;
            height: 5px !important;
            background: #00e5ff !important;
            border-radius: 50% !important;
            bottom: -2px !important;
            left: 50% !important;
            transform: translateX(-50%) !important;
            box-shadow: 0 0 12px #00e5ff !important;
        }

        /* ── Core Glow (center of rings) ───────────────── */
        .core-glow {
            position: absolute !important;
            width: 80px !important;
            height: 80px !important;
            border-radius: 50% !important;
            background: radial-gradient(circle, rgba(0,229,255,0.25) 0%, rgba(0,229,255,0.05) 50%, transparent 70%) !important;
            animation: corePulse 2.5s ease-in-out infinite alternate !important;
        }
        .core-glow::after {
            content: '' !important;
            position: absolute !important;
            inset: 20px !important;
            border-radius: 50% !important;
            background: radial-gradient(circle, rgba(255,140,0,0.4) 0%, transparent 70%) !important;
        }

        /* ── Title ─────────────────────────────────────── */
        .title {
            font-family: 'Outfit', sans-serif !important;
            font-size: 88px !important;
            font-weight: 800 !important;
            color: #ffffff !important;
            letter-spacing: 24px !important;
            text-shadow:
                0 0 30px rgba(0,229,255,0.4),
                0 0 60px rgba(0,229,255,0.15),
                0 2px 4px rgba(0,0,0,0.8) !important;
            margin: 0 !important;
            animation: titleReveal 1.2s cubic-bezier(.16,1,.3,1) 0.6s both,
                       titleGlow 3s ease-in-out infinite alternate !important;
            opacity: 0 !important;
        }

        /* ── Subtitle ──────────────────────────────────── */
        .subtitle {
            font-family: 'Inter', sans-serif !important;
            font-size: 16px !important;
            font-weight: 300 !important;
            color: rgba(0,229,255,0.7) !important;
            letter-spacing: 10px !important;
            text-transform: uppercase !important;
            margin-top: 18px !important;
            animation: subtitleReveal 1s cubic-bezier(.16,1,.3,1) 1.2s both !important;
            opacity: 0 !important;
        }

        /* ── Accent line ───────────────────────────────── */
        .accent-line {
            width: 120px !important;
            height: 1px !important;
            background: linear-gradient(90deg, transparent, #00e5ff, #ff8c00, transparent) !important;
            margin-top: 28px !important;
            animation: lineReveal 1.2s ease 1.5s both !important;
            opacity: 0 !important;
        }

        /* ── Bottom tagline ────────────────────────────── */
        .tagline {
            position: absolute !important;
            bottom: 48px !important;
            font-family: 'Inter', sans-serif !important;
            font-size: 11px !important;
            font-weight: 300 !important;
            color: rgba(255,255,255,0.2) !important;
            letter-spacing: 6px !important;
            text-transform: uppercase !important;
            animation: subtitleReveal 1s ease 2s both !important;
            opacity: 0 !important;
        }

        /* ── Floating particles (CSS-only) ─────────────── */
        .particle {
            position: absolute !important;
            border-radius: 50% !important;
            pointer-events: none !important;
            animation: particleFloat linear infinite !important;
        }
        .p1  { width:3px; height:3px; background:#00e5ff; left:8%;  top:70%; opacity:0.6; animation-duration:7s; }
        .p2  { width:2px; height:2px; background:#ff8c00; left:15%; top:85%; opacity:0.5; animation-duration:9s; animation-delay:1s; }
        .p3  { width:4px; height:4px; background:#00e5ff; left:25%; top:75%; opacity:0.4; animation-duration:11s; animation-delay:0.5s; }
        .p4  { width:2px; height:2px; background:#fff;    left:40%; top:90%; opacity:0.3; animation-duration:8s; animation-delay:2s; }
        .p5  { width:3px; height:3px; background:#ff6a00; left:55%; top:80%; opacity:0.5; animation-duration:10s; animation-delay:0.3s; }
        .p6  { width:2px; height:2px; background:#00e5ff; left:70%; top:88%; opacity:0.4; animation-duration:7.5s; animation-delay:1.5s; }
        .p7  { width:3px; height:3px; background:#fff;    left:82%; top:72%; opacity:0.25; animation-duration:12s; animation-delay:0.8s; }
        .p8  { width:2px; height:2px; background:#ff8c00; left:92%; top:82%; opacity:0.4; animation-duration:9s; animation-delay:2.5s; }
        .p9  { width:1px; height:1px; background:#00e5ff; left:48%; top:95%; opacity:0.5; animation-duration:6s; animation-delay:0.2s; }
        .p10 { width:2px; height:2px; background:#00e5ff; left:33%; top:60%; opacity:0.3; animation-duration:14s; animation-delay:1.2s; }

        /* ── Keyframes ─────────────────────────────────── */
        @keyframes orbitSpin {
            100% { transform: rotate(360deg); }
        }
        @keyframes corePulse {
            0%   { transform: scale(0.85); opacity: 0.6; }
            100% { transform: scale(1.2);  opacity: 1; }
        }
        @keyframes floatUp {
            0%   { transform: translateY(6px); }
            100% { transform: translateY(-6px); }
        }
        @keyframes titleReveal {
            0%   { opacity: 0; transform: translateY(30px) scale(0.95); }
            100% { opacity: 1; transform: translateY(0) scale(1); }
        }
        @keyframes titleGlow {
            0%   { text-shadow: 0 0 30px rgba(0,229,255,0.4), 0 0 60px rgba(0,229,255,0.1), 0 2px 4px rgba(0,0,0,0.8); }
            100% { text-shadow: 0 0 40px rgba(0,229,255,0.6), 0 0 80px rgba(0,229,255,0.2), 0 0 120px rgba(255,140,0,0.1), 0 2px 4px rgba(0,0,0,0.8); }
        }
        @keyframes subtitleReveal {
            0%   { opacity: 0; transform: translateY(16px); }
            100% { opacity: 1; transform: translateY(0); }
        }
        @keyframes lineReveal {
            0%   { opacity: 0; width: 0; }
            100% { opacity: 1; width: 120px; }
        }
        @keyframes starDrift {
            0%   { transform: translateY(0); }
            100% { transform: translateY(-40px); }
        }
        @keyframes particleFloat {
            0%   { transform: translateY(0) translateX(0); opacity: 0; }
            10%  { opacity: 1; }
            90%  { opacity: 1; }
            100% { transform: translateY(-100vh) translateX(20px); opacity: 0; }
        }
        @keyframes introFadeOut {
            0%   { opacity: 1; visibility: visible; }
            100% { opacity: 0; visibility: hidden; }
        }
    </style>
    </head>
    <body>
        <div class="intro-container" id="intro">

            <!-- Starfield layers -->
            <div class="starfield"></div>
            <div class="starfield-deep"></div>

            <!-- Orbital rings -->
            <div class="orbital-ring-wrapper">
                <div class="ring-outer"></div>
                <div class="ring-mid"></div>
                <div class="ring-inner"></div>
                <div class="core-glow"></div>
            </div>

            <!-- Title block -->
            <h1 class="title">KALA AGNI</h1>
            <div class="subtitle">ADVANCED ORBITAL INTELLIGENCE PLATFORM</div>
            <div class="accent-line"></div>

            <!-- Bottom tagline -->
            <div class="tagline">3D Space Situational Awareness</div>

            <!-- Floating particles -->
            <div class="particle p1"></div>
            <div class="particle p2"></div>
            <div class="particle p3"></div>
            <div class="particle p4"></div>
            <div class="particle p5"></div>
            <div class="particle p6"></div>
            <div class="particle p7"></div>
            <div class="particle p8"></div>
            <div class="particle p9"></div>
            <div class="particle p10"></div>
        </div>

        <script>
            setTimeout(() => {
                try {
                    const iframes = window.parent.document.querySelectorAll('iframe');
                    iframes.forEach(iframe => {
                        if (iframe.contentWindow === window) {
                            iframe.style.position = 'fixed';
                            iframe.style.top = '0';
                            iframe.style.left = '0';
                            iframe.style.width = '100vw';
                            iframe.style.height = '100vh';
                            iframe.style.zIndex = '999999';
                            iframe.style.border = 'none';

                            if (iframe.parentElement) {
                                iframe.parentElement.style.padding = '0';
                                iframe.parentElement.style.margin = '0';
                            }
                        }
                    });
                } catch(e) {
                    console.error("Iframe expansion failed: ", e);
                }
            }, 10);
        </script>
    </body>
    </html>
    """
    components.html(html_code, height=1080, width=1920, scrolling=False)