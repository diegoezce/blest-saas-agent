import csv


_CHANNEL_EMOJI = {"email": "📧", "linkedin": "💼", "phone": "📞", "whatsapp": "💬"}


def export_csv(report: dict, path: str) -> None:
    drafts = report.get("outreach_drafts", [])
    run_date = report.get("run_date", "")
    fieldnames = [
        "run_date", "company_name", "contact_name", "contact_role",
        "contact_email", "contact_linkedin_url",
        "channel", "language", "subject_line", "body",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for d in drafts:
            writer.writerow({
                "run_date": run_date,
                "company_name": d.get("company_name", ""),
                "contact_name": d.get("contact_name", ""),
                "contact_role": d.get("contact_role", ""),
                "contact_email": d.get("contact_email", ""),
                "contact_linkedin_url": d.get("contact_linkedin_url", ""),
                "channel": d.get("channel", ""),
                "language": d.get("language", ""),
                "subject_line": d.get("subject_line", ""),
                "body": d.get("body", ""),
            })


def export_markdown(report: dict, path: str) -> None:
    run_date = report.get("run_date", "unknown")
    quick_wins = report.get("quick_wins", [])
    strategic = report.get("strategic_opportunities", [])
    total = report.get("total_companies_found", 0)
    drafts = report.get("outreach_drafts", [])
    follow_ups = report.get("follow_up_suggestions", [])

    drafts_by_company: dict[str, list] = {}
    for d in drafts:
        drafts_by_company.setdefault(d.get("company_name", ""), []).append(d)

    score_map: dict[str, int] = {}
    for opp in quick_wins + strategic:
        score_map[opp.get("company_name", "")] = opp.get("score", 0)

    lines: list[str] = []
    lines.append(f"# Blest Lead Report — {run_date}")
    lines.append(
        f"**{total} empresas** · {len(quick_wins)} quick wins · {len(strategic)} estratégicas"
    )
    lines.append("")

    def _write_section(title: str, opps: list) -> None:
        if not opps:
            return
        lines.append(f"## {title}")
        lines.append("")
        for opp in opps:
            name = opp.get("company_name", "")
            score = opp.get("score", 0)
            lines.append(f"### {name}")
            lines.append(f"- Score: {score}/100")

            company_drafts = drafts_by_company.get(name, [])
            if company_drafts:
                first = company_drafts[0]
                contact_parts = []
                if first.get("contact_name"):
                    role = first.get("contact_role", "")
                    label = f"{first['contact_name']} ({role})" if role else first["contact_name"]
                    contact_parts.append(label)
                if first.get("contact_email"):
                    contact_parts.append(first["contact_email"])
                if first.get("contact_linkedin_url"):
                    contact_parts.append(first["contact_linkedin_url"])
                if contact_parts:
                    lines.append(f"- Contacto: {' · '.join(contact_parts)}")

            lines.append("")

            for d in company_drafts:
                channel = d.get("channel", "").lower()
                lang = (d.get("language") or "").upper()
                emoji = _CHANNEL_EMOJI.get(channel, "✉")
                header = f"#### {emoji} {channel.upper()}"
                if lang:
                    header += f" ({lang})"
                subject = d.get("subject_line", "")
                if subject:
                    header += f" — Asunto: {subject}"
                lines.append(header)
                lines.append("")
                lines.append(d.get("body", ""))
                lines.append("")

    _write_section("Quick Wins ⚡", quick_wins)
    _write_section("Strategic 📈", strategic)

    if follow_ups:
        lines.append("## Seguimiento 📋")
        lines.append("")
        for s in follow_ups:
            lines.append(f"- {s}")
        lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
