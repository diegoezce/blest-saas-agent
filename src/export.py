import csv


def export_markdown(report: dict, path: str) -> None:
    run_date = report.get("run_date", "unknown")
    total = report.get("total_companies_found", 0)
    quick_wins = report.get("quick_wins", [])
    strategic = report.get("strategic_opportunities", [])
    drafts = report.get("outreach_drafts", [])
    insights_map = {i["company_name"]: i for i in report.get("top_insights", [])}

    drafts_by_company: dict[str, list] = {}
    for d in drafts:
        drafts_by_company.setdefault(d.get("company_name", ""), []).append(d)

    lines = [
        f"# Blest Lead Report — {run_date}",
        "",
        f"**{total} empresas encontradas** · {len(quick_wins)} quick wins · {len(strategic)} estratégicas",
        "",
    ]

    sections = [("## Quick Wins ⚡", quick_wins), ("## Oportunidades Estratégicas 📈", strategic)]
    for section_title, opportunities in sections:
        if not opportunities:
            continue
        lines += [section_title, ""]
        for opp in opportunities:
            name = opp.get("company_name", "")
            score = opp.get("score", 0)
            lines.append(f"### {name}")
            lines.append(f"- **Score:** {score}/100")
            if opp.get("score_explanation"):
                lines.append(f"- **Por qué:** {opp['score_explanation']}")

            insight = insights_map.get(name, {})
            if insight.get("why_they_need_training"):
                lines.append(f"- **Necesidad de capacitación:** {insight['why_they_need_training']}")
            if insight.get("suggested_approach"):
                lines.append(f"- **Enfoque sugerido:** {insight['suggested_approach']}")
            if insight.get("conversation_starter"):
                lines.append(f"- **Apertura:** _{insight['conversation_starter']}_")

            company_drafts = drafts_by_company.get(name, [])
            if company_drafts:
                first = company_drafts[0]
                contact_parts: list[str] = []
                if first.get("contact_name"):
                    role_str = f" ({first['contact_role']})" if first.get("contact_role") else ""
                    contact_parts.append(f"{first['contact_name']}{role_str}")
                if first.get("contact_email"):
                    contact_parts.append(first["contact_email"])
                if first.get("contact_linkedin_url"):
                    contact_parts.append(first["contact_linkedin_url"])
                if contact_parts:
                    lines.append(f"- **Contacto:** {' · '.join(contact_parts)}")
                lines.append("")

                for d in company_drafts:
                    ch = (d.get("channel") or "").upper()
                    lang = (d.get("language") or "").upper()
                    icon = "📧" if d.get("channel") == "email" else "💼"
                    subj = f" — Asunto: {d['subject_line']}" if d.get("subject_line") else ""
                    lines.append(f"#### {icon} {ch} ({lang}){subj}")
                    lines.append("")
                    lines.append(d.get("body", ""))
                    lines.append("")
            else:
                lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def export_csv(report: dict, path: str) -> None:
    run_date = report.get("run_date", "unknown")
    drafts = report.get("outreach_drafts", [])

    fieldnames = [
        "run_date", "company_name", "contact_name", "contact_role",
        "contact_email", "contact_linkedin_url",
        "channel", "language", "subject_line", "body",
    ]

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for d in drafts:
            writer.writerow({
                "run_date": run_date,
                "company_name": d.get("company_name") or "",
                "contact_name": d.get("contact_name") or "",
                "contact_role": d.get("contact_role") or "",
                "contact_email": d.get("contact_email") or "",
                "contact_linkedin_url": d.get("contact_linkedin_url") or "",
                "channel": d.get("channel") or "",
                "language": d.get("language") or "",
                "subject_line": d.get("subject_line") or "",
                "body": d.get("body") or "",
            })
