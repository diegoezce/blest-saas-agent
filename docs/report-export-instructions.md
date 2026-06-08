# Instrucciones: Report Recipient Info + Export (CSV + MD)

Estas instrucciones describen cómo agregar datos de destinatario a los outreach drafts
y exportar el reporte como CSV y Markdown en un agente LangGraph similar a este.

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
| `src/graph/nodes/outreach.py` | +3 líneas: agregar email, linkedin, rol al draft |
| `src/tools/db_tools.py` | +1 línea: `all_contacts` en report dict |
| `src/dashboard.py` | Reescribir sección outreach para agrupar por empresa + mostrar destinatario; `render_last_run` devuelve dict |
| `src/export.py` | Nuevo archivo: `export_markdown()` + `export_csv()` |
| `run.py` | Bloque `--report` auto-guarda CSV + MD tras renderizar |

---

## Notas

- Los runs anteriores al cambio tendrán `contact_email=None` en sus drafts (ya persistidos en JSONB).
  Los exports los muestran como celdas vacías, lo cual es correcto.
- El directorio `reports/` se crea automáticamente.
- No se requieren migraciones de base de datos.
