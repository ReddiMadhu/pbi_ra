"""Shared, cached reader for usergroup.xlsx — single source of truth."""

import os
import re
import difflib
import time
from typing import Optional

_CACHE: dict | None = None
_CACHE_MTIME: float = 0.0

EXCEL_PATH = os.path.join(os.path.dirname(__file__), "../../../usergroup.xlsx")


def _load_mapping() -> dict:
    """Parse usergroup.xlsx into {normalised_name: {days_ago, groups}}."""
    mapping: dict = {}
    if not os.path.exists(EXCEL_PATH):
        return mapping
    try:
        import pandas as pd
        df = pd.read_excel(EXCEL_PATH, header=None)
        for _, row in df.iterrows():
            dash_name = str(row.iloc[0]).strip().lower()
            try:
                days_ago = int(float(row.iloc[1]))
            except Exception:
                days_ago = None
            groups = [str(g).strip() for g in row.iloc[2:].dropna().tolist() if str(g).strip()]
            mapping[dash_name] = {"days_ago": days_ago, "groups": groups}
    except Exception:
        pass
    return mapping


def get_user_group_mapping() -> dict:
    """Return cached mapping; auto-reloads if the file changes on disk."""
    global _CACHE, _CACHE_MTIME
    try:
        mtime = os.path.getmtime(EXCEL_PATH) if os.path.exists(EXCEL_PATH) else 0.0
    except OSError:
        mtime = 0.0
    if _CACHE is None or mtime != _CACHE_MTIME:
        _CACHE = _load_mapping()
        _CACHE_MTIME = mtime
    return _CACHE


def _normalize_key(s: str) -> str:
    return re.sub(r'[^a-z0-9]', '', s.lower())


def lookup_user_group(
    dashboard_name: str,
    workbook_file: str | None = None,
) -> dict:
    """
    Fuzzy-match a dashboard/workbook name against usergroup.xlsx.
    Returns {"days_ago": int|None, "groups": list[str]} or empty dict.
    """
    mapping = get_user_group_mapping()
    db_name_lower = dashboard_name.strip().lower()
    wb_base_name = (
        workbook_file.replace('.twbx', '').replace('.twb', '').strip().lower()
        if workbook_file else db_name_lower
    )

    # Exact match
    result = mapping.get(wb_base_name) or mapping.get(db_name_lower)
    if result:
        return result

    # Fuzzy match
    norm_db = _normalize_key(db_name_lower)
    norm_wb = _normalize_key(wb_base_name)
    for key, val in mapping.items():
        norm_key = _normalize_key(key)
        if not norm_key:
            continue
        ratio_db = difflib.SequenceMatcher(None, norm_db, norm_key).ratio() if norm_db else 0
        ratio_wb = difflib.SequenceMatcher(None, norm_wb, norm_key).ratio() if norm_wb else 0
        if (norm_db and (norm_db == norm_key or ratio_db > 0.85)) or \
           (norm_wb and (norm_wb == norm_key or ratio_wb > 0.85)):
            return val

    return {}
