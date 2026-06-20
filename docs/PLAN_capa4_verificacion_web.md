# Plan — Capa 4: Confirmación de email por búsqueda web (Tavily)

> Estado: **propuesto, sin implementar.** Continuar en Claude Code desktop sobre la rama
> `claude/process-flow-mapping-p3vkfr`.

## Objetivo

Agregar una **capa más** a la verificación de emails que **replica la búsqueda manual en Google**
("email de [empresa/persona]" → dato oficial publicado). Reusa la infraestructura existente de
Tavily (`src/tools/search.py`), **sin contratar ningún vendor nuevo**.

## Cuándo corre

**Solo en casos dudosos** (decisión del usuario): se activa después de la Capa 3 (Hunter)
únicamente cuando el email NO quedó `verified` — es decir `probable` / `pattern_unverified` /
`catch_all` / `not_found`. Son justo los que hoy rebotan.

## Mecánica (réplica del test manual)

1. **Queries dirigidas** (reusan nombre + empresa + dominio + rol):
   - `"{nombre} {apellido}" "{empresa}" email`
   - `"{nombre} {apellido}" {dominio} correo`
   - `"{empresa}" {rol} contacto email`  (nivel persona)
   - `"{empresa}" contacto email`        (nivel empresa, fallback)
2. **Buscar con `search()` (Tavily)** — 2–3 queries, con el rate-limit ya existente.
3. **Extraer emails** por regex del `content`/`title` de los resultados.
   (Opcional v1.1: fetchear el mejor `url` con el `scraper` existente para una pasada más profunda.)
4. **Filtrar y puntuar** reusando lo que ya hay:
   - Priorizar emails en el **dominio de la empresa**; rechazar `_BLOCKED_HOSTS`, proveedores
     gratuitos y los `bad_emails` del blocklist.
   - **Match por nombre** (first/last en la parte local) → confianza alta.
   - Si un email hallado **coincide con la conjetura `probable` de la Capa 2** → **consenso de 2 fuentes**.

## Política de decisión (D7-bis)

| Hallazgo en la web | Resultado |
|---|---|
| Email oficial que matchea el nombre | `verified` · source `web_search` (reemplaza la conjetura propensa a rebote) |
| Email que **confirma** el `probable` de la Capa 2 | sube `probable` → `verified` (consenso) |
| Solo inbox genérico publicado (`info@`, `contacto@`) | `verified` · `web_search_generic` |
| Nada útil | queda como estaba (`probable`/`not_found`) — sin regresión |

## Punto de inserción

`src/enrichment/pipeline.py`: después de la Capa 3 (Hunter, ~línea 304) y **antes** del fallback
genérico, gateado por `if result.email_status != "verified"`. Un email nominal hallado en la web
tiene prioridad sobre el genérico; el genérico queda debajo como red de seguridad.

## Archivos a tocar

- **Nuevo** `src/enrichment/web_email_finder.py` — construir queries + extraer + puntuar
  (espejo de `domain_resolver.py`; reusa `search`, `_BLOCKED_HOSTS`, `GENERIC_PREFIXES`,
  `_split_name`, `bad_emails`).
- **Editar** `src/enrichment/pipeline.py` — el hook de la Capa 4.
- Nuevos valores de `email_source`: `web_search`, `web_search_generic`.
- **Tests** en `tests/` — armado de queries, extracción de email de snippets, match por nombre,
  upgrade por consenso.
- **Docs** — `CLAUDE.md` (nueva Capa 4) + `docs/FLUJO_DEL_PROCESO.md` (nueva D7-bis + nodo en el diagrama).

## Flags / config

- `ENRICH_WEB_SEARCH` (on/off) — apagable, bajo riesgo.
- Opción a decidir: `ENRICH_WEB_SEARCH_SMTP_CONFIRM` — pasar el email nominal hallado por el
  verificador de la Capa 2 antes de promover a `verified` (máxima certeza vs. costo de créditos).

## Caveats

- Un email de la web es "oficial/publicado" pero no pasó SMTP → mitigado por doble filtro
  (dominio + nombre) y consenso; o por el flag de SMTP-confirm.
- Snippets ruidosos → preferir match por dominio + nombre.
- Costo Tavily acotado porque solo corre en casos dudosos.

## Investigación (jun 2026)

Patrón estándar "encontrar email vía Google" = SERP + extracción de snippets (SerpApi, HasData,
Bright Data). No hace falta SERP API dedicada: **Tavily ya integrado cumple ese rol**.
- https://serpapi.com/blog/cold-email-marketing-with-open-source-email-extractor/
- https://github.com/HasData/extract-emails-from-google-search
- https://www.scrapingdog.com/blog/best-serp-apis/

## Decisión: confirmación SMTP en v1

**Resolución: `ENRICH_WEB_SEARCH_SMTP_CONFIRM = false` (desactivado)**

**Razonamiento:**
- Un email publicado en el sitio oficial (LinkedIn, About Us, footer) es intrínsecamente más confiable que una conjetura `probable`.
- Pasar cada email web hallado por SMTP verification quemaría créditos para todos los casos, no solo los problemáticos.
- La v1 enfatiza **precisión sin overhead de costo**; si la métrica de rebotes post-web-search sube más de lo esperado en producción, iteramos en v1.1 agregando la confirmación.
- El doble filtro (dominio válido + match de nombre) ya proporciona confianza razonable sin SMTP.
