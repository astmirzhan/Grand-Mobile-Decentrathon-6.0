from __future__ import annotations

import html
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from locqa.models import Finding


def _finding_to_dict(f: Any) -> dict[str, Any]:
    if hasattr(f, "to_dict"):
        d = f.to_dict()
    else:
        d = asdict(f)
    d.pop("fragment", None)
    return {
        "key": d["key"],
        "issue_type": d["issue_type"],
        "severity": d.get("severity") or "medium",
        "source": d.get("source") or "",
        "target": d.get("target") or "",
        "evidence": d.get("evidence") or "",
        "suggestion": d.get("suggestion") if d.get("suggestion") is not None else "",
        "confidence": float(d.get("confidence", 1.0)),
        "reviewed_by_human": bool(d.get("reviewed_by_human", False)),
    }


def write_json_report(findings: list[Finding], out_path: str | Path) -> None:
    data = [_finding_to_dict(f) for f in findings]
    Path(out_path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_html_report(findings: list[Finding], out_path: str | Path) -> None:
    rows_html: list[str] = []
    issue_types = sorted({f.issue_type for f in findings})

    for idx, f in enumerate(findings, start=1):
        sev = html.escape(getattr(f, "severity", None) or "medium")
        itype = html.escape(f.issue_type)
        sugg = html.escape(getattr(f, "suggestion", None) or "")
        rows_html.append(
            f'<tr data-type="{itype}" data-sev="{sev}">'
            f"<td>{idx}</td>"
            f"<td><code>{html.escape(f.key)}</code></td>"
            f'<td><span class="badge type">{itype}</span></td>'
            f'<td><span class="badge sev-{sev}">{sev}</span></td>'
            f"<td>{html.escape(f.source or '')}</td>"
            f"<td>{html.escape(f.target or '')}</td>"
            f"<td>{html.escape(f.evidence or '')}</td>"
            f"<td>{sugg}</td>"
            f"<td>{float(getattr(f, 'confidence', 1.0)):.2f}</td>"
            f"<td>{'✅' if getattr(f, 'reviewed_by_human', False) else '—'}</td>"
            f"</tr>"
        )

    type_options = "\n".join(
        f'<option value="{html.escape(t)}">{html.escape(t)}</option>' for t in issue_types
    )

    doc = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>LocQA Report ({len(findings)} issues)</title>
<style>
  body {{ font-family: system-ui, -apple-system, sans-serif; margin: 20px; background: #f8fafc; color: #0f172a; }}
  h1 {{ margin-top: 0; font-size: 22px; }}
  .controls {{ display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; align-items: center; background: #fff; padding: 12px; border-radius: 8px; border: 1px solid #e2e8f0; }}
  select, input {{ padding: 6px 10px; border: 1px solid #cbd5e1; border-radius: 6px; font-size: 14px; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; font-size: 13px; }}
  th, td {{ border: 1px solid #e2e8f0; padding: 8px 10px; text-align: left; vertical-align: top; }}
  th {{ background: #f1f5f9; position: sticky; top: 0; }}
  tr:hover {{ background: #f8fafc; }}
  .badge {{ padding: 2px 6px; border-radius: 4px; font-weight: 600; font-size: 11px; }}
  .sev-high {{ background: #fee2e2; color: #991b1b; }}
  .sev-medium {{ background: #fef3c7; color: #92400e; }}
  .sev-low {{ background: #e0f2fe; color: #075985; }}
  .type {{ background: #f1f5f9; color: #334155; }}
</style>
</head>
<body>
<h1>Отчёт проверки локализации (LocQA) — всего находок: <span id="count">{len(findings)}</span></h1>
<div class="controls">
  <label>Тип ошибки:
    <select id="filterType" onchange="applyFilter()">
      <option value="">Все типы</option>
      {type_options}
    </select>
  </label>
  <label>Severity:
    <select id="filterSev" onchange="applyFilter()">
      <option value="">Все уровни</option>
      <option value="high">high</option>
      <option value="medium">medium</option>
      <option value="low">low</option>
    </select>
  </label>
  <label>Поиск:
    <input type="text" id="filterSearch" oninput="applyFilter()" placeholder="Ключ или текст...">
  </label>
</div>
<table>
  <thead>
    <tr>
      <th>#</th><th>Key</th><th>Issue Type</th><th>Severity</th>
      <th>Source (ru)</th><th>Target (kk)</th><th>Evidence</th>
      <th>Suggestion</th><th>Conf.</th><th>Reviewed</th>
    </tr>
  </thead>
  <tbody id="tbody">
    {"".join(rows_html)}
  </tbody>
</table>
<script>
function applyFilter() {{
  const t = document.getElementById('filterType').value;
  const s = document.getElementById('filterSev').value;
  const q = document.getElementById('filterSearch').value.toLowerCase();
  const rows = document.querySelectorAll('#tbody tr');
  let visible = 0;
  rows.forEach(r => {{
    const matchT = !t || r.dataset.type === t;
    const matchS = !s || r.dataset.sev === s;
    const matchQ = !q || r.innerText.toLowerCase().includes(q);
    const show = matchT && matchS && matchQ;
    r.style.display = show ? '' : 'none';
    if (show) visible++;
  }});
  document.getElementById('count').innerText = visible;
}}
</script>
</body>
</html>
"""
    Path(out_path).write_text(doc, encoding="utf-8")