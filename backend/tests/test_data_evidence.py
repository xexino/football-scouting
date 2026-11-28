"""Data-protection guard for committed research evidence (docs/data/evidence).

Evidence may describe what providers return (field names, counts, fill rates) but must never
contain raw player records or special-category personal data (ethnicity, religion, health)."""
import json
from pathlib import Path

EVIDENCE = Path(__file__).resolve().parents[2] / "docs" / "data" / "evidence"
SPECIAL_CATEGORY = {"strethnicity", "strreligion", "ethnicity", "religion"}
RAW_PERSON_KEYS = {"strplayer", "dateborn", "player_name", "datebirth", "dob"}


def _walk(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k, v, f"{path}/{k}"
            yield from _walk(v, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")


def test_evidence_contains_no_personal_records():
    problems = []
    for f in sorted(EVIDENCE.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        for key, value, where in _walk(data):
            k = key.lower()
            if k in SPECIAL_CATEGORY and value not in (None, "", [], {}):
                problems.append(f"{f.name}{where}: special-category value")
            if k in RAW_PERSON_KEYS and isinstance(value, str) and value:
                problems.append(f"{f.name}{where}: raw personal record")
    assert not problems, problems[:10]
