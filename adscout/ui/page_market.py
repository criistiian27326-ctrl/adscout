"""Página Streamlit: Mercado (selector YAML, fuente de datos y botón de actualizar)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from adscout.models.market import MarketConfig
from adscout.sources import (
    InvalidTokenError,
    RateLimitError,
    SourceConfigError,
    SourceError,
    get_source,
    list_registered_sources,
)
from adscout.ui.context import AppContext


def render_market_page(ctx: AppContext, market: MarketConfig) -> None:
    st.header(f"Mercado: {market.name} ({market.country} · {market.language})")
    st.caption(
        "Configurado dinámicamente desde `/markets/*.yaml`. "
        "Para añadir otro país, crea un nuevo archivo YAML en la carpeta `markets/` y recarga."
    )

    col_info1, col_info2 = st.columns(2)
    with col_info1:
        st.subheader("Palabras clave de producto digital")
        st.write(", ".join(f"`{kw}`" for kw in market.keywords) or "Sin keywords configuradas")
    with col_info2:
        st.subheader("Dominios de checkout conocidos")
        st.write(", ".join(f"`{dom}`" for dom in market.checkout_domains) or "Sin dominios configurados")

    st.divider()
    st.subheader("Ingestión / Actualización de anuncios")

    sources_meta = list_registered_sources()
    source_keys = [s["key"] for s in sources_meta]
    source_labels = {
        s["key"]: f"{s['label']}" + (" [PAGO OPCIONAL]" if s["is_paid"] else "")
        for s in sources_meta
    }

    default_index = source_keys.index("csv_import") if "csv_import" in source_keys else 0
    selected_source_key = st.selectbox(
        "Fuente de datos",
        options=source_keys,
        index=default_index,
        format_func=lambda key: source_labels[key],
    )

    selected_meta = next(s for s in sources_meta if s["key"] == selected_source_key)
    st.info(selected_meta["description"])

    uploaded_file = None
    selected_sample_path: Path | None = None
    filter_by_keywords = False

    if selected_source_key == "csv_import":
        sample_files = sorted(
            [
                p
                for p in ctx.settings.sample_data_dir.glob("*")
                if p.suffix.lower() in {".csv", ".json"}
            ],
            key=lambda p: (0 if p.suffix.lower() == ".csv" else 1, p.name),
        )
        import_mode = st.radio(
            "Origen del archivo",
            options=["Usar datos de ejemplo (/sample_data)", "Subir archivo CSV o JSON"],
            horizontal=True,
        )
        if import_mode == "Usar datos de ejemplo (/sample_data)":
            if sample_files:
                selected_sample_path = st.selectbox(
                    "Archivo de ejemplo",
                    options=sample_files,
                    format_func=lambda p: p.name,
                )
            else:
                st.warning("No se encontraron archivos en `/sample_data`.")
        else:
            uploaded_file = st.file_uploader(
                "Sube un CSV o JSON exportado manualmente o desde Apify",
                type=["csv", "json"],
            )
        filter_by_keywords = st.checkbox(
            "Filtrar filas importadas que coincidan con las palabras clave del mercado",
            value=False,
        )

    elif selected_source_key == "meta_official_api":
        st.warning(
            "Recordatorio de Meta: la API oficial (`/ads_archive`) solo entrega anuncios comerciales "
            "dirigidos a la Unión Europea (UE) o Reino Unido (UK). Para Brasil (BR) u otros países fuera "
            "de UE/UK, utiliza `CsvImportSource` (costo cero) o `ApifySource`."
        )
        if not ctx.settings.meta_access_token:
            st.error("`META_ACCESS_TOKEN` no está configurado en `.env`. Revisa el README para obtenerlo.")

    elif selected_source_key == "apify":
        st.warning(
            "**Fuente de pago opcional**: requiere créditos activos en Apify y configurar "
            "`APIFY_API_TOKEN` y `APIFY_ACTOR_ID` en `.env`."
        )
        if not ctx.settings.apify_api_token:
            st.error("`APIFY_API_TOKEN` no está configurado en `.env`.")

    col_kw, col_lim = st.columns([3, 1])
    with col_kw:
        keywords_input = st.text_input(
            "Palabras clave para esta corrida (separadas por coma)",
            value=", ".join(market.keywords),
        )
    with col_lim:
        limit = st.number_input("Límite máximo de anuncios", min_value=1, max_value=1000, value=100, step=10)

    run_keywords = [kw.strip() for kw in keywords_input.split(",") if kw.strip()]

    if st.button("Actualizar anuncios ahora", type="primary", width="stretch"):
        temp_path: Path | None = None
        try:
            if selected_source_key == "csv_import":
                if uploaded_file is not None:
                    suffix = Path(uploaded_file.name).suffix.lower() or ".csv"
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        tmp.write(uploaded_file.getbuffer())
                        temp_path = Path(tmp.name)
                    target_path = temp_path
                elif selected_sample_path is not None:
                    target_path = selected_sample_path
                else:
                    st.error("Selecciona un archivo de ejemplo o sube un archivo CSV/JSON.")
                    return

                source = get_source(
                    "csv_import",
                    file_path=target_path,
                    filter_by_keywords=filter_by_keywords,
                )
            elif selected_source_key == "meta_official_api":
                source = get_source(
                    "meta_official_api",
                    access_token=ctx.settings.meta_access_token,
                    api_version=ctx.settings.meta_api_version,
                    ad_active_status=ctx.settings.meta_ad_active_status,
                    ad_type=ctx.settings.meta_ad_type,
                    timeout_seconds=ctx.settings.meta_timeout_seconds,
                )
            elif selected_source_key == "apify":
                source = get_source(
                    "apify",
                    api_token=ctx.settings.apify_api_token,
                    actor_id=ctx.settings.apify_actor_id,
                    timeout_seconds=ctx.settings.apify_timeout_seconds,
                )
            else:
                source = get_source(selected_source_key)

            with st.spinner("Ejecutando corrida y deduplicando por ad_id..."):
                stats = ctx.pipeline.run(
                    source=source,
                    market=market,
                    keywords=run_keywords,
                    limit=int(limit),
                )

            st.success(
                f"Corrida completada ({stats['source_name']}): "
                f"**{stats['inserted']}** nuevos, **{stats['updated']}** actualizados "
                f"(de {stats['total_fetched']} recibidos)."
            )
        except InvalidTokenError as exc:
            st.error(f"Token inválido o expirado: {exc}")
        except RateLimitError as exc:
            st.warning(f"Límite de tasa alcanzado: {exc}")
        except (SourceConfigError, SourceError) as exc:
            st.error(f"Error en la fuente de datos: {exc}")
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink(missing_ok=True)

    st.divider()
    st.subheader("Historial reciente de corridas")
    runs = ctx.repository.list_runs(market_code=market.code, limit=20)
    if runs:
        runs_df = pd.DataFrame(runs)
        runs_df["executed_at"] = runs_df["executed_at"].astype(str)
        st.dataframe(runs_df, width="stretch", hide_index=True)
    else:
        st.caption(
            "Aún no hay corridas registradas para este mercado. "
            "Pulsa **Actualizar anuncios ahora** usando `/sample_data/brasil_ads_sample.csv` para empezar con costo cero."
        )
