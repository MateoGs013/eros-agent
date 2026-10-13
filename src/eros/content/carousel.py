import html
from typing import List
from eros.content.models import ContentPost, SlideItem


class CarouselRenderer:
    """Renderizador de Carousels con la identidad visual y técnica de Mateo Sonzogni (mateogs.tech)."""

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
                    <span class="bullet-icon">
                        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                            <polyline points="9 18 15 12 9 6"></polyline>
                        </svg>
                    </span>
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

            footer_text = s.footer or "Mateo Sonzogni // mateogs.tech"

            slides_html += f"""
            <div class="slide {is_active}" data-index="{i}">
                <div class="slide-inner">
                    <div class="slide-top">
                        <div class="brand">
                            <span class="brand-logo">M</span>
                            <div class="brand-info">
                                <span class="brand-name">MATEO SONZOGNI</span>
                                <span class="brand-sub">MATEOGS.TECH</span>
                            </div>
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
                            <span class="swipe-hint">DESLIZAR &rarr;</span>
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
    <link href="https://fonts.googleapis.com/css2?family=Martian+Mono:wght@400;500;600;700;800&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            /* Tokens visuales oficiales de mateogs.tech */
            --d-paper: #09090b;
            --d-surface: #121215;
            --d-surface-raised: #19191e;
            --d-ink: #f4f4f5;
            --d-dim: #929298;
            --d-faint: #7c7c82;
            --d-rule: rgba(255, 255, 255, 0.08);
            --d-rule-strong: rgba(255, 255, 255, 0.16);
            --d-sig: #ff3e00;
            --d-sig-hover: #ff551c;
            --d-sig-glow: rgba(255, 62, 0, 0.28);
            --d-sig-bg: rgba(255, 62, 0, 0.09);
            --font-mono: 'Martian Mono', ui-monospace, monospace;
            --font-display: 'Space Grotesk', system-ui, -apple-system, sans-serif;
            --slide-w: 1080px;
            --slide-h: 1350px;
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        body {{
            background: #040405;
            color: var(--d-ink);
            font-family: var(--font-display);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 20px 10px 60px;
        }}

        /* Toolbar UI (Oculta al imprimir) */
        .toolbar {{
            background: rgba(18, 18, 21, 0.88);
            backdrop-filter: blur(14px);
            border: 1px solid var(--d-rule-strong);
            border-radius: 12px;
            padding: 12px 24px;
            margin-bottom: 24px;
            display: flex;
            align-items: center;
            gap: 16px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.7);
            position: sticky;
            top: 16px;
            z-index: 100;
            font-family: var(--font-mono);
        }}

        .btn {{
            background: var(--d-surface-raised);
            color: var(--d-ink);
            border: 1px solid var(--d-rule);
            padding: 8px 16px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 600;
            font-family: var(--font-mono);
            cursor: pointer;
            transition: all 0.2s ease;
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }}

        .btn:hover {{
            background: #23232a;
            border-color: var(--d-sig);
            color: #fff;
        }}

        .btn-primary {{
            background: var(--d-sig);
            color: #ffffff;
            border-color: var(--d-sig);
            box-shadow: 0 0 16px var(--d-sig-glow);
        }}

        .btn-primary:hover {{
            background: var(--d-sig-hover);
            border-color: var(--d-sig-hover);
            color: #ffffff;
        }}

        .pill-group {{
            display: flex;
            gap: 6px;
        }}

        .pill {{
            background: var(--d-surface);
            color: var(--d-dim);
            border: 1px solid var(--d-rule);
            width: 32px;
            height: 32px;
            border-radius: 6px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 12px;
            font-family: var(--font-mono);
            font-weight: 700;
            cursor: pointer;
            transition: all 0.15s ease;
        }}

        .pill.active {{
            background: var(--d-sig);
            color: #ffffff;
            border-color: var(--d-sig);
            box-shadow: 0 0 10px var(--d-sig-glow);
        }}

        /* Contenedor de Diapositivas */
        .carousel-stage {{
            width: 540px;
            height: 675px; /* Proporción 4:5 a escala 0.5x en navegador */
            position: relative;
            background: var(--d-paper);
            border-radius: 14px;
            box-shadow: 0 30px 70px rgba(0, 0, 0, 0.9), 0 0 0 1px var(--d-rule);
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
            background-color: var(--d-paper);
            background-image:
                radial-gradient(circle at 90% 10%, rgba(255, 62, 0, 0.12) 0%, transparent 45%),
                radial-gradient(circle at 10% 90%, rgba(255, 62, 0, 0.05) 0%, transparent 40%),
                linear-gradient(to right, rgba(255, 255, 255, 0.022) 1px, transparent 1px),
                linear-gradient(to bottom, rgba(255, 255, 255, 0.022) 1px, transparent 1px);
            background-size: 100% 100%, 100% 100%, 54px 54px, 54px 54px;
        }}

        .slide.active {{
            opacity: 1;
            pointer-events: auto;
        }}

        .slide-inner {{
            width: 100%;
            height: 100%;
            padding: 85px 80px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            position: relative;
            border: 1px solid var(--d-rule);
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
            width: 46px;
            height: 46px;
            background: var(--d-surface);
            border: 1px solid var(--d-sig);
            color: var(--d-sig);
            font-family: var(--font-mono);
            font-weight: 800;
            font-size: 22px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 8px;
            box-shadow: 0 0 16px var(--d-sig-bg);
        }}

        .brand-info {{
            display: flex;
            flex-direction: column;
            gap: 3px;
        }}

        .brand-name {{
            font-family: var(--font-mono);
            font-size: 18px;
            font-weight: 700;
            letter-spacing: 1.5px;
            color: var(--d-ink);
        }}

        .brand-sub {{
            font-family: var(--font-mono);
            font-size: 11px;
            letter-spacing: 1px;
            color: var(--d-sig);
            font-weight: 600;
        }}

        .slide-counter {{
            font-family: var(--font-mono);
            font-size: 18px;
            color: var(--d-dim);
            background: var(--d-surface);
            border: 1px solid var(--d-rule);
            padding: 8px 16px;
            border-radius: 6px;
        }}

        .counter-num {{
            color: var(--d-sig);
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
            background: var(--d-sig-bg);
            border: 1px solid rgba(255, 62, 0, 0.45);
            color: var(--d-sig);
            padding: 10px 22px;
            border-radius: 999px;
            font-size: 18px;
            font-weight: 700;
            font-family: var(--font-mono);
            margin-bottom: 30px;
            width: fit-content;
        }}

        .metric-dot {{
            width: 10px;
            height: 10px;
            background: var(--d-sig);
            border-radius: 50%;
            box-shadow: 0 0 12px var(--d-sig);
        }}

        .slide-title {{
            font-family: var(--font-display);
            font-size: 64px;
            font-weight: 700;
            line-height: 1.15;
            letter-spacing: -1.5px;
            margin-bottom: 24px;
            color: #ffffff;
        }}

        .slide-subtitle {{
            font-family: var(--font-display);
            font-size: 28px;
            font-weight: 400;
            color: var(--d-dim);
            line-height: 1.45;
            margin-bottom: 40px;
        }}

        .bullet-list {{
            list-style: none;
            display: flex;
            flex-direction: column;
            gap: 22px;
        }}

        .bullet-item {{
            display: flex;
            align-items: flex-start;
            gap: 20px;
            background: var(--d-surface);
            border: 1px solid var(--d-rule);
            padding: 24px 28px;
            border-radius: 10px;
        }}

        .bullet-icon {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            color: var(--d-sig);
            flex-shrink: 0;
            padding-top: 4px;
        }}

        .bullet-text {{
            font-family: var(--font-display);
            font-size: 25px;
            font-weight: 400;
            color: var(--d-ink);
            line-height: 1.4;
        }}

        /* Caja de código */
        .code-box {{
            background: #050507;
            border: 1px solid var(--d-rule-strong);
            border-radius: 10px;
            margin-bottom: 35px;
            overflow: hidden;
            font-family: var(--font-mono);
        }}

        .code-header {{
            background: var(--d-surface);
            padding: 12px 18px;
            display: flex;
            align-items: center;
            gap: 8px;
            border-bottom: 1px solid var(--d-rule);
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
            font-size: 13px;
            color: var(--d-dim);
            margin-left: 8px;
            font-family: var(--font-mono);
        }}

        .code-box pre {{
            padding: 24px 26px;
            font-size: 20px;
            color: #ff9166;
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
            border-top: 1px solid var(--d-rule);
        }}

        .swipe-hint {{
            font-family: var(--font-mono);
            font-size: 17px;
            font-weight: 700;
            letter-spacing: 2px;
            color: var(--d-sig);
        }}

        .footer-meta {{
            font-family: var(--font-mono);
            font-size: 17px;
            font-weight: 500;
            color: var(--d-faint);
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
        <button class="btn" onclick="prevSlide()">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"></polyline></svg>
            Anterior
        </button>
        <div class="pill-group" id="pillGroup">
            {"".join([f'<div class="pill {"active" if idx == 0 else ""}" onclick="goToSlide({idx})">{idx+1}</div>' for idx in range(len(slides))])}
        </div>
        <button class="btn" onclick="nextSlide()">
            Siguiente
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>
        </button>
        <button class="btn btn-primary" onclick="window.print()">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 6 2 18 2 18 9"></polyline><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"></path><rect x="6" y="14" width="12" height="8"></rect></svg>
            Imprimir / Guardar como PDF LinkedIn
        </button>
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
