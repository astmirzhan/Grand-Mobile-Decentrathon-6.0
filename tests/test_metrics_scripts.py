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
