import json
import os
import functools
import re
import difflib
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.postgres import Dashboard, Workbook, DatasourceModel
from app.agents.workflows import stream_agent_workflow
from app.agents.classification import AreaDescriptionAgent
from app.services.ontology.ontology_service import enrich_with_ontology_inventory
from app.services.rationalization.scoring import (
    compute_ontology_score,
    compute_composite_score,
    compute_data_source_score,
    compute_semantic_model_score,
    compute_dax_structural_score,
    compute_visual_score,
    compute_filter_score,
    get_kpi_set,
)
def get_user_group_mapping():
    import pandas as pd
    mapping = {}
    excel_path = os.path.join(os.path.dirname(__file__), "../../../usergroup.xlsx")
    if os.path.exists(excel_path):
        try:
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
            pass
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
                sim = difflib.SequenceMatcher(None, k1.lower(), k2.lower()).ratio()
                candidate_pairs.append((score, sim, idx1, idx2))
                
    # Bipartite matching
    candidate_pairs.sort(key=lambda x: (x[0], x[1]), reverse=True)
    matched1 = set()
    matched2 = set()
    match_score_sum = 0.0
    for score, sim, idx1, idx2 in candidate_pairs:
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
router = APIRouter()
@router.get("/analyze/stream")
async def analyze_stream(
    request: Request,
    dashboard_name: str,
    worksheets: str = "",
    datasources: str = "",
    calc_fields_count: int = 0,
):
    """
    SSE streaming endpoint. Yields each agent step as it completes.
    Frontend subscribes with EventSource API.
    """
    ws_list = [w for w in worksheets.split("|||") if w]
    ds_list = [d for d in datasources.split("|||") if d]
    async def event_generator():
        try:
            for event in stream_agent_workflow(
                dashboard_name=dashboard_name,
                worksheets=ws_list,
                datasources=ds_list,
                calc_fields_count=calc_fields_count
            ):
                if await request.is_disconnected():
                    break
                payload = json.dumps({"event": event["event"], "data": event["data"]})
                yield f"data: {payload}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'event': 'error', 'data': str(e)})}\n\n"
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )
@router.get("/analyze/area-description")
def get_area_description(area_name: str, dashboards: str = "", db: Session = Depends(get_db)):
    dashboard_list = [d for d in dashboards.split("|||") if d]
    
    dashboard_metadata = []
    for d_name in dashboard_list:
        db_d = db.query(Dashboard).filter(Dashboard.name == d_name).first()
        if db_d:
            kpis = []
            if db_d.ai_summary and db_d.ai_summary.startswith("{"):
                try:
                    import json
                    data = json.loads(db_d.ai_summary)
                    kpis = data.get("kpis", [])
                except:
                    pass
            tables = []
            if db_d.workbook:
                for ds in db_d.workbook.datasources:
                    for t in ds.tables:
                        tables.append(t.business_name or t.name)
            
            mapping = get_user_group_mapping()
            db_name_lower = db_d.name.strip().lower()
            wb_base_name = db_d.workbook.source_file.replace('.twbx', '').replace('.twb', '').strip().lower() if getattr(db_d, "workbook", None) else db_name_lower
            excel_groups = mapping.get(wb_base_name) or mapping.get(db_name_lower)
            if not excel_groups:
                import re, difflib
                def normalize(s): return re.sub(r'[^a-z0-9]', '', s.lower())
                norm_db = normalize(db_name_lower)
                norm_wb = normalize(wb_base_name)
                for key, val in mapping.items():
                    norm_key = normalize(key)
                    if not norm_key: continue
                    ratio_db = difflib.SequenceMatcher(None, norm_db, norm_key).ratio() if norm_db else 0
                    ratio_wb = difflib.SequenceMatcher(None, norm_wb, norm_key).ratio() if norm_wb else 0
                    if (norm_db and (norm_db == norm_key or ratio_db > 0.85)) or \
                       (norm_wb and (norm_wb == norm_key or ratio_wb > 0.85)):
                        excel_groups = val
                        break
            user_groups = excel_groups["groups"] if excel_groups else (db_d.user_groups or [])
            
            dashboard_metadata.append({
                "name": db_d.name,
                "user_groups": user_groups,
                "kpis": [k.get("name") if isinstance(k, dict) else k for k in kpis],
                "tables": list(set(tables))
            })
        else:
            dashboard_metadata.append({"name": d_name})
    agent = AreaDescriptionAgent()
    result = agent.generate(area_name, dashboard_metadata)
    return {"description": result.description}
