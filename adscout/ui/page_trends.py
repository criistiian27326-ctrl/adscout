"""Página Streamlit: Tendencias de nichos entre corridas usando first_seen_at."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from adscout.llm import LLMConfigError, LLMDailyLimitExceededError, LLMError
from adscout.models.market import MarketConfig
from adscout.services.pipeline import build_trends_dataframe
from adscout.ui.context import AppContext


def render_trends_page(ctx: AppContext, market: MarketConfig) -> None:
    st.header(f"Tendencias entre Corridas — {market.name} ({market.country})")
    st.caption(
        "Mide qué nichos (o palabras clave si aún no se ejecutó Gemini) suman más anuncios nuevos "
        "en la corrida más reciente usando `first_seen_at`."
    )

    ads = ctx.repository.list_ads(country=market.country, only_active=False)
    if not ads:
        st.info("No hay anuncios registrados todavía. Importa un archivo en la página **Mercado**.")
        return

    analyses = ctx.repository.list_all_analyses(ad_ids=[ad.ad_id for ad in ads])
    trends_df = build_trends_dataframe(ads=ads, analyses=analyses, market=market)

    if trends_df.empty:
        st.warning("No hay suficientes datos para calcular tendencias.")
        return

    st.subheader("Nichos / Temas en mayor crecimiento")
    st.dataframe(trends_df, width="stretch", hide_index=True)

    chart_df = trends_df.head(10).set_index("nicho")[["nuevos_ultima_corrida", "anteriores"]]
    st.bar_chart(chart_df)

    # Serie temporal de descubrimientos por fecha first_seen_at
    st.subheader("Nuevos anuncios detectados por fecha (`first_seen_at`)")
    daily_df = pd.DataFrame(
        [{"fecha": ad.first_seen_at.date(), "ad_id": ad.ad_id} for ad in ads]
    )
    daily_counts = daily_df.groupby("fecha").size().rename("anuncios_nuevos")
    st.line_chart(daily_counts)

    # Exportar tendencias a CSV
    csv_bytes = trends_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label="Exportar tendencias a CSV",
        data=csv_bytes,
        file_name=f"adscout_tendencias_{market.code}.csv",
        mime="text/csv",
    )

    # Validación rápida con Perplexity
    st.divider()
    st.subheader("Validar nicho en tendencia (Perplexity)")
    chosen_niche = st.selectbox("Elige un nicho de la tabla", options=trends_df["nicho"].tolist())
    if st.button("Validar nicho", key="trends_validate_niche_btn"):
        try:
            with st.spinner("Consultando Perplexity..."):
                val = ctx.perplexity.validate_niche(
                    nicho=chosen_niche,
                    market=market,
                    repository=ctx.repository,
                    limiter=ctx.limiter,
                )
            st.success(f"Validación completada para '{val.nicho}'")
            st.write(f"**Tendencia:** {val.tendencia}")
            st.write(f"**Saturación:** {val.saturacion}")
            if val.competidores:
                st.write("**Competidores:** " + ", ".join(val.competidores))
            st.write(f"**Resumen ejecutivo:** {val.resumen_ejecutivo}")
            if val.sources:
                st.markdown("**Fuentes:**")
                for src in val.sources:
                    st.markdown(f"- [{src}]({src})")
        except (LLMConfigError, LLMDailyLimitExceededError, LLMError) as exc:
            st.error(str(exc))
