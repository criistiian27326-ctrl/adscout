# AdScout

**AdScout** es un investigador de mercado en Python 3.11 + Streamlit diseñado para detectar productos digitales (ebooks, PDFs, cursos online, plantillas, comunidades en Whop) que se anuncian activamente en Facebook e Instagram a partir de la **Biblioteca de anuncios de Meta**.

Funciona para **cualquier país** mediante archivos YAML en `/markets/` (mercado inicial incluido: **Brasil, `pt-BR`**) y arranca con **costo cero** sin necesidad de APIs ni servicios de pago.

---

## Principios y Transparencia

- **Sin datos inventados**: Meta **no publica ventas ni gasto publicitario** de anuncios comerciales. El motor de puntuación (`0–100`, configurable en `config/scoring.yaml`) utiliza únicamente proxies observables:
  1. Días activo del anuncio (`days_active`).
  2. Cantidad de variantes del mismo anuncio (`variants_count`).
  3. Cantidad de anuncios activos de la misma página (`page_active_ads`).
  4. Enlace hacia un dominio de checkout conocido (`checkout_domain`).
  5. Coincidencia con palabras clave de producto digital (`keyword_match`).
- **Desglose siempre visible**: cada anuncio muestra cuántos puntos recibió por cada criterio y la evidencia exacta.
- **Privacidad y cumplimiento**: AdScout respeta límites de tasa (reintentos con *exponential backoff*) y sanea los registros crudos para no guardar datos personales de usuarios (PII).

---

## Instalación (Python 3.11)

```bash
# 1. Clona o entra en el directorio del proyecto
cd adscout

# 2. Crea y activa un entorno virtual con Python 3.11
python3.11 -m venv .venv
source .venv/bin/activate  # En Windows: .venv\Scripts\activate

# 3. Instala dependencias
pip install -r requirements.txt

# 4. Crea tu archivo de variables de entorno (opcional para Fase 1)
cp .env.example .env

# 5. Ejecuta la aplicación Streamlit
streamlit run app.py
```

### Arranque inmediato con costo cero (sin claves)

1. Abre la pestaña **Mercado** en Streamlit.
2. Verifica que el mercado **Brasil (`BR · pt-BR`)** y la fuente **`Importar CSV / JSON (Costo cero - Por defecto)`** estén seleccionados.
3. Selecciona `brasil_ads_sample.csv` (o `brasil_ads_apify.json` para probar una segunda corrida con deduplicación) y pulsa **Actualizar anuncios ahora**.
4. Explora **Ranking**, **Detalle de producto/página**, **Tendencias** y el botón **Exportar a CSV**.

### Ejecutar pruebas automatizadas

```bash
pytest -v
```

---

## Cómo obtener el token de Meta (API Oficial)

> **IMPORTANTE — Cobertura de la API Oficial de Meta:**
> Los **anuncios comerciales** solo están disponibles a través de la API oficial (`/ads_archive`) si fueron entregados en la **Unión Europea (UE) o Reino Unido (UK)**. Para Brasil (`BR`) u otros países fuera de UE/UK, la API oficial únicamente devuelve anuncios relacionados con temas sociales, elecciones o política. Para mercados fuera de UE/UK, utiliza `CsvImportSource` (costo cero) o `ApifySource` (fuente de pago opcional).

Pasos para obtener tu `META_ACCESS_TOKEN`:

