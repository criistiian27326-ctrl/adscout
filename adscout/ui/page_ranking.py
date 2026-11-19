"""Página Streamlit: Ranking ordenable por puntaje, filtros, desglose y exportación CSV."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from adscout.models.market import MarketConfig
from adscout.ui.context import AppContext


def render_ranking_page(ctx: AppContext, market: MarketConfig) -> None:
    st.header(f"Ranking de Productos Digitales — {market.name} ({market.country})")
    st.caption(
        "Transparencia del scoring (0–100): Meta NO publica ventas ni gasto de anuncios comerciales. "
        "El puntaje usa únicamente proxies observables (días activo, variantes, anuncios activos de la página, "
        "dominio de checkout conocido y palabras clave digitales)."
    )

    ranked_items = ctx.pipeline.get_ranked_ads(market=market, only_active=False)
    if not ranked_items:
        st.info(
            "No hay anuncios cargados para este mercado todavía. "
            "Ve a la página **Mercado** e importa `brasil_ads_sample.csv` en un clic."
        )
        return

    # Construcción de filtros
    all_niches = sorted({item["nicho"] for item in ranked_items})
    all_checkouts = sorted({item["matched_checkout"] for item in ranked_items if item["matched_checkout"]})

    f_col1, f_col2, f_col3, f_col4 = st.columns([2, 2, 1.5, 1])
    with f_col1:
        selected_niches = st.multiselect("Filtrar por nicho", options=all_niches, default=[])
    with f_col2:
        selected_checkouts = st.multiselect("Dominio de checkout", options=all_checkouts, default=[])
    with f_col3:
        min_days = st.number_input("Días activo mínimo", min_value=0, max_value=3650, value=0, step=1)
    with f_col4:
        only_active = st.checkbox("Solo activos", value=True)

    search_text = st.text_input("Buscar por página, titular o texto del anuncio", value="").strip().lower()

    filtered = []
    for item in ranked_items:
        ad = item["ad"]
        if only_active and not ad.is_active:
            continue
        if item["days_active"] < min_days:
            continue
        if selected_niches and item["nicho"] not in selected_niches:
            continue
        if selected_checkouts and item["matched_checkout"] not in selected_checkouts:
            continue
        if search_text:
            blob = f"{ad.page_name} {ad.headline} {ad.ad_text} {ad.link_domain or ''}".lower()
            if search_text not in blob:
                continue
        filtered.append(item)

    # KPIs rápidos
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Anuncios mostrados", len(filtered))
    k2.metric("Páginas únicas", len({i["ad"].page_id for i in filtered}))
    k3.metric(
        "Puntaje promedio",
        f"{sum(i['score'].total_score for i in filtered) / len(filtered):.1f}" if filtered else "0.0",
    )
    k4.metric(
        "Con checkout conocido",
        sum(1 for i in filtered if i["matched_checkout"]),
    )

    if not filtered:
        st.warning("Ningún anuncio coincide con los filtros actuales.")
        return

    rows = []
    for item in filtered:
        ad = item["ad"]
        score = item["score"]
        comp = score.as_dict()
        rows.append(
            {
                "Puntaje": score.total_score,
                "Página": ad.page_name,
                "Nicho": item["nicho"],
                "Titular": ad.headline or "(sin titular)",
                "Checkout": item["matched_checkout"] or "-",
                "Dominio": ad.link_domain or "-",
                "Días activo": item["days_active"],
                "Variantes": ad.variants_count,
                "Anuncios activos pág.": item["page_active_ads"],
                "Activo": ad.is_active,
                "Snapshot": ad.snapshot_url,
                "ad_id": ad.ad_id,
                "pts_dias": comp["days_active"].points,
                "pts_variantes": comp["variants_count"].points,
                "pts_pagina": comp["page_active_ads"].points,
                "pts_checkout": comp["checkout_domain"].points,
                "pts_keywords": comp["keyword_match"].points,
                "first_seen_at": ad.first_seen_at.isoformat(),
                "last_seen_at": ad.last_seen_at.isoformat(),
            }
        )

    df = pd.DataFrame(rows)

    display_cols = [
        "Puntaje",
        "Página",
        "Nicho",
        "Titular",
        "Checkout",
        "Días activo",
        "Variantes",
        "Anuncios activos pág.",
        "Activo",
        "Snapshot",
    ]

    st.dataframe(
        df[display_cols],
        width="stretch",
        hide_index=True,
        column_config={
            "Puntaje": st.column_config.ProgressColumn(
                "Puntaje",
                min_value=0,
                max_value=100,
                format="%.1f",
            ),
            "Snapshot": st.column_config.LinkColumn("Snapshot Meta", display_text="Abrir anuncio"),
        },
    )

    # Exportar a CSV
    csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label="Exportar ranking filtrado a CSV",
        data=csv_bytes,
        file_name=f"adscout_ranking_{market.code}.csv",
        mime="text/csv",
    )

    # Desglose transparente del puntaje por anuncio
    st.divider()
    st.subheader("Desglose transparente del puntaje por anuncio")
    ad_options = {
        f"[{item['score'].total_score:.1f} pts] {item['ad'].page_name} — {item['ad'].headline or item['ad'].ad_id}": item
        for item in filtered
    }
    chosen_label = st.selectbox("Selecciona un anuncio para inspeccionar su puntaje", options=list(ad_options.keys()))
    chosen = ad_options[chosen_label]
    chosen_ad = chosen["ad"]
    chosen_score = chosen["score"]

    c_left, c_right = st.columns([2, 1])
    with c_left:
        breakdown_rows = [
            {
                "Criterio": comp.label,
                "Puntos": comp.points,
                "Máximo": comp.max_points,
                "Evidencia observable": comp.evidence,
            }
            for comp in chosen_score.components
        ]
        st.dataframe(pd.DataFrame(breakdown_rows), width="stretch", hide_index=True)
    with c_right:
        st.metric("Puntaje Total", f"{chosen_score.total_score:.1f} / 100")
        st.write(f"**Página:** {chosen_ad.page_name} (`{chosen_ad.page_id}`)")
        st.write(f"**Enlace:** {chosen_ad.link_url or 'N/D'}")
        if chosen_ad.snapshot_url:
            st.link_button("Ver snapshot en Meta Ad Library", chosen_ad.snapshot_url)
        st.write("**Texto del anuncio:**")
        st.caption(chosen_ad.ad_text or "(sin texto)")
