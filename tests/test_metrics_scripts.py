import csv
import json

from scripts import precision_sample


def test_sample_and_score_roundtrip(tmp_path, capsys):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"findings": [
        {"key": f"k{i}", "issue_type": "orthography" if i % 2 else "suffix_harmony",
         "severity": "medium", "source": "", "target": "", "evidence": "", "suggestion": None,
         "confidence": 0.9}
        for i in range(10)
    ]}), encoding="utf-8")
    sample = tmp_path / "sample.csv"
    precision_sample.main(["sample", "--report", str(report), "--n", "6", "--out", str(sample)])
    rows = list(csv.DictReader(open(sample, encoding="utf-8")))
    assert len(rows) == 6

    for r in rows:
        r["verdict"] = "1" if r["issue_type"] == "orthography" else "0"
    with open(sample, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=precision_sample.FIELDS)
        w.writeheader()
        w.writerows(rows)

    scores = precision_sample.main(["score", str(sample)])
    assert set(scores.values()) <= {0.0, 1.0}
    assert scores.get("orthography", 1.0) == 1.0
    assert scores.get("suffix_harmony", 0.0) == 0.0


def test_compare_baselines_table_and_filters(capsys):
    from types import SimpleNamespace

    from scripts import compare_baselines as cb

    only = cb._only(lambda ctx: [SimpleNamespace(issue_type="untranslated"),
                                 SimpleNamespace(issue_type="orthography")], {"untranslated"})
    assert [f.issue_type for f in only(None)] == ["untranslated"]
    assert "locqa, no LLM" in cb.tools()

    cb.print_table({"locqa, no LLM": {
        "recall_mean": 0.99, "recall_min": 0.97, "recall_max": 1.0, "types_reportable": 11,
        "types_found_in_test": 9, "findings_real_file": 145, "clean_strings": 203,
        "clean_findings": 2, "clean_examples": []}})
    out = capsys.readouterr().out
    assert "| locqa, no LLM | 99% (97%–100%) | 11 of 11 | 145 | 2 of 203 strings |" in out