1. **Verifica tu identidad en Facebook**:
   - Entra a [facebook.com/id](https://www.facebook.com/id) y completa la verificación de identidad y la autenticación en dos pasos (2FA). Meta exige este requisito antes de conceder acceso a la Ad Library API.
2. **Regístrate en Meta for Developers**:
   - Ingresa a [developers.facebook.com](https://developers.facebook.com/), acepta las condiciones de desarrollador y crea una aplicación (tipo *Otros / Business*).
3. **Solicita acceso a la API de la Biblioteca de anuncios**:
   - Visita [facebook.com/ads/library/api](https://www.facebook.com/ads/library/api/) y confirma tu cuenta verificada.
4. **Genera el token de acceso**:
   - En el **Explorador de la API Graph** (`developers.facebook.com/tools/explorer/`), selecciona tu aplicación y genera un token de usuario (`User Access Token`). Para evitar expiraciones cada hora, conviértelo en un *Long-Lived Token* (válido ~60 días).
5. **Configura `.env`**:
   ```env
   META_ACCESS_TOKEN=tu_token_aqui
   META_API_VERSION=v21.0
   ```
   - Si el token caduca o es inválido, AdScout detecta el **error 190** y muestra un aviso claro.
   - Si alcanzas el límite de llamadas, AdScout detecta el **error 613** y aplica reintentos automáticos con *exponential backoff*.

---

## Cómo exportar datos de la Biblioteca de anuncios web

Para investigar mercados fuera de UE/UK (como Brasil) a **costo cero**:

1. Abre [facebook.com/ads/library](https://www.facebook.com/ads/library/).
2. Selecciona el país (por ejemplo, **Brasil**), categoría **Todos los anuncios** y busca palabras clave como `ebook`, `PDF`, `planilha`, `curso online`, `whop` o dominios como `hotmart.com` / `kiwify.com.br`.
3. Recopila los anuncios en una hoja de cálculo (Google Sheets / Excel) y expórtala como **CSV** con las columnas estándar (puedes usar `sample_data/brasil_ads_sample.csv` como plantilla):
   - `ad_id`, `page_id`, `page_name`, `country`, `language`, `ad_text`, `headline`, `cta`, `link_url`, `start_date`, `end_date`, `is_active`, `platforms`, `snapshot_url`, `variants_count`.
4. También puedes importar directamente un **JSON descargado desde Apify** (ver ejemplo en `sample_data/brasil_ads_apify.json`), ya que `CsvImportSource` normaliza automáticamente campos como `adArchiveID`, `pageID`, `pageName`, `collationCount` y `snapshot`.
5. Sube el archivo en la página **Mercado** → **Subir archivo CSV o JSON** → **Actualizar anuncios ahora**.
   - Si importas varias corridas en días distintos, AdScout deduplica por `ad_id`, conserva `first_seen_at` y actualiza `last_seen_at` automáticamente.

---

## Cómo agregar un mercado nuevo

No hace falta tocar código Python. Solo crea un archivo YAML en `/markets/<codigo>.yaml`, por ejemplo `markets/mexico.yaml`:

```yaml
code: mexico
name: México
country: MX
language: es-MX

keywords:
  - ebook
  - e-book
  - PDF
  - guía completa
  - método
  - curso online
  - plantilla
  - link en bio
  - whop

checkout_domains:
  - hotmart.com
  - whop.com
  - gumroad.com
  - payhip.com
  - stan.store
  - stripe.com
```

Recarga la app en Streamlit y el nuevo país aparecerá automáticamente en el selector lateral.

---

## Cómo agregar una fuente de datos nueva (o de pago)

La arquitectura de fuentes utiliza la interfaz abstracta `AdSource` y el diccionario `SOURCE_REGISTRY`. Agregar un proveedor nuevo requiere únicamente **dos pasos**:

1. **Crea un archivo nuevo** en `adscout/sources/mi_fuente_pago.py` heredando de `AdSource`:

```python
from adscout.models.ad import Ad
from adscout.models.market import MarketConfig
from adscout.sources.base import AdSource


class MiFuentePagoSource(AdSource):
    name = "mi_fuente_pago"
    label = "Mi Proveedor (Fuente de pago opcional)"
    description = "Consulta anuncios desde mi proveedor externo."
    is_paid = True

    def search(
        self,
        market_config: MarketConfig,
        keywords: list[str],
        limit: int = 100,
    ) -> list[Ad]:
        # Implementa aquí la consulta HTTP con httpx, backoff y normalización a Ad
        return []
```

2. **Regístrala en el diccionario `SOURCE_REGISTRY`** en `adscout/sources/registry.py`:

```python
SOURCE_REGISTRY: dict[str, type[AdSource]] = {
    "csv_import": CsvImportSource,
    "meta_official_api": MetaOfficialApiSource,
    "apify": ApifySource,
    "mi_fuente_pago": MiFuentePagoSource,
}
```

> Recuerda leer siempre tus credenciales desde `.env` (nunca en el código fuente).

---

## Módulos LLM Opcionales (Fase 3)

AdScout funciona al 100% sin claves de LLM. Si deseas enriquecer anuncios y validar nichos:

- **Gemini (`GEMINI_API_KEY`)**: usa el paquete oficial `google-genai`. Genera un JSON validado con Pydantic (`nicho`, `tipo_producto`, `promesa_principal`, `gancho`, `publico_objetivo`, `resumen_es`) y lo cachea en SQLite (`ad_analyses`) para no repetir llamadas.
- **Perplexity (`PERPLEXITY_API_KEY`)**: usa la API compatible con OpenAI (`/chat/completions`). Se ejecuta solo bajo demanda al pulsar **Validar nicho**, devolviendo tendencia, saturación, competidores y **las fuentes citadas**.
- **Tope diario de gasto**: configura `LLM_DAILY_CALL_LIMIT` en `.env` (por defecto `25` llamadas/día).

---

## Despliegue en la nube

> **Nota sobre Vercel y Streamlit:**
> Streamlit requiere un servidor Python persistente con soporte WebSocket, por lo que **no puede ejecutarse nativamente como función serverless en Vercel** (además, SQLite en disco no persiste en funciones serverless).

Opciones recomendadas para desplegar AdScout con costo cero o mínimo:

1. **Streamlit Community Cloud (Gratis)**: conecta tu repositorio privado de GitHub en [share.streamlit.io](https://share.streamlit.io/), selecciona `app.py` como archivo principal y configura las variables de `.env` en *Secrets*.
2. **Render / Railway / Fly.io**: despliega `streamlit run app.py --server.port $PORT --server.address 0.0.0.0` con un disco persistente montado en `/data` para conservar la base SQLite entre reinicios.
