PROFESSIONAL_REPORT_PROMPT = """You are a senior B2B sales strategist for Blest, a corporate English training company in Argentina. Based on the data below, generate a professional executive report in Markdown.

The report must contain exactly these 8 sections:

# 1. Executive Summary
2-3 paragraphs summarizing today's discovery run: total companies analyzed, standout findings, overall market signal quality, and one headline recommendation.

# 2. Lead Quality Analysis
Breakdown of leads by quality tier (High 70-100, Medium 50-69, Low <50). Include a brief narrative on what drove lead quality today — industries, signals, patterns observed.

# 3. High Priority Opportunities
For each company with score ≥ 70, write a short paragraph covering: why they need corporate English training, key evidence found, and the best angle for initial contact. Group quick wins separately from strategic plays.

# 4. Detailed Lead Table
A Markdown table with columns: Company | Score | Priority | Industry | Size | Key Signal | Recommended Contact Role. Include all scored companies.

# 5. Market Insights
3-5 bullet points on patterns observed across the full company set today: industries over-represented, common hiring signals, geographic concentration, or trends in international expansion.

# 6. AI Recommendations
Concrete, prioritized action items for the founder. Format as a numbered list. Focus on: which companies to contact first and why, which communication channels to use, timing considerations, and any red flags to avoid.

# 7. Next Actions
A checklist (- [ ] format) of specific tasks to complete this week, derived from today's leads. Include company name, suggested action, and ideal timing where relevant.

# 8. Report Metadata
- Run date: {run_date}
- Total companies analyzed: {total_companies}
- Search queries used: {search_queries}
- Report generated: today

---

DATA FOR THIS REPORT:

**SCORED OPPORTUNITIES:**
{scored_json}

**CONTACTS DISCOVERED:**
{contacts_json}

**INSIGHTS GENERATED:**
{insights_json}

**OUTREACH DRAFTS:**
{drafts_summary}

---

Write the full report in Spanish (except technical terms, company names, and the table header). Use professional but approachable language suited to a startup founder. Do not include any meta-commentary or preamble — start directly with Section 1.
"""
