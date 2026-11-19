"""AdScout — Punto de entrada de la aplicación Streamlit."""

from __future__ import annotations

import streamlit as st

from adscout.ui.context import build_app_context
from adscout.ui.page_detail import render_detail_page
from adscout.ui.page_market import render_market_page
from adscout.ui.page_ranking import render_ranking_page
from adscout.ui.page_trends import render_trends_page


def main() -> None:
    st.set_page_config(
        page_title="AdScout — Investigador de Productos Digitales",
        page_icon="🔎",
        layout="wide",
    )

    ctx = build_app_context()

    with st.sidebar:
        st.title("AdScout")
        st.caption("Investigador de productos digitales en Meta Ad Library")

        if not ctx.markets:
            st.error(
                f"No se encontraron archivos YAML en `{ctx.settings.markets_dir}`. "
                "Crea al menos `markets/brasil.yaml`."
            )
            return

        market_codes = list(ctx.markets.keys())
        default_idx = market_codes.index("brasil") if "brasil" in market_codes else 0
        selected_code = st.selectbox(
            "País / Mercado (YAML)",
            options=market_codes,
            index=default_idx,
            format_func=lambda code: f"{ctx.markets[code].name} ({ctx.markets[code].country} · {ctx.markets[code].language})",
        )
        active_market = ctx.markets[selected_code]

        page = st.radio(
            "Navegación",
            options=[
                "Mercado",
                "Ranking",
                "Detalle de producto/página",
                "Tendencias",
            ],
        )

        st.divider()
        st.caption("Estado de módulos opcionales")
        st.write(f"- Gemini: {'Configurado' if ctx.gemini.is_configured() else 'Inactivo (sin clave)'}")
        st.write(f"- Perplexity: {'Configurado' if ctx.perplexity.is_configured() else 'Inactivo (sin clave)'}")
        st.write(f"- Cuota LLM hoy: `{ctx.limiter.used_today()} / {ctx.limiter.daily_limit}`")

    if page == "Mercado":
        render_market_page(ctx, active_market)
    elif page == "Ranking":
        render_ranking_page(ctx, active_market)
    elif page == "Detalle de producto/página":
        render_detail_page(ctx, active_market)
    elif page == "Tendencias":
        render_trends_page(ctx, active_market)


if __name__ == "__main__":
    main()