@router.get("/workbook-summary")
def get_workbook_summary(workbook_name: str, db: Session = Depends(get_db)):
    """
    Returns AI-generated summaries for each dashboard in the workbook.
    Used by InventoryView to show the Gen AI description.
    """
    workbook = db.query(Workbook).filter(Workbook.name == workbook_name).first()
    if not workbook:
        # Try partial match (in case of path prefix)
        workbook = db.query(Workbook).filter(
            Workbook.name.like(f"%{workbook_name}%")
        ).first()
    if not workbook:
        return {"workbook_summary": None, "dashboards": []}
    dashboard_summaries = []
    for d in workbook.dashboards:
        summary_text = d.ai_summary
        kpis_text = ""
        if summary_text and summary_text.startswith("{"):
            try:
                import json
                data = json.loads(summary_text)
                summary_text = data.get("summary", d.ai_summary)
                kpis_text = data.get("kpis", "")
            except:
                pass
        
        mapping = get_user_group_mapping()
        db_name_lower = d.name.strip().lower()
        wb_base_name = d.workbook.source_file.replace('.twbx', '').replace('.twb', '').strip().lower() if getattr(d, "workbook", None) else db_name_lower
        excel_data = mapping.get(wb_base_name) or mapping.get(db_name_lower)
        if not excel_data:
            import re, difflib
            def normalize(s): return re.sub(r'[^a-z0-9]', '', s.lower())
            norm_db = normalize(db_name_lower)
            norm_wb = normalize(wb_base_name)
            for key, val in mapping.items():
                norm_key = normalize(key)
                if not norm_key: continue
                ratio_db = difflib.SequenceMatcher(None, norm_db, norm_key).ratio() if norm_db else 0
                ratio_wb = difflib.SequenceMatcher(None, norm_wb, norm_key).ratio() if norm_wb else 0
                if (norm_db and (norm_db == norm_key or ratio_db > 0.85)) or \
                   (norm_wb and (norm_wb == norm_key or ratio_wb > 0.85)):
                    excel_data = val
                    break
        if not excel_data:
            excel_data = {}
        excel_groups = excel_data.get("groups") if isinstance(excel_data, dict) else None
        user_groups = excel_groups if excel_groups else getattr(d, "user_groups", [])
        days_ago_excel = excel_data.get("days_ago") if isinstance(excel_data, dict) else None
        dashboard_summaries.append({
            "name": d.name,
            "domain": d.domain_classification,
            "line_of_business": getattr(d, "line_of_business", None),
            "user_groups": user_groups,
            "days_ago": days_ago_excel,
            "complexity": d.complexity_score,
            "summary": summary_text,
            "kpis": kpis_text,
            "is_real_ai": bool(d.is_real_ai)
        })
    # Re-order dashboard_summaries to put representative dashboards first
    priority_ds = []
    standard_ds = []
    helper_ds = []
    
    helper_keywords = ("info", "information", "intro", "introduction", "cover", "readme", "legal", "tooltip", "q&a", "qa", "filter", "template")
    
    for ds in dashboard_summaries:
        name_lower = ds["name"].lower()
        summary_lower = (ds["summary"] or "").lower()
        
        is_helper = any(kw in name_lower for kw in helper_keywords) or "static content display" in summary_lower
        
        if is_helper:
            helper_ds.append(ds)
        else:
            has_kpis = False
            kpis_val = ds.get("kpis")
            if kpis_val:
                if isinstance(kpis_val, list) and len(kpis_val) > 0:
                    has_kpis = True
                elif isinstance(kpis_val, str) and kpis_val.strip() and kpis_val.strip() != "[]":
                    has_kpis = True
            
            if has_kpis:
                priority_ds.append(ds)
            else:
                standard_ds.append(ds)
                
    dashboard_summaries = priority_ds + standard_ds + helper_ds

    # Find first summary for overall
    overall_summary = None
    overall_domain = None
    overall_lob = None
    overall_user_groups = []
    overall_days_ago = None
    
    for ds in dashboard_summaries:
        if ds["summary"]:
            overall_summary = ds["summary"]
            overall_domain = ds["domain"]
            overall_lob = ds["line_of_business"]
            overall_user_groups = ds["user_groups"]
            overall_days_ago = ds["days_ago"]
            break
    return {
        "workbook_summary": overall_summary,
        "workbook_domain": overall_domain,
        "line_of_business": overall_lob,
        "user_groups": overall_user_groups,
        "days_ago": overall_days_ago,
        "dashboards": dashboard_summaries
    }
