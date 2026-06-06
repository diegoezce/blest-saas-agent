# Blest Lead Discovery Agent

Agente de descubrimiento de leads B2B para Blest, empresa de capacitación en inglés corporativo en Argentina. Corre diariamente, busca empresas que necesiten entrenamiento en inglés, las puntúa, encuentra contactos clave y genera borradores de outreach listos para usar.

---

## Stack

- **Python 3.11+**
- **LangGraph** — orquestación del workflow
- **Anthropic Claude** — modelos de lenguaje (Haiku para volumen, Sonnet para razonamiento)
- **Tavily** — búsqueda web de leads
- **PostgreSQL** — base de datos vía SQLAlchemy
- **APScheduler** — ejecución diaria automática
- **Flask** — web UI para ver reportes

---

## Quickstart local

```bash
# 1. Levantar la base de datos
docker compose up -d

# 2. Configurar variables de entorno
cp .env.example .env
# Editar .env con tus API keys

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Crear tablas en la DB
python run.py --setup

# 5. Correr el agente una vez
python run.py

# 6. Ver el reporte en terminal
python run.py --report

# 7. Iniciar la web UI (con scheduler incluido)
python run.py --web
# Abrir http://localhost:8080
```

---

## Web UI

La web UI muestra todos los runs históricos con sus reportes: empresas encontradas, puntajes, insights por empresa y borradores de outreach.

```bash
python run.py --web
```

- **Usuario:** `blest`
- **Password:** el valor de `WEB_PASSWORD` (default: `blest2024`)
- **Run Now:** botón en la página principal para disparar el agente manualmente (requiere `TRIGGER_PASSWORD`)

---

## Deploy en Railway

1. Conectar el repositorio en [railway.app](https://railway.app)
2. Agregar una base de datos PostgreSQL al proyecto
3. Configurar las variables de entorno (ver sección siguiente)
4. El servicio arranca con `python run.py --web` y corre el scheduler internamente

Para exponer la UI públicamente: **Settings → Public Networking → Generate Domain**.

---

## Variables de entorno

### Requeridas

| Variable | Descripción |
|---|---|
| `ANTHROPIC_API_KEY` | API key de Anthropic |
| `TAVILY_API_KEY` | API key de Tavily (búsqueda web) |
| `DATABASE_URL` | URL de conexión PostgreSQL |

### Web UI

| Variable | Default | Descripción |
|---|---|---|
| `WEB_PASSWORD` | `blest2024` | Password para acceder a la web UI (usuario siempre: `blest`) |
| `TRIGGER_PASSWORD` | `blest2024` | Password para el botón "Run Now" |

### Scheduler

| Variable | Default | Descripción |
|---|---|---|
| `SCHEDULE_TIME` | `08:00` | Hora de ejecución diaria en formato `HH:MM` |
| `SCHEDULE_DAYS` | `mon-thu` | Días de ejecución. Ejemplos: `mon-fri`, `mon,wed,fri`, `mon-thu` |
| `SCHEDULER_TIMEZONE` | `America/Argentina/Buenos_Aires` | Timezone para el scheduler |

### Modelos

| Variable | Default | Descripción |
|---|---|---|
| `FAST_MODEL` | `claude-haiku-4-5-20251001` | Modelo para discovery, scoring y contacts |
| `REASONING_MODEL` | `claude-sonnet-4-6` | Modelo para insights y outreach |

### Targeting

| Variable | Default | Descripción |
|---|---|---|
| `TARGET_CITIES` | `Buenos Aires,Córdoba,Rosario,Mendoza` | Ciudades a buscar |
| `TARGET_INDUSTRIES` | `technology,consulting,accounting,...` | Industrias objetivo |
| `MIN_EMPLOYEES` | `20` | Mínimo de empleados |
| `MAX_EMPLOYEES` | `500` | Máximo de empleados |

### Límites de procesamiento (impactan el costo)

| Variable | Default | Descripción |
|---|---|---|
| `MAX_COMPANIES_TO_SCORE` | `30` | Empresas que pasan por scoring |
| `MAX_COMPANIES_FOR_CONTACTS` | `20` | Empresas para las que se buscan contactos |
| `MAX_COMPANIES_FOR_INSIGHTS` | `10` | Empresas para las que se generan insights |
| `MAX_COMPANIES_FOR_OUTREACH` | `5` | Empresas para las que se generan borradores |

> **Costo estimado:** ~$0.10–0.15 USD por run con los valores default.
> Para reducir costos, bajar `MAX_COMPANIES_FOR_CONTACTS` tiene el mayor impacto.

---

## Comandos

```bash
python run.py                         # Correr el agente una vez
python run.py --web                   # Web UI + scheduler en background
python run.py --schedule              # Solo scheduler (sin web UI)
python run.py --report                # Ver último reporte en terminal
python run.py --report --date 2025-06-01  # Ver reporte de una fecha específica
python run.py --setup                 # Inicializar tablas de la DB y salir
```

---

## Workflow del agente

```
Discovery → Scoring → Contacts → Insights → Outreach → Report
```

1. **Discovery** — busca empresas en la web con Tavily usando queries configuradas
2. **Scoring** — puntúa cada empresa (0–100) según tamaño, exposición internacional, hiring, etc.
3. **Contacts** — encuentra decision makers (HR, L&D, founders) por empresa
4. **Insights** — genera análisis consultivo de por qué cada empresa necesita entrenamiento
5. **Outreach** — redacta emails y mensajes de LinkedIn personalizados
6. **Report** — guarda todo en la DB y muestra el dashboard
