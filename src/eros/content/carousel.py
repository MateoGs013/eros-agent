import html
from typing import List
from eros.content.models import ContentPost, SlideItem


class CarouselRenderer:
    """Renderizador de Carousels en HTML/CSS de alto impacto para LinkedIn."""

    @staticmethod
    def render_html(post: ContentPost, auto_print: bool = False) -> str:
        """Genera un documento HTML standalone con visor interactivo y estilos @media print listos para PDF."""
        slides = post.carousel_slides
        if not slides:
            return "<html><body><p>No hay diapositivas para este post.</p></body></html>"

        slides_html = ""
        for i, s in enumerate(slides):
            is_active = "active" if i == 0 else ""
            bullets_html = ""
            for b in s.bullets:
                bullets_html += f"""
                <li class="bullet-item">
                    <span class="bullet-icon">⚡</span>
                    <span class="bullet-text">{html.escape(b)}</span>
                </li>
                """

            badge_html = ""
            if s.metric_badge:
                badge_html = f"""
                <div class="metric-badge">
                    <span class="metric-dot"></span>
                    <span>{html.escape(s.metric_badge)}</span>
                </div>
                """

            code_html = ""
            if s.code_snippet:
                code_html = f"""
                <div class="code-box">
                    <div class="code-header">
                        <span class="code-dot red"></span>
                        <span class="code-dot yellow"></span>
                        <span class="code-dot green"></span>
                        <span class="code-title">architecture.ts</span>
                    </div>
                    <pre><code>{html.escape(s.code_snippet)}</code></pre>
                </div>
                """

            footer_text = s.footer or "Mateo Sonzogni · mateogs.tech"

            slides_html += f"""
            <div class="slide {is_active}" data-index="{i}">
                <div class="slide-inner">
                    <div class="slide-top">
                        <div class="brand">
                            <span class="brand-logo">M</span>
                            <span class="brand-name">MATEO GABRIEL SONZOGNI</span>
                        </div>
                        <div class="slide-counter">
                            <span class="counter-num">{s.index:02d}</span>
                            <span class="counter-total">/ {len(slides):02d}</span>
                        </div>
                    </div>

                    <div class="slide-content">
                        {badge_html}
                        <h1 class="slide-title">{html.escape(s.title)}</h1>
                        <p class="slide-subtitle">{html.escape(s.subtitle)}</p>

                        {code_html}

                        <ul class="bullet-list">
                            {bullets_html}
                        </ul>
                    </div>

                    <div class="slide-footer">
                        <div class="footer-left">
                            <span class="swipe-hint">DESLIZÁ PARA MÁS ➔</span>
                        </div>
                        <div class="footer-right">
                            <span class="footer-meta">{html.escape(footer_text)}</span>
                        </div>
                    </div>
                </div>
            </div>
            """

        print_script = ""
        if auto_print:
            print_script = "<script>window.addEventListener('load', () => setTimeout(() => window.print(), 400));</script>"

        return f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(post.title)} — Carousel LinkedIn</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600&family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-base: #06080b;
            --bg-card: #0d1117;
            --bg-surface: #151b23;
            --border-glow: rgba(16, 185, 129, 0.25);
            --border-subtle: #21262d;
            --text-main: #f0f6fc;
            --text-muted: #8b949e;
            --accent-emerald: #10b981;
            --accent-cyan: #06b6d4;
            --accent-glow: rgba(6, 182, 212, 0.15);
            --slide-w: 1080px;
            --slide-h: 1350px;
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        body {{
            background: #020408;
            color: var(--text-main);
            font-family: 'Inter', system-ui, -apple-system, sans-serif;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 20px 10px 60px;
        }}

        /* Toolbar UI (Oculta al imprimir) */
        .toolbar {{
            background: rgba(13, 17, 23, 0.85);
            backdrop-filter: blur(12px);
            border: 1px solid var(--border-subtle);
            border-radius: 14px;
            padding: 12px 24px;
            margin-bottom: 24px;
            display: flex;
            align-items: center;
            gap: 16px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.6);
            position: sticky;
            top: 16px;
            z-index: 100;
        }}

        .btn {{
            background: var(--bg-surface);
            color: var(--text-main);
            border: 1px solid var(--border-subtle);
            padding: 8px 16px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }}

        .btn:hover {{
            background: #21262d;
            border-color: var(--accent-emerald);
            color: #fff;
        }}

        .btn-primary {{
            background: #10b981;
            color: #06080b;
            border-color: #10b981;
        }}

        .btn-primary:hover {{
            background: #059669;
            border-color: #059669;
            color: #fff;
        }}

        .pill-group {{
            display: flex;
            gap: 6px;
        }}

        .pill {{
            background: #161b22;
            color: var(--text-muted);
            border: 1px solid var(--border-subtle);
            width: 32px;
            height: 32px;
            border-radius: 6px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 13px;
            font-weight: 700;
            cursor: pointer;
        }}

        .pill.active {{
            background: var(--accent-emerald);
            color: #06080b;
            border-color: var(--accent-emerald);
        }}

        /* Contenedor de Diapositivas */
        .carousel-stage {{
            width: 540px;
            height: 675px; /* Proporción 4:5 a escala 0.5x en navegador */
            position: relative;
            background: var(--bg-base);
            border-radius: 16px;
            box-shadow: 0 25px 60px rgba(0, 0, 0, 0.8), 0 0 0 1px rgba(255, 255, 255, 0.05);
            overflow: hidden;
        }}

        .slide {{
            position: absolute;
            top: 0;
            left: 0;
            width: 1080px;
            height: 1350px;
            transform-origin: top left;
            transform: scale(0.5); /* Escala responsiva en pantalla */
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.25s ease;
            background: radial-gradient(circle at 10% 20%, rgba(16, 185, 129, 0.08) 0%, transparent 40%),
                        radial-gradient(circle at 90% 80%, rgba(6, 182, 212, 0.06) 0%, transparent 45%),
                        #07090e;
        }}

        .slide.active {{
            opacity: 1;
            pointer-events: auto;
        }}

        .slide-inner {{
            width: 100%;
            height: 100%;
            padding: 80px 75px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            position: relative;
            border: 1px solid rgba(255, 255, 255, 0.04);
        }}

        /* Header Slide */
        .slide-top {{
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}

        .brand {{
            display: flex;
            align-items: center;
            gap: 16px;
        }}

        .brand-logo {{
            width: 44px;
            height: 44px;
            background: linear-gradient(135deg, #10b981, #06b6d4);
            color: #06080b;
            font-weight: 900;
            font-size: 24px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 10px;
        }}

        .brand-name {{
            font-size: 20px;
            font-weight: 800;
            letter-spacing: 2px;
            color: #e6edf3;
        }}

        .slide-counter {{
            font-family: 'Fira Code', monospace;
            font-size: 22px;
            color: var(--text-muted);
        }}

        .counter-num {{
            color: var(--accent-emerald);
            font-weight: 700;
        }}

        /* Contenido Slide */
        .slide-content {{
            flex: 1;
            display: flex;
            flex-direction: column;
            justify-content: center;
            padding: 40px 0;
        }}

        .metric-badge {{
            display: inline-flex;
            align-items: center;
            gap: 12px;
            background: rgba(16, 185, 129, 0.12);
            border: 1px solid rgba(16, 185, 129, 0.35);
            color: #34d399;
            padding: 10px 22px;
            border-radius: 999px;
            font-size: 20px;
            font-weight: 700;
            margin-bottom: 30px;
            width: fit-content;
        }}

        .metric-dot {{
            width: 10px;
            height: 10px;
            background: #10b981;
            border-radius: 50%;
            box-shadow: 0 0 12px #10b981;
        }}

        .slide-title {{
            font-size: 64px;
            font-weight: 900;
            line-height: 1.15;
            letter-spacing: -1.5px;
            margin-bottom: 24px;
            background: linear-gradient(180deg, #ffffff 40%, #94a3b8 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}

        .slide-subtitle {{
            font-size: 28px;
            font-weight: 500;
            color: #94a3b8;
            line-height: 1.45;
            margin-bottom: 40px;
        }}

        .bullet-list {{
            list-style: none;
            display: flex;
            flex-direction: column;
            gap: 24px;
        }}

        .bullet-item {{
            display: flex;
            align-items: flex-start;
            gap: 20px;
            background: rgba(22, 27, 34, 0.7);
            border: 1px solid rgba(255, 255, 255, 0.08);
            padding: 24px 28px;
            border-radius: 16px;
        }}

        .bullet-icon {{
            font-size: 26px;
            color: var(--accent-emerald);
            flex-shrink: 0;
        }}

        .bullet-text {{
            font-size: 26px;
            font-weight: 500;
            color: #e2e8f0;
            line-height: 1.4;
        }}

        /* Caja de código */
        .code-box {{
            background: #020408;
            border: 1px solid #30363d;
            border-radius: 14px;
            margin-bottom: 35px;
            overflow: hidden;
            font-family: 'Fira Code', monospace;
        }}

        .code-header {{
            background: #161b22;
            padding: 12px 18px;
            display: flex;
            align-items: center;
            gap: 8px;
            border-bottom: 1px solid #30363d;
        }}

        .code-dot {{
            width: 10px;
            height: 10px;
            border-radius: 50%;
        }}
        .code-dot.red {{ background: #ff5f56; }}
        .code-dot.yellow {{ background: #ffbd2e; }}
        .code-dot.green {{ background: #27c93f; }}

        .code-title {{
            font-size: 14px;
            color: #8b949e;
            margin-left: 8px;
        }}

        .code-box pre {{
            padding: 22px 24px;
            font-size: 20px;
            color: #38bdf8;
            line-height: 1.5;
            white-space: pre-wrap;
            word-break: break-word;
        }}

        /* Footer Slide */
        .slide-footer {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-top: 30px;
            border-top: 1px solid rgba(255, 255, 255, 0.06);
        }}

        .swipe-hint {{
            font-size: 18px;
            font-weight: 800;
            letter-spacing: 2px;
            color: var(--accent-emerald);
        }}

        .footer-meta {{
            font-size: 20px;
            font-weight: 600;
            color: #64748b;
        }}

        /* ============================================================ */
        /* Estilos de Impresión / Exportación Directa a PDF de LinkedIn */
        /* ============================================================ */
        @media print {{
            @page {{
                size: 1080px 1350px;
                margin: 0;
            }}

            html, body {{
                background: #000;
                margin: 0;
                padding: 0;
                width: 1080px;
                height: auto;
            }}

            .toolbar {{
                display: none !important;
            }}

            .carousel-stage {{
                width: 1080px !important;
                height: auto !important;
                background: transparent !important;
                box-shadow: none !important;
                overflow: visible !important;
            }}

            .slide {{
                position: relative !important;
                width: 1080px !important;
                height: 1350px !important;
                transform: none !important;
                opacity: 1 !important;
                pointer-events: auto !important;
                page-break-after: always !important;
                break-after: page !important;
            }}
        }}
    </style>
</head>
<body>

    <div class="toolbar">
        <button class="btn" onclick="prevSlide()">◀ Anterior</button>
        <div class="pill-group" id="pillGroup">
            {"".join([f'<div class="pill {"active" if idx == 0 else ""}" onclick="goToSlide({idx})">{idx+1}</div>' for idx in range(len(slides))])}
        </div>
        <button class="btn" onclick="nextSlide()">Siguiente ▶</button>
        <button class="btn btn-primary" onclick="window.print()">🖨️ Imprimir / Guardar como PDF LinkedIn</button>
    </div>

    <div class="carousel-stage" id="stage">
        {slides_html}
    </div>

    {print_script}

    <script>
        let currentIndex = 0;
        const totalSlides = {len(slides)};
        const slides = document.querySelectorAll('.slide');
        const pills = document.querySelectorAll('.pill');

        function updateSlide() {{
            slides.forEach((s, idx) => {{
                s.classList.toggle('active', idx === currentIndex);
            }});
            pills.forEach((p, idx) => {{
                p.classList.toggle('active', idx === currentIndex);
            }});
        }}

        function nextSlide() {{
            if (currentIndex < totalSlides - 1) {{
                currentIndex++;
                updateSlide();
            }}
        }}

        function prevSlide() {{
            if (currentIndex > 0) {{
                currentIndex--;
                updateSlide();
            }}
        }}

        function goToSlide(idx) {{
            if (idx >= 0 && idx < totalSlides) {{
                currentIndex = idx;
                updateSlide();
            }}
        }}

        // Navegación por teclado
        window.addEventListener('keydown', (e) => {{
            if (e.key === 'ArrowRight' || e.key === ' ') {{
                nextSlide();
            }} else if (e.key === 'ArrowLeft') {{
                prevSlide();
            }}
        }});
    </script>
</body>
</html>
"""
