import hashlib
import json


def _hash_text(text: str) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()


def compute_report_fingerprints(report_data: dict) -> dict:
    ds_names = sorted(report_data.get("datasource_names") or [])
    tables = sorted(report_data.get("tables") or [])
    calc_formulas = sorted(report_data.get("calc_formulas") or [])
    ws_names = sorted(w.get("name", "") for w in report_data.get("worksheets_config") or [])

    return {
        "data_source_hash": _hash_text(json.dumps(ds_names)),
        "semantic_model_hash": _hash_text(json.dumps(tables)),
        "dax_minhash": None,
        "dax_simhash": _hash_text(json.dumps(calc_formulas)).encode()[:16],
        "visual_hash": _hash_text(json.dumps(ws_names)),
        "filter_hash": _hash_text(json.dumps(report_data.get("filter_marks") or [])),
        "ontology_kpi_hash": _hash_text(json.dumps(sorted(report_data.get("canonical_kpi_ids") or []))),
    }
