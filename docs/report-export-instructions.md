# Instrucciones: Fixes y Mejoras al Agente de Leads

Instrucciones para replicar los siguientes cambios en otro agente LangGraph similar:
1. Fix de FK constraint en contacts (bug crítico)
2. Datos de destinatario en outreach drafts + export CSV/MD

---

## 0. Fix: FK constraint al insertar contacts (`db_tools.py`) — VERIFICAR PRIMERO

### Síntoma
Si al correr el agente aparece este error, el bug está presente:

```
psycopg2.errors.ForeignKeyViolation: insert or update on table "contacts"
violates foreign key constraint "contacts_company_id_fkey"
DETAIL: Key (company_id)=(X) is not present in table "companies".
```

### Causa
En `persist_run_node()`, el bloque que inserta `Opportunity` tiene un `session.rollback()`
en el `except`. Ese rollback deshace **toda la sesión**, incluyendo los `flush()` de companies
que se hicieron antes. Las companies desaparecen de la DB pero el `company_id_map` sigue
teniendo sus IDs — y cuando se insertan los contacts con esos IDs inválidos, PostgreSQL
rechaza la FK.

### Cómo verificar si tu agente lo tiene
Buscá este patrón en el nodo de persistencia (suele estar en `db_tools.py` o similar):

```python
try:
    session.add(opp)
    session.flush()
except Exception:
    session.rollback()   # ← este rollback es el problema
```

### Fix: reemplazar con savepoint
Cambiar el bloque completo por:

```python
try:
    with session.begin_nested():   # savepoint — solo revierte esta oportunidad
        session.add(opp)
except Exception as e:
    logger.warning(f"Skipped opportunity for {name}: {e}")
```

`begin_nested()` crea un savepoint de PostgreSQL. Si falla esa inserción, solo se
deshace ese savepoint — las companies y el resto de la sesión quedan intactos.

---

## 1. Enriquecer drafts con datos del contacto (`outreach.py`)

En el nodo que genera los borradores de outreach, luego de asignar `contact_name`,
agregar también email, LinkedIn y rol:

```python
# Antes (solo nombre):
if primary_contact:
    d["contact_name"] = primary_contact.get("name")

# Después (nombre + datos de contacto):
if primary_contact:
    d["contact_name"]         = primary_contact.get("name")
    d["contact_email"]        = primary_contact.get("email")
    d["contact_linkedin_url"] = primary_contact.get("linkedin_url")
    d["contact_role"]         = primary_contact.get("role")
```

El `primary_contact` es el primer elemento de la lista de contactos de esa empresa
(ya disponible en el nodo de outreach como `contacts["contacts"][0]`).

---

## 2. Incluir todos los contactos en el reporte (`db_tools.py`)

En `generate_report_node()`, agregar al dict del reporte:

```python
report = {
    ...
    "outreach_drafts": state.get("outreach_drafts", []),
    "all_contacts": state.get("contacts", []),   # ← agregar esta línea
    "follow_up_suggestions": follow_ups,
}
```

Los nuevos campos en los drafts se persisten automáticamente en el JSONB `report_json`
sin cambios de esquema de base de datos.

---

## 3. Crear `src/export.py` con dos funciones

```python
def export_markdown(report: dict, path: str) -> None
def export_csv(report: dict, path: str) -> None
```

**Estructura CSV** — una fila por outreach draft:
```
run_date, company_name, contact_name, contact_role,
contact_email, contact_linkedin_url,
channel, language, subject_line, body
```

**Estructura Markdown**:
```markdown
# Blest Lead Report — YYYY-MM-DD
**N empresas** · N quick wins · N estratégicas

## Quick Wins ⚡
### Empresa X
- Score: 85/100
- Contacto: Nombre (Rol) · email@... · linkedin.com/in/...

#### 📧 EMAIL (EN) — Asunto: ...
<cuerpo del mensaje>

#### 💼 LINKEDIN (ES)
<cuerpo del mensaje>
```

Ver implementación completa en `src/export.py`.

---

## 4. Modificar dashboard para mostrar destinatario (`dashboard.py`)

En la sección de outreach drafts, agrupar por empresa y mostrar una línea "Para:" antes
de los mensajes:

```python
# Agrupar drafts por empresa
by_company: dict[str, list] = {}
for d in drafts:
    by_company.setdefault(d.get("company_name", ""), []).append(d)

for company_name, company_drafts in list(by_company.items())[:5]:
    first = company_drafts[0]
    # Construir línea de destinatario
    recipient_parts = []
    if first.get("contact_name"):
        recipient_parts.append(first["contact_name"])
    if first.get("contact_email"):
        recipient_parts.append(first["contact_email"])
    if first.get("contact_linkedin_url"):
        recipient_parts.append(first["contact_linkedin_url"])
    recipient_line = "  ·  ".join(recipient_parts) or "Destinatario desconocido"
    # ... renderizar panel con recipient_line + drafts agrupados
```

---

## 5. Auto-exportar al mostrar el reporte (`run.py`)

Modificar el bloque `--report` para que `render_last_run` devuelva el dict del reporte
y luego guardar los archivos:

```python
# En dashboard.py: hacer que render_last_run devuelva el dict
def render_last_run(target_date=None) -> dict | None:
    ...
    render_report_from_data(report_row.report_json, run)
    return report_row.report_json  # ← agregar return

# En run.py:
report_data = render_last_run(target_date=target)
if report_data:
    from src.export import export_markdown, export_csv
    run_date = report_data.get("run_date", "unknown")
    pathlib.Path("reports").mkdir(exist_ok=True)
    export_markdown(report_data, f"reports/{run_date}.md")
    export_csv(report_data, f"reports/{run_date}.csv")
    print(f"Guardado: reports/{run_date}.md + .csv")
```

---

## Archivos modificados/creados

| Archivo | Cambio |
|---|---|
| `src/tools/db_tools.py` | Fix FK: `begin_nested()` en insert de Opportunity; +1 línea `all_contacts` en report dict |
| `src/graph/nodes/outreach.py` | +3 líneas: agregar email, linkedin, rol al draft |
| `src/dashboard.py` | Reescribir sección outreach para agrupar por empresa + mostrar destinatario; `render_last_run` devuelve dict |
| `src/export.py` | Nuevo archivo: `export_markdown()` + `export_csv()` |
| `run.py` | Bloque `--report` auto-guarda CSV + MD tras renderizar |

---

## Notas

- Los runs anteriores al cambio tendrán `contact_email=None` en sus drafts (ya persistidos en JSONB).
  Los exports los muestran como celdas vacías, lo cual es correcto.
- El directorio `reports/` se crea automáticamente.
- No se requieren migraciones de base de datos.
