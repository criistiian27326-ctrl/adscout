"""Página Streamlit: Detalle de producto/página, evolución, desglose y análisis LLM."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from adscout.llm import LLMConfigError, LLMDailyLimitExceededError, LLMError
from adscout.models.market import MarketConfig
from adscout.ui.context import AppContext


def render_detail_page(ctx: AppContext, market: MarketConfig) -> None:
    st.header(f"Detalle de Producto / Página — {market.name} ({market.country})")

    ranked_items = ctx.pipeline.get_ranked_ads(market=market, only_active=False)
    if not ranked_items:
        st.info("No hay anuncios cargados todavía. Importa datos en la página **Mercado**.")
        return

    # Agrupar páginas ordenadas por puntaje máximo
    pages: dict[str, dict] = {}
    for item in ranked_items:
        ad = item["ad"]
        entry = pages.setdefault(
            ad.page_id,
            {"page_name": ad.page_name, "max_score": 0.0, "items": []},
        )
        entry["items"].append(item)
        entry["max_score"] = max(entry["max_score"], item["score"].total_score)

    sorted_page_ids = sorted(pages.keys(), key=lambda pid: pages[pid]["max_score"], reverse=True)
    selected_page_id = st.selectbox(
        "Selecciona una página / anunciante",
        options=sorted_page_ids,
        format_func=lambda pid: (
            f"{pages[pid]['page_name']} ({len(pages[pid]['items'])} anuncios · "
            f"máx {pages[pid]['max_score']:.1f} pts)"
        ),
    )

    page_info = pages[selected_page_id]
    page_items = page_info["items"]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total anuncios", len(page_items))
    m2.metric("Activos", sum(1 for i in page_items if i["ad"].is_active))
    m3.metric("Puntaje máximo", f"{max(i['score'].total_score for i in page_items):.1f}")
    m4.metric("Máx. días activo", max(i["days_active"] for i in page_items))

    # Evolución temporal de la página
    st.subheader("Evolución temporal de anuncios")
    timeline_rows = []
    for item in page_items:
        ad = item["ad"]
        timeline_rows.append(
            {
                "fecha_inicio": str(ad.start_date) if ad.start_date else str(ad.first_seen_at.date()),
                "first_seen": str(ad.first_seen_at.date()),
                "last_seen": str(ad.last_seen_at.date()),
                "ad_id": ad.ad_id,
                "puntaje": item["score"].total_score,
                "variantes": ad.variants_count,
                "activo": ad.is_active,
            }
        )
    timeline_df = pd.DataFrame(timeline_rows).sort_values("fecha_inicio")
    st.bar_chart(timeline_df.set_index("ad_id")[["puntaje", "variantes"]])

    st.divider()
    st.subheader("Todos los anuncios de la página, desglose y análisis Gemini")
    st.caption(
        f"Cuota LLM hoy: **{ctx.limiter.used_today()} / {ctx.limiter.daily_limit}** llamadas usadas "
        "(los análisis de Gemini se cachean en SQLite para no repetir llamadas)."
    )

    detected_niches: list[str] = []

    for item in page_items:
        ad = item["ad"]
        score = item["score"]
        analysis = ctx.repository.get_ad_analysis(ad.ad_id)
        if analysis:
            detected_niches.append(analysis.nicho)

        with st.expander(
            f"[{score.total_score:.1f} pts] {ad.headline or ad.ad_id} · "
            f"{item['days_active']}d activo · {ad.variants_count} variantes",
            expanded=(item == page_items[0]),
        ):
            left, right = st.columns([1.4, 1])
            with left:
                st.write(f"**Texto:** {ad.ad_text or '(sin texto)'}")
                st.write(f"**CTA:** {ad.cta or 'N/D'} · **Dominio:** `{ad.link_domain or 'N/D'}`")
                st.write(
                    f"**Inicio:** {ad.start_date or 'N/D'} · **Fin:** {ad.end_date or 'Activo'} · "
                    f"**Visto:** {ad.first_seen_at.date()} → {ad.last_seen_at.date()}"
                )
                if ad.snapshot_url:
                    st.link_button("Abrir snapshot en Meta Ad Library", ad.snapshot_url)

                st.markdown("**Desglose del puntaje:**")
                bd_df = pd.DataFrame(
                    [
                        {
                            "Criterio": comp.label,
                            "Puntos": comp.points,
                            "Máx.": comp.max_points,
                            "Evidencia": comp.evidence,
                        }
                        for comp in score.components
                    ]
                )
                st.dataframe(bd_df, width="stretch", hide_index=True)

            with right:
                st.markdown("**Análisis semántico (Gemini)**")
                if analysis:
                    st.success(f"Nicho: **{analysis.nicho}** ({analysis.tipo_producto})")
                    st.write(f"- **Promesa principal:** {analysis.promesa_principal}")
                    st.write(f"- **Gancho:** {analysis.gancho}")
                    st.write(f"- **Público objetivo:** {analysis.publico_objetivo}")
                    st.write(f"- **Resumen (ES):** {analysis.resumen_es}")
                    st.caption(f"Cacheado en SQLite ({analysis.model_name or 'gemini'}).")
                else:
                    st.caption("Sin análisis Gemini guardado para este anuncio.")

                if st.button(
                    "Analizar con Gemini" if not analysis else "Re-analizar con Gemini",
                    key=f"gemini_btn_{ad.ad_id}",
                ):
                    try:
                        with st.spinner("Consultando Gemini (validación Pydantic + caché SQLite)..."):
                            res, from_cache = ctx.gemini.analyze_ad(
                                ad=ad,
                                market=market,
                                repository=ctx.repository,
                                limiter=ctx.limiter,
                                force_refresh=bool(analysis),
                            )
                        msg = "Recuperado de caché SQLite." if from_cache else "Análisis generado y guardado en SQLite."
                        st.success(f"{msg} Nicho: {res.nicho}")
                        st.rerun()
                    except (LLMConfigError, LLMDailyLimitExceededError, LLMError) as exc:
                        st.error(str(exc))

    # Sección Perplexity bajo demanda: "Validar nicho"
    st.divider()
    st.subheader("Validación externa de nicho bajo demanda (Perplexity)")
    default_niche = detected_niches[0] if detected_niches else page_items[0]["nicho"].replace("Sin analizar", "").strip(" ()")
    niche_to_validate = st.text_input(
        "Nicho a validar",
        value=default_niche or page_info["page_name"],
        key=f"niche_input_{selected_page_id}",
    )

    if st.button("Validar nicho", type="primary", key=f"pplx_btn_{selected_page_id}"):
        try:
            with st.spinner("Consultando tendencia, saturación y competidores en Perplexity..."):
                validation = ctx.perplexity.validate_niche(
                    nicho=niche_to_validate,
                    market=market,
                    repository=ctx.repository,
                    limiter=ctx.limiter,
                )
            st.success("Validación de nicho completada y guardada.")
            _render_validation_card(validation)
        except (LLMConfigError, LLMDailyLimitExceededError, LLMError) as exc:
            st.error(str(exc))
    else:
        existing_val = ctx.repository.get_latest_niche_validation(niche_to_validate, market.country)
        if existing_val:
            st.caption("Última validación guardada para este nicho:")
            _render_validation_card(existing_val)


def _render_validation_card(validation) -> None:
    st.markdown(f"#### Nicho: {validation.nicho} ({validation.country})")
    st.write(f"**Tendencia:** {validation.tendencia}")
    st.write(f"**Saturación:** {validation.saturacion}")
    if validation.competidores:
        st.write("**Competidores / Referentes:** " + ", ".join(validation.competidores))
    st.write(f"**Resumen ejecutivo:** {validation.resumen_ejecutivo}")
    st.markdown("**Fuentes citadas:**")
    if validation.sources:
        for idx, url in enumerate(validation.sources, start=1):
            st.markdown(f"{idx}. [{url}]({url})")
    else:
        st.caption("La respuesta no incluyó URLs de fuentes externas.")