def calculate_kpi_overlap(d1, d2):
    kpis1 = d1["kpis"]
    kpis2 = d2["kpis"]
    if not kpis1 or not kpis2:
        return 0.0
        
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
                sim = difflib.SequenceMatcher(None, k1.lower(), k2.lower()).ratio()
                candidate_pairs.append((score, sim, idx1, idx2))
                
    candidate_pairs.sort(key=lambda x: (x[0], x[1]), reverse=True)
    matched1 = set()
    matched2 = set()
    match_score_sum = 0.0
    for score, sim, idx1, idx2 in candidate_pairs:
        if idx1 in matched1 or idx2 in matched2:
            continue
        matched1.add(idx1)
        matched2.add(idx2)
        match_score_sum += score
        
    overlap = match_score_sum / min(len(kpis1), len(kpis2))
    return overlap

def get_shared_datasources(wb_id1, wb_id2, wb_ds_map):
    ds1 = wb_ds_map.get(wb_id1, [])
    ds2 = wb_ds_map.get(wb_id2, [])
    
    shared = []
    for d1 in ds1:
        keys1 = {d1["name"].strip().lower(), d1["caption"].strip().lower()} - {""}
        if not keys1:
            continue
        for d2 in ds2:
            keys2 = {d2["name"].strip().lower(), d2["caption"].strip().lower()} - {""}
            if not keys2:
                continue
            if keys1 & keys2:
                display_name = d1["caption"] if d1["caption"] else d1["name"]
                shared.append(display_name)
                break
    return list(set(shared))

