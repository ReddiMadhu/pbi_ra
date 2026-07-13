import sqlite3
import json
import os
import re
import difflib
def get_user_group_mapping():
    mapping = {}
    excel_path = "usergroup.xlsx"
    if os.path.exists(excel_path):
        try:
            import pandas as pd
            df = pd.read_excel(excel_path, header=None)
            for _, row in df.iterrows():
                dash_name = str(row.iloc[0]).strip().lower()
                try:
                    days_ago = int(float(row.iloc[1]))
                except:
                    days_ago = None
                groups = [str(g).strip() for g in row.iloc[2:].dropna().tolist() if str(g).strip()]
                mapping[dash_name] = {
                    "days_ago": days_ago,
                    "groups": groups
                }
        except Exception as e:
            print("Excel read error:", e)
    return mapping
def clean_text(s: str) -> str:
    s = re.sub(r"\s*\(Table\s*-\s*[^\)]+\)", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*\([^\)]+\)", "", s)
    s = re.sub(r"![0-9]+", "", s)
    s = re.sub(r"\b(avg|sum|min|max|count|attr)\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"[^a-zA-Z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()
def compare_worksheets(ws1, ws2):
    name1 = clean_text(ws1["name"])
    name2 = clean_text(ws2["name"])
    w1 = set(name1.split())
    w2 = set(name2.split())
    
    # 1. Check exact name match / high similarity
    seq_ratio = difflib.SequenceMatcher(None, name1, name2).ratio()
    word_overlap = len(w1 & w2) / min(len(w1), len(w2)) if w1 and w2 else 0.0
    names_sane = (seq_ratio > 0.75 or word_overlap > 0.65 or name1 in name2 or name2 in name1)
    
    rows1 = ws1.get("rows") or []
    cols1 = ws1.get("columns") or []
    rows2 = ws2.get("rows") or []
    cols2 = ws2.get("columns") or []
    
    vars1 = set(clean_text(v) for v in (rows1 + cols1))
    vars2 = set(clean_text(v) for v in (rows2 + cols2))
    vars1 = {v for v in vars1 if v}
    vars2 = {v for v in vars2 if v}
    
    axis_sane = False
    if not vars1 or not vars2:
        axis_sane = True
    else:
        intersection = vars1 & vars2
        overlap = len(intersection) / min(len(vars1), len(vars2))
        if overlap >= 0.70:
            axis_sane = True
        else:
            fuzzy_matches = 0
            for v1 in vars1:
                for v2 in vars2:
                    if v1 in v2 or v2 in v1 or difflib.SequenceMatcher(None, v1, v2).ratio() > 0.8:
                        fuzzy_matches += 1
                        break
            fuzzy_overlap = fuzzy_matches / min(len(vars1), len(vars2))
            if fuzzy_overlap >= 0.70:
                axis_sane = True
                
    if names_sane and axis_sane:
        return 2.0 + seq_ratio, True, False # Exact/sane structural match
        
    # 2. Check granularity difference match
    grain_words = {'by', 'per', 'state', 'region', 'gender', 'category', 'zone', 'group', 'country', 'date', 'year', 'month'}
    core_w1 = w1 - grain_words
    core_w2 = w2 - grain_words
    
    if core_w1 and core_w2:
        core_overlap = len(core_w1 & core_w2) / min(len(core_w1), len(core_w2))
        if core_overlap >= 0.70:
            # Check axis variables overlap
            if not vars1 or not vars2:
                return 1.0 + seq_ratio, False, True # Grain match
            intersection = vars1 & vars2
            overlap = len(intersection) / min(len(vars1), len(vars2))
            if overlap >= 0.50:
                return 1.0 + seq_ratio, False, True # Grain match
                
    return 0.0, False, False
def calculate_kpi_table_overlap(d1, d2):
    import difflib
    # 1. KPI Overlap via Bipartite Matching
    kpis1 = d1["kpis"]
    kpis2 = d2["kpis"]
    
    candidate_pairs = []
    for idx1, k1 in enumerate(kpis1):
        def1 = d1.get("kpi_defs", {}).get(k1, "")
        base1 = d1["base_metrics_list"][idx1]
        
        for idx2, k2 in enumerate(kpis2):
            def2 = d2.get("kpi_defs", {}).get(k2, "")
            base2 = d2["base_metrics_list"][idx2]
            
            # Match rules:
            match = False
            score = 0.0
            
            if base1 == base2 and base1 != "":
                match = True
                score = 1.0
            elif d1["canonical_kpis_list"][idx1] == d2["canonical_kpis_list"][idx2] and d1["canonical_kpis_list"][idx1] != "":
                match = True
                score = 1.0
            elif def1 and def2 and difflib.SequenceMatcher(None, def1.lower(), def2.lower()).ratio() > 0.8:
                match = True
                score = 0.8
            elif difflib.SequenceMatcher(None, k1.lower(), k2.lower()).ratio() > 0.8:
                match = True
                score = 0.8
                
            if match:
                candidate_pairs.append((score, idx1, idx2))
                
    # Bipartite matching
    candidate_pairs.sort(key=lambda x: x[0], reverse=True)
    matched1 = set()
    matched2 = set()
    match_score_sum = 0.0
    for score, idx1, idx2 in candidate_pairs:
        if idx1 in matched1 or idx2 in matched2:
            continue
        matched1.add(idx1)
        matched2.add(idx2)
        match_score_sum += score
        
    kpi_sim = match_score_sum / max(1, len(kpis1)) if kpis1 else 0.0
    
    # 2. Table Overlap
    t1 = set(d1["tables"])
    t2 = set(d2["tables"])
    table_sim = len(t1 & t2) / max(1, len(t1)) if t1 else 0.0
    
    # 3. Combined similarity
    if kpis1 and t1:
        overlap = 0.7 * kpi_sim + 0.3 * table_sim
    elif kpis1:
        overlap = kpi_sim
    elif t1:
        overlap = table_sim
    else:
        overlap = 0.0
        
    return overlap
def run_recommendations_logic():
    conn = sqlite3.connect('tableau_gov.db')
    c = conn.cursor()
    c.execute("SELECT id, name, ai_summary, raw_metadata FROM dashboards")
    dash_rows = c.fetchall()
    # Get workbook source files to match workbook names
    c.execute("SELECT id, source_file FROM workbooks")
    wb_map = {row[0]: row[1] for row in c.fetchall()}
    c.execute("SELECT id, workbook_id FROM dashboards")
    dash_wb_map = {row[0]: row[1] for row in c.fetchall()}
    mapping = get_user_group_mapping()
    dashboards_data = []
    # Helper to clean base metrics for granularity matching
    def get_base_metric(kpi_name):
        cleaned = re.sub(r"\b(by|per)\b.*$", "", kpi_name, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\blevel\b", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\baging\b", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip().lower()
    # 1. Parse and collect metadata for each dashboard
    for row in dash_rows:
        db_id, name, ai_summary, raw_metadata_str = row
        wb_id = dash_wb_map.get(db_id)
        wb_file = wb_map.get(wb_id, "unknown.twb")
        
        db_name_lower = name.strip().lower()
        wb_base_name = wb_file.replace('.twbx', '').replace('.twb', '').strip().lower()
        excel_data = mapping.get(wb_base_name) or mapping.get(db_name_lower)
        if not excel_data:
            def normalize(s): return re.sub(r'[^a-z0-9]', '', s.lower())
            norm_db = normalize(db_name_lower)
            norm_wb = normalize(wb_base_name)
            for key, val in mapping.items():
                norm_key = normalize(key)
                if not norm_key: continue
                ratio_db = difflib.SequenceMatcher(None, norm_db, norm_key).ratio() if norm_db else 0
                ratio_wb = difflib.SequenceMatcher(None, norm_wb, norm_key).ratio() if norm_wb else 0
                if (norm_db and (norm_db in norm_key or norm_key in norm_db or ratio_db > 0.9)) or \
                   (norm_wb and (norm_wb in norm_key or norm_key in norm_wb or ratio_wb > 0.9)):
                    excel_data = val
                    break
        if not excel_data:
            excel_data = {}
        user_groups = excel_data.get("groups") or []
        days_ago = excel_data.get("days_ago")
        if days_ago is None:
            days_ago = 120 # moderate default
        # Parse KPIs
        kpis = []
        kpi_defs = {}
        tables = []
        if ai_summary:
            try:
                data = json.loads(ai_summary)
                kpis_raw = data.get("kpis", [])
                for k in kpis_raw:
                    if isinstance(k, dict) and k.get("name"):
                        kpis.append(k["name"])
                        kpi_defs[k["name"]] = k.get("definition", "")
                    elif isinstance(k, str):
                        kpis.append(k)
                        kpi_defs[k] = ""
                
                tables_raw = data.get("tables", [])
                for t in tables_raw:
                    if isinstance(t, dict) and t.get("name"):
                        tables.append(t["name"])
                    elif isinstance(t, str):
                        tables.append(t)
            except:
                pass
        if not tables and raw_metadata_str:
            try:
                rm = json.loads(raw_metadata_str)
                tables = rm.get("tables", [])
            except:
                pass
        # Query worksheets from db for this dashboard
        c.execute("SELECT name, rows, columns, mark_type FROM worksheets WHERE dashboard_id = ?", (db_id,))
        ws_rows = c.fetchall()
        worksheets_config = []
        for ws_row in ws_rows:
            try:
                rows_list = json.loads(ws_row[1]) if ws_row[1] else []
            except:
                rows_list = []
            try:
                cols_list = json.loads(ws_row[2]) if ws_row[2] else []
            except:
                cols_list = []
            worksheets_config.append({
                "name": ws_row[0],
                "rows": rows_list,
                "columns": cols_list,
                "mark_type": ws_row[3]
            })
        dashboards_data.append({
            "id": db_id,
            "name": name,
            "workbook_name": wb_file,
            "user_groups": user_groups,
            "days_ago": days_ago,
            "kpis": kpis,
            "kpi_defs": kpi_defs,
            "tables": list(set(tables)),
            "worksheets_config": worksheets_config
        })
    # Standardize all KPIs across all dashboards using memory mock clustering for now
    all_kpis = set()
    for d in dashboards_data:
        for k in d["kpis"]:
            all_kpis.add(k)
            
    kpi_clusters = {k: k for k in all_kpis}
    
    # Calculate canonical KPI sets
    for d in dashboards_data:
        d["canonical_kpis"] = set(kpi_clusters.get(k, k) for k in d["kpis"])
        d["base_metrics"] = set(get_base_metric(k) for k in d["canonical_kpis"])
        d["canonical_kpis_list"] = [kpi_clusters.get(k, k) for k in d["kpis"]]
        d["base_metrics_list"] = [get_base_metric(k) for k in d["canonical_kpis_list"]]
    # 2. Pairwise worksheet and duplication checks
    for d in dashboards_data:
        d["is_duplicate"] = False
        d["duplicate_target"] = None
        d["duplicate_overlap_pct"] = 0
        d["duplicate_reason"] = ""
        d["merge_candidates"] = []
    for i, d1 in enumerate(dashboards_data):
        ws_list1 = d1["worksheets_config"]
        if not ws_list1:
            continue
        for j, d2 in enumerate(dashboards_data):
            if i == j:
                continue
            ws_list2 = d2["worksheets_config"]
            if not ws_list2:
                continue
            # Score-based greedy bipartite matching
            candidate_pairs = []
            for idx1, ws1 in enumerate(ws_list1):
                for idx2, ws2 in enumerate(ws_list2):
                    score, is_exact, is_grain = compare_worksheets(ws1, ws2)
                    if score > 0.0:
                        candidate_pairs.append((score, idx1, idx2, is_exact, is_grain))
            
            # Sort descending by score
            candidate_pairs.sort(key=lambda x: x[0], reverse=True)
            
            exact_matches = 0
            grain_matches = 0
            matched_indices1 = set()
            matched_indices2 = set()
            
            for score, idx1, idx2, is_exact, is_grain in candidate_pairs:
                if idx1 in matched_indices1 or idx2 in matched_indices2:
                    continue
                matched_indices1.add(idx1)
                matched_indices2.add(idx2)
                if is_exact:
                    exact_matches += 1
                elif is_grain:
                    grain_matches += 1
            total_matches = exact_matches + grain_matches
            len1 = len(ws_list1)
            len2 = len(ws_list2)
            
            # Check if duplicate (both exact matches >= 85%)
            is_dup = (exact_matches / len1 >= 0.85) and (exact_matches / len2 >= 0.85)
            if is_dup:
                d1_days = d1["days_ago"] if d1["days_ago"] is not None else 9999
                d2_days = d2["days_ago"] if d2["days_ago"] is not None else 9999
                
                discard_d1 = False
                if d1_days > d2_days:
                    discard_d1 = True
                elif d1_days == d2_days:
                    if d1["id"] > d2["id"]:
                        discard_d1 = True
                        
                if discard_d1:
                    d1["is_duplicate"] = True
                    d1["duplicate_target"] = d2["name"]
                    overlap_pct = int((exact_matches / len1) * 100)
                    d1["duplicate_overlap_pct"] = overlap_pct
                    if d1["days_ago"] == d2["days_ago"]:
                        d1["duplicate_reason"] = f"Duplicate dashboard: structurally identical to '{d2['name']}' (worksheet overlap is {overlap_pct}%) but has a higher ID as a tiebreaker."
                    else:
                        d1["duplicate_reason"] = f"Duplicate dashboard: structurally identical to '{d2['name']}' (worksheet overlap is {overlap_pct}%) but less active ({d1['days_ago']} days ago vs {d2['days_ago']} days ago)."
            # Check if merge candidate (if not duplicate and overlap is high >= 70% of min_len)
            if not is_dup:
                min_len = min(len1, len2)
                overlap_ratio = total_matches / min_len if min_len > 0 else 0.0
                if overlap_ratio >= 0.70:
                    shared_tables = list(set(d1["tables"]) & set(d2["tables"]))
                    if shared_tables:
                        is_grain_diff = (grain_matches > 0) or (len1 != len2)
                        d1["merge_candidates"].append({
                            "name": d2["name"],
                            "overlap_pct": min(100, int(overlap_ratio * 100)),
                            "is_grain_diff": is_grain_diff,
                            "shared_tables": shared_tables,
                            "user_groups": d2["user_groups"]
                        })
    results = {
        "keep": [],
        "merge": [],
        "discard": []
    }
    # Categorize
    for d in dashboards_data:
        db_id = d["id"]
        name = d["name"]
        wb_name = d["workbook_name"]
        days_ago = d["days_ago"]
        user_groups = d["user_groups"]
        canonical_kpis = list(d["canonical_kpis"])
        tables = d["tables"]
        
        # Rules Check
        is_discard = False
        discard_reasons = []
        if days_ago > 180:
            is_discard = True
            discard_reasons.append(f"Last viewed {days_ago} days ago (> 180 days)")
        if len(user_groups) == 0:
            is_discard = True
            discard_reasons.append("Orphaned dashboard: no active user groups assigned")
        if d["is_duplicate"]:
            is_discard = True
            discard_reasons.append(d["duplicate_reason"])
        if is_discard:
            # Calculate KPI and table-based uniqueness compared to all other dashboards
            max_overlap = 0.0
            for other in dashboards_data:
                if other["id"] == d["id"]:
                    continue
                overlap = calculate_kpi_table_overlap(d, other)
                if overlap > max_overlap:
                    max_overlap = overlap
            discard_uniqueness = max(0.0, 1.0 - max_overlap)
            results["discard"].append({
                "id": db_id,
                "name": name,
                "workbook_name": wb_name,
                "days_ago": days_ago,
                "user_groups": user_groups,
                "kpis": canonical_kpis,
                "tables": tables,
                "uniqueness": discard_uniqueness,
                "reasons": discard_reasons
            })
            continue
        # Check Merge
        if d["merge_candidates"]:
            best_cand = max(d["merge_candidates"], key=lambda x: x["overlap_pct"])
            
            # Find common KPIs
            other_db = next((o for o in dashboards_data if o["name"] == best_cand["name"]), None)
            common_kpis = []
            if other_db:
                # Intersect canonical KPIs
                common_kpis = list(d["canonical_kpis"] & other_db["canonical_kpis"])
                if not common_kpis:
                    common_kpis = list(d["base_metrics"] & other_db["base_metrics"])
            
            common_tables = list(set(tables) & set(best_cand["shared_tables"]))
            merge_reasons = []
            if best_cand["is_grain_diff"]:
                merge_reasons.append(f"Redundant granularity level compared to '{best_cand['name']}': same tables but different detail levels.")
            else:
                merge_reasons.append(f"High structure overlap of {best_cand['overlap_pct']}% with '{best_cand['name']}' (> 70%).")
                
            merge_reasons.append(f"Shares database tables: {', '.join(best_cand['shared_tables'])}")
            if user_groups:
                merge_reasons.append(f"Target audience: {', '.join(user_groups)}")
            if best_cand["user_groups"]:
                merge_reasons.append(f"Overlap dashboard audience: {', '.join(best_cand['user_groups'])}")
            kpi_table_overlap = calculate_kpi_table_overlap(d, other_db) if other_db else 0.0
            results["merge"].append({
                "id": db_id,
                "name": name,
                "workbook_name": wb_name,
                "days_ago": days_ago,
                "user_groups": user_groups,
                "kpis": canonical_kpis,
                "tables": tables,
                "uniqueness": max(0.0, 1.0 - kpi_table_overlap),
                "merge_with": best_cand["name"],
                "reasons": merge_reasons,
                "common_kpis": common_kpis,
                "common_tables": common_tables
            })
            continue
        # Fallback to Keep
        keep_reasons = []
        if days_ago < 90:
            keep_reasons.append(f"Active dashboard: last accessed {days_ago} days ago (< 90 days)")
        else:
            keep_reasons.append(f"Moderate dashboard activity: last accessed {days_ago} days ago")
            
        if len(user_groups) > 0:
            keep_reasons.append(f"Target audience is active: {', '.join(user_groups)}")
            
        # Calculate KPI and table-based uniqueness compared to all other dashboards
        max_overlap = 0.0
        for other in dashboards_data:
            if other["id"] == d["id"]:
                continue
            overlap = calculate_kpi_table_overlap(d, other)
            if overlap > max_overlap:
                max_overlap = overlap
        ws_uniqueness = max(0.0, 1.0 - max_overlap)
        keep_reasons.append(f"High KPI/Table uniqueness of {int(ws_uniqueness*100)}% (> 70%)")
        results["keep"].append({
            "id": db_id,
            "name": name,
            "workbook_name": wb_name,
            "days_ago": days_ago,
            "user_groups": user_groups,
            "kpis": canonical_kpis,
            "tables": tables,
            "uniqueness": ws_uniqueness,
            "reasons": keep_reasons
        })
    print(f"Keep: {len(results['keep'])}")
    for d in results['keep']:
        print(f" - {d['name']}: {d['reasons']}")
    print(f"Merge: {len(results['merge'])}")
    for d in results['merge']:
        print(f" - {d['name']} (with {d['merge_with']}): {d['reasons']}")
    print(f"Discard: {len(results['discard'])}")
    for d in results['discard']:
        print(f" - {d['name']}: {d['reasons']}")
if __name__ == "__main__":
    run_recommendations_logic()