@router.get("/recommendations")
def get_recommendations(db: Session = Depends(get_db)):
    dashboards = db.query(Dashboard).all()
    workbooks = db.query(Workbook).all()
    datasources = db.query(DatasourceModel).all()
    
    wb_map = {w.id: w.source_file for w in workbooks}
    dash_wb_map = {d.id: d.workbook_id for d in dashboards}
    
    wb_ds_map = {}
    for ds in datasources:
        wb_id = ds.workbook_id
        if wb_id not in wb_ds_map:
            wb_ds_map[wb_id] = []
        wb_ds_map[wb_id].append({
            "name": ds.name or "",
            "caption": ds.caption or ""
        })
        
    mapping = get_user_group_mapping()
    dashboards_data = []
    
    def get_base_metric(kpi_name):
        cleaned = re.sub(r"\b(by|per)\b.*$", "", kpi_name, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\blevel\b", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\baging\b", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip().lower()
    # 1. Parse and collect metadata for each dashboard
    for d in dashboards:
        wb_id = dash_wb_map.get(d.id)
        wb_file = wb_map.get(wb_id, "unknown.twb")
        
        db_name_lower = d.name.strip().lower()
        wb_base_name = wb_file.replace('.twbx', '').replace('.twb', '').strip().lower()
        excel_data = mapping.get(wb_base_name) or mapping.get(db_name_lower)
        if not excel_data:
            import re, difflib
            def normalize(s): return re.sub(r'[^a-z0-9]', '', s.lower())
            norm_db = normalize(db_name_lower)
            norm_wb = normalize(wb_base_name)
            for key, val in mapping.items():
                norm_key = normalize(key)
                if not norm_key: continue
                ratio_db = difflib.SequenceMatcher(None, norm_db, norm_key).ratio() if norm_db else 0
                ratio_wb = difflib.SequenceMatcher(None, norm_wb, norm_key).ratio() if norm_wb else 0
                if (norm_db and (norm_db == norm_key or ratio_db > 0.85)) or \
                   (norm_wb and (norm_wb == norm_key or ratio_wb > 0.85)):
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
        if d.ai_summary:
            try:
                data = json.loads(d.ai_summary)
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
        if not tables and d.raw_metadata:
            try:
                if isinstance(d.raw_metadata, dict):
                    tables = d.raw_metadata.get("tables", [])
                elif isinstance(d.raw_metadata, str):
                    tables = json.loads(d.raw_metadata).get("tables", [])
            except:
                pass
        worksheets_config = []
        for ws in d.worksheets:
            rows_list = ws.rows if isinstance(ws.rows, list) else []
            cols_list = ws.columns if isinstance(ws.columns, list) else []
            worksheets_config.append({
                "name": ws.name,
                "rows": rows_list,
                "columns": cols_list,
                "mark_type": ws.mark_type
            })
        
        summary_text = d.ai_summary or ""
        if summary_text and summary_text.startswith("{"):
            try:
                import json
                data = json.loads(summary_text)
                summary_text = data.get("summary", d.ai_summary)
            except:
                pass
                
        dashboards_data.append({
            "id": d.id,
            "name": d.name,
            "workbook_name": wb_file,
            "workbook_id": wb_id,
            "user_groups": user_groups,
            "days_ago": days_ago,
            "kpis": kpis,
            "kpi_defs": kpi_defs,
            "tables": list(set(tables)),
            "worksheets_config": worksheets_config,
            "summary": summary_text
        })
    # Standardize all KPIs across all dashboards using memory mock clustering
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
    # 2. Pairwise duplicate check (structurally identical dashboards)
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
            # Score-based greedy bipartite matching for exact worksheets
            candidate_pairs = []
            for idx1, ws1 in enumerate(ws_list1):
                for idx2, ws2 in enumerate(ws_list2):
                    score, is_exact, _ = compare_worksheets(ws1, ws2)
                    if score > 0.0 and is_exact:
                        candidate_pairs.append((score, idx1, idx2))
            
            candidate_pairs.sort(key=lambda x: x[0], reverse=True)
            exact_matches = 0
            matched_indices1 = set()
            matched_indices2 = set()
            for score, idx1, idx2 in candidate_pairs:
                if idx1 in matched_indices1 or idx2 in matched_indices2:
                    continue
                matched_indices1.add(idx1)
                matched_indices2.add(idx2)
                exact_matches += 1
                
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
                    overlap_pct = 100
                    d1["duplicate_overlap_pct"] = overlap_pct
                    if d1["days_ago"] == d2["days_ago"]:
                        d1["duplicate_reason"] = f"100% overlap with '{d2['name']}' (structurally identical) but has a higher ID as a tiebreaker."
                    else:
                        d1["duplicate_reason"] = f"100% overlap with '{d2['name']}' (structurally identical) but less active ({d1['days_ago']} days ago vs {d2['days_ago']} days ago)."

    # 3. Merge Candidate Check (based on datasource, user group, KPI overlap > 60%)
    for i, d1 in enumerate(dashboards_data):
        if d1["is_duplicate"]:
            continue
        for j, d2 in enumerate(dashboards_data):
            if i == j:
                continue
            if d2["is_duplicate"]:
                continue
                
            # A. Datasource match
            shared_ds = get_shared_datasources(d1["workbook_id"], d2["workbook_id"], wb_ds_map)
            if not shared_ds:
                continue
                
            # B. User group match
            shared_groups = {g.strip().lower() for g in d1["user_groups"]} & {g.strip().lower() for g in d2["user_groups"]}
            if not shared_groups:
                continue
                
            # C. KPI / ontology overlap
            kpi_overlap = calculate_kpi_overlap(d1, d2)
            ontology_overlap = 0.0
            ontology_overlap_kpis: list[str] = []
            try:
                set_a = get_kpi_set(d1["id"], db)
                set_b = get_kpi_set(d2["id"], db)
                if set_a or set_b:
                    ontology_overlap = compute_ontology_score(d1["id"], d2["id"], db)
                    ontology_overlap_kpis = sorted(set_a & set_b)
                    kpi_overlap = max(kpi_overlap, ontology_overlap)
            except Exception:
                pass

            if kpi_overlap > 0.60:
                d1["merge_candidates"].append({
                    "name": d2["name"],
                    "overlap_pct": int(kpi_overlap * 100),
                    "ontology_overlap_pct": int(ontology_overlap * 100),
                    "ontology_overlap_kpis": ontology_overlap_kpis,
                    "shared_datasources": shared_ds,
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
        ontology_inventory = enrich_with_ontology_inventory(db_id, db)
        
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
                "kpis": d["kpis"],
                "tables": tables,
                "uniqueness": discard_uniqueness,
                "reasons": discard_reasons,
                "summary": d.get("summary", ""),
                "ontology_inventory": ontology_inventory,
            })
            continue
            
        # Check Merge
        if d["merge_candidates"]:
            best_cand = max(d["merge_candidates"], key=lambda x: x["overlap_pct"])
            
            # Find common KPIs
            other_db = next((o for o in dashboards_data if o["name"] == best_cand["name"]), None)
            common_kpis = []
            ontology_overlap_kpis: list[str] = []
            if other_db:
                common_kpis = list(d["canonical_kpis"] & other_db["canonical_kpis"])
                if not common_kpis:
                    common_kpis = list(d["base_metrics"] & other_db["base_metrics"])
                try:
                    set_a = get_kpi_set(d["id"], db)
                    set_b = get_kpi_set(other_db["id"], db)
                    ontology_overlap_kpis = sorted(set_a & set_b)
                    if ontology_overlap_kpis:
                        common_kpis = ontology_overlap_kpis
                except Exception:
                    pass
            
            common_tables = best_cand["shared_datasources"]
            merge_reasons = []
            merge_reasons.append(f"High KPI overlap of {best_cand['overlap_pct']}% with '{best_cand['name']}' (> 60%).")
            merge_reasons.append(f"Shares datasource: {', '.join(best_cand['shared_datasources'])}")
            if user_groups:
                merge_reasons.append(f"Target audience: {', '.join(user_groups)}")
            if best_cand["user_groups"]:
                merge_reasons.append(f"Overlap dashboard audience: {', '.join(best_cand['user_groups'])}")
                
            kpi_table_overlap = calculate_kpi_table_overlap(d, other_db) if other_db else 0.0
            if other_db and ontology_inventory:
                shared_ds = get_shared_datasources(d["workbook_id"], other_db["workbook_id"], wb_ds_map)
                ds_a = len(wb_ds_map.get(d["workbook_id"], []))
                ds_b = len(wb_ds_map.get(other_db["workbook_id"], []))
                layers = {
                    "data_source": compute_data_source_score(shared_ds, ds_a, ds_b),
                    "semantic_model": compute_semantic_model_score(set(d["tables"]), set(other_db["tables"])),
                    "ontology_kpi": compute_ontology_score(d["id"], other_db["id"], db),
                    "dax_structural": compute_dax_structural_score(calculate_kpi_overlap(d, other_db)),
                    "visual": compute_visual_score(d["worksheets_config"], other_db["worksheets_config"]),
                    "filter": compute_filter_score(d["worksheets_config"], other_db["worksheets_config"]),
                }
                kpi_table_overlap = compute_composite_score(layers)
            results["merge"].append({
                "id": db_id,
                "name": name,
                "workbook_name": wb_name,
                "days_ago": days_ago,
                "user_groups": user_groups,
                "kpis": d["kpis"],
                "tables": tables,
                "uniqueness": max(0.0, 1.0 - kpi_table_overlap),
                "merge_with": best_cand["name"],
                "reasons": merge_reasons,
                "common_kpis": common_kpis,
                "ontology_overlap_kpis": ontology_overlap_kpis,
                "common_tables": common_tables,
                "summary": d.get("summary", ""),
                "ontology_inventory": ontology_inventory,
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
            
        max_overlap = 0.0
        for other in dashboards_data:
            if other["id"] == d["id"]:
                continue
            overlap = calculate_kpi_table_overlap(d, other)
            if overlap > max_overlap:
                max_overlap = overlap
        ws_uniqueness = max(0.0, 1.0 - max_overlap)
        keep_reasons.append(f"High KPI/Table uniqueness of {int(ws_uniqueness*100)}%")
        results["keep"].append({
            "id": db_id,
            "name": name,
            "workbook_name": wb_name,
            "days_ago": days_ago,
            "user_groups": user_groups,
            "kpis": d["kpis"],
            "tables": tables,
            "uniqueness": ws_uniqueness,
            "reasons": keep_reasons,
            "summary": d.get("summary", ""),
            "ontology_inventory": ontology_inventory,
        })
    return results
