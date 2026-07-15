import os
import json
import functools
from fastapi import APIRouter, Query, Depends
from sqlalchemy.orm import Session
from typing import List
from app.db.session import get_db
from app.models.postgres import Dashboard
from app.services.user_groups import get_user_group_mapping, lookup_user_group
router = APIRouter()
def parse_llm_json(content: str) -> dict:
    """Helper to extract JSON from markdown code blocks and parse it."""
    try:
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.endswith("```"):
            content = content[:-3]
        return json.loads(content.strip())
    except:
        return {}
# Fix #6: Use a clearable dict cache instead of lru_cache for KPI clusters
_kpi_cluster_cache: dict[tuple, dict] = {}


def clear_kpi_cluster_cache() -> int:
    """Clear the KPI cluster cache. Returns count of cleared entries."""
    count = len(_kpi_cluster_cache)
    _kpi_cluster_cache.clear()
    return count


def get_kpi_clusters(kpi_names_tuple: tuple) -> dict:
    if len(kpi_names_tuple) <= 1:
        return {k: k for k in kpi_names_tuple}

    if kpi_names_tuple in _kpi_cluster_cache:
        return _kpi_cluster_cache[kpi_names_tuple]

    prompt = f"""
    You are a data analyst. I have a list of KPI names extracted from several dashboards.
    Group them by semantic similarity. If two KPIs mean the exact same thing (e.g., "Total Revenue" and "Revenue", or "Active Users" and "User Count"), map them to a single canonical name.
    
    CRITICAL RULE 1: Focus purely on the underlying semantic meaning. If two KPIs measure the exact same underlying business metric, you MUST combine them into a single canonical name. Ignore differences in phrasing, word order, redundant words, punctuation, abbreviations, or formatting. If the true business meaning is identical, merge them.
    CRITICAL RULE 2: Do NOT combine or group KPIs if one is a breakdown or subset of another (e.g. "Loss Ratio" vs "Loss Ratio by State"). They must remain separate.
    CRITICAL RULE 3: However, you MUST standardize the base metric name across these breakdowns! If you see "% Change - Loss Ratio by State" and "% Change in Loss Ratio", you must rename the first one to "% Change in Loss Ratio by State" so the base metric prefix matches perfectly. Likewise, if you see "Days to Settle by State" and "Days to Settle Claims by Region", you must standardize them to use the same base metric (e.g. "Days to Settle Claims by State" and "Days to Settle Claims by Region").
    
    Return ONLY a valid JSON dictionary where the keys are the EXACT original KPI names, and the values are the canonical KPI names.
    Do not add any markdown formatting or explanation. Just the raw JSON object.
    
    KPI Names:
    {json.dumps(list(kpi_names_tuple))}
    """
    
    try:
        from app.core.llm import get_llm
        llm = get_llm(temperature=0.0)
        res = llm.invoke(prompt)
        
        content = res.content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        
        mapping = json.loads(content.strip())
        result = {k: mapping.get(k, k) for k in kpi_names_tuple}
        _kpi_cluster_cache[kpi_names_tuple] = result
        return result
    except Exception as e:
        print(f"--- KPI CLUSTERING FAILED ---\n{e}")
        result = {k: k for k in kpi_names_tuple}
        _kpi_cluster_cache[kpi_names_tuple] = result
        return result
def build_graph_for_dashboards(requested_dashboards: List[str], db: Session):
    nodes = []
    links = []
    node_ids = set()
    dashboard_data_for_llm = []
    
    def add_node(node_id, group_type, label, properties=None):
        if node_id not in node_ids:
            nodes.append({
                "id": node_id,
                "group": group_type,
                "label": label,
                **(properties or {})
            })
            node_ids.add(node_id)
        else:
            if properties:
                for n in nodes:
                    if n["id"] == node_id:
                        for k, v in properties.items():
                            if k == "original_names":
                                if "original_names" not in n:
                                    n["original_names"] = []
                                for val in v:
                                    if val not in n["original_names"]:
                                        n["original_names"].append(val)
                            else:
                                n[k] = v
                        break
            
    def add_link(source, target, label="", properties=None):
        links.append({
            "source": source,
            "target": target,
            "label": label,
            **(properties or {})
        })
    all_dashboards = db.query(Dashboard).all()
    matched_dashboards = []
    # Pass 1: Filter dashboards and extract unique KPI names
    unique_kpi_names = set()
    for dashboard in all_dashboards:
        if not dashboard.name or not dashboard.ai_summary:
            continue
            
        d_name_lower = dashboard.name.lower()
        matched = False
        for req_d in requested_dashboards:
            if req_d == d_name_lower or req_d == f"{d_name_lower}.twb" or req_d == f"{d_name_lower}.twbx" or (len(req_d) > 5 and (d_name_lower.startswith(req_d) or req_d.startswith(d_name_lower))):
                matched = True
                break
                
        if not matched:
            continue
            
        try:
            parsed = json.loads(dashboard.ai_summary)
        except:
            parsed = parse_llm_json(dashboard.ai_summary)
        if not parsed or "kpis" not in parsed:
            continue
            
        matched_dashboards.append((dashboard, parsed))
        
        for kpi in parsed.get("kpis", []):
            if kpi.get("name"):
                unique_kpi_names.add(kpi.get("name"))
                
    # Use AI semantic clustering to join KPIs that mean the exact same thing across different dashboards.
    kpi_mapping = get_kpi_clusters(tuple(sorted(list(unique_kpi_names))))
    # Pass 2: Build the graph
    for dashboard, parsed in matched_dashboards:
        dashboard_data_for_llm.append({
            "name": dashboard.name,
            "summary": dashboard.ai_summary
        })
        dash_id = f"dash_{dashboard.name}"
        add_node(dash_id, "Dashboard", dashboard.name.title(), {"complexity": getattr(dashboard, "complexity_score", 1.0) or 1.0})
        
        domain = getattr(dashboard, "domain_classification", None)
        if domain:
            domain_id = f"domain_{domain.lower()}"
            add_node(domain_id, "Business Area", domain)
            add_link(dash_id, domain_id, "belongs_to")
            
        mapping = get_user_group_mapping()
        db_name_lower = dashboard.name.strip().lower()
        wb_base_name = dashboard.workbook.source_file.replace('.twbx', '').replace('.twb', '').strip().lower() if getattr(dashboard, "workbook", None) else db_name_lower
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
        groups = excel_groups if excel_groups else (getattr(dashboard, "user_groups", []) or [])
        days_ago_excel = excel_data.get("days_ago") if isinstance(excel_data, dict) else None
        
        for group in groups:
            group_id = f"group_{group.lower().replace(' ', '_')}"
            add_node(group_id, "User Group", group)
            add_link(dash_id, group_id, "used_by")
            
        insight = parsed.get("insight_level")
        # Removing Insights Level node from Dashboard as per user request
        
        # Access Frequency Calculation based on uploaded_at (as proxy for initial access)
        try:
            from datetime import datetime
            if days_ago_excel is not None:
                days_old = days_ago_excel
            elif dashboard.workbook and dashboard.workbook.uploaded_at:
                uploaded_date = dashboard.workbook.uploaded_at
                days_old = (datetime.utcnow() - uploaded_date).days
            else:
                days_old = 0
                
            if days_old <= 180:
                freq_label = "Recent Activity (< 6 months)"
            elif days_old <= 365:
                freq_label = "Moderate Activity (6-12 months)"
            else:
                freq_label = "Stale Activity (> 1 year)"
            
            freq_id = f"freq_{freq_label.lower().replace(' ', '_').replace('<', 'lt').replace('>', 'gt')}"
            add_node(freq_id, "Access Frequency", freq_label)
            add_link(dash_id, freq_id, "accessed")
        except Exception as e:
            print(f"Failed to calculate access frequency: {e}")
            
        kpis = parsed.get("kpis", [])
        for kpi in kpis:
            original_kpi_name = kpi.get("name")
            if original_kpi_name:
                # Use the canonical matched name!
                canonical_name = kpi_mapping.get(original_kpi_name, original_kpi_name)
                
                import re
                
                # Normalize 'avg' or 'avg.' to 'Average'
                canonical_name = re.sub(r"\bavg\.?\b", "Average", canonical_name, flags=re.IGNORECASE)
                
                match = re.search(r"^(.*?)\s+(?:by|per)\s+(.*)$", canonical_name, re.IGNORECASE)
                if match:
                    core_metric = match.group(1).strip()
                    granularity = f"{match.group(2).strip().title()} Level"
                else:
                    core_metric = canonical_name.strip()
                    granularity = "Overall Level"
                
                kpi_id = f"kpi_{core_metric.lower().replace(' ', '_')}"
                
                # We can keep the definition from any of them, or combine them
                add_node(kpi_id, "KPI", core_metric, {
                    "definition": kpi.get("definition", ""),
                    "original_names": [original_kpi_name]
                })
                
                granularity_id = f"granularity_{granularity.lower().replace(' ', '_')}"
                add_node(granularity_id, "Granularity Level", granularity)
                
                add_link(dash_id, kpi_id, "", {"granularity": granularity})
                add_link(kpi_id, granularity_id, "")
        # Use AI parsed conceptual tables if available, fallback to raw metadata tables
        ai_tables = parsed.get("tables", [])
        if ai_tables:
            for t_data in ai_tables:
                t_name = t_data.get("name")
                if t_name:
                    t_id = f"table_{t_name.lower()}"
                    add_node(t_id, "Table", t_name)
                    add_link(dash_id, t_id, "queries")
        else:
            raw_meta = getattr(dashboard, "raw_metadata", {}) or {}
            tables = raw_meta.get("tables", [])
            for table_name in tables:
                t_id = f"table_{table_name.lower()}"
                add_node(t_id, "Table", table_name)
                add_link(dash_id, t_id, "queries")
    return nodes, links, dashboard_data_for_llm
@router.get("/data")
async def get_kpi_graph_data(
    dashboards: str = Query(..., description="Comma separated list of dashboard names"),
    db: Session = Depends(get_db)
):
    cleaned_dashboards = dashboards.replace("|||", ",")
    requested_dashboards = [d.strip().lower() for d in cleaned_dashboards.split(",") if d.strip()]
    nodes, links, _ = build_graph_for_dashboards(requested_dashboards, db)
    return {"nodes": nodes, "links": links}
@router.get("/summary")
async def get_kpi_graph_summary(
    dashboards: str = Query(..., description="Comma separated list of dashboard names"),
    focus_type: str = Query("all", description="Type of nodes to focus the summary on"),
    db: Session = Depends(get_db)
):
    cleaned_dashboards = dashboards.replace("|||", ",")
    requested_dashboards = [d.strip().lower() for d in cleaned_dashboards.split(",") if d.strip()]
    nodes, links, dashboard_data_for_llm = build_graph_for_dashboards(requested_dashboards, db)
    if not dashboard_data_for_llm:
        return {"summary": "No AI summary data found for the selected dashboards."}
    from app.core.llm import get_llm
    llm = get_llm(temperature=0.0) # lower temp for more deterministic cache
    if not llm:
        return {"summary": "LLM is not configured. Cannot generate similarity and difference summary."}
    # Sort to ensure deterministic prompt for caching
    nodes.sort(key=lambda x: x["id"])
    links.sort(key=lambda x: f"{x['source']}-{x['target']}")
    dashboard_data_for_llm.sort(key=lambda x: x["name"])
    prompt = "You are a BI governance expert analyzing a network graph of dashboards, KPIs, Tables, Business Areas, User Groups, Granularity Levels, and Access Recencies.\n\n"
    if focus_type != "all" and focus_type:
        prompt += f"The user has just clicked to highlight the '{focus_type}' view in the graph.\n"
        prompt += f"Your task is to find high-level strategic insights specifically focusing on relationships, overlaps, and patterns related to {focus_type.upper()}.\n"
    else:
        prompt += "Your task is to find high-level strategic insights from the graph connections and present them clearly.\n"
        
    prompt += "CRITICAL INSTRUCTIONS:\n"
    prompt += "- Start your response exactly with: 'The key insights from the graph are:'\n"
    prompt += "- Output a simple, flat list of bullet points (using dashes '-').\n"
    prompt += "- STRICT LIMIT: Provide exactly 3 to 4 bullet points. Only write the absolute MOST important and surprising insights.\n"
    prompt += "- EXTREME BREVITY: Every single bullet point MUST be exactly 1 short sentence (maximum 15 words). Get straight to the point.\n"
    prompt += "- DO NOT use headings, sub-headings, or grouped bullet points.\n"
    prompt += "- Think deeply about the data. Find interesting patterns such as dashboards sharing tables but having different KPIs, completely isolated dashboards, unexpected overlap in teams, etc.\n"
    prompt += "- IF ONLY ONE DASHBOARD IS PRESENT: Focus entirely on its core strategic value, who uses it, its main KPIs, and its underlying tables.\n"
    prompt += "- IF MULTIPLE DASHBOARDS ARE PRESENT: You MUST ONLY provide combined insights (e.g. 'Both Dashboard A and Dashboard B share the X table but target different users'). Do NOT write bullet points that just summarize a single dashboard individually.\n"
    prompt += "- Output PLAIN TEXT ONLY. Do not use bold (**) or other markdown besides dashes for bullet points.\n\n"
    
    prompt += "--- Graph Nodes ---\\n"
    for n in nodes:
        prompt += f"- {n['group']}: {n['label']}\\n"
        
    prompt += "\\n--- Graph Links (Connections) ---\\n"
    for l in links:
        prompt += f"- {l['source']} --[{l['label']}]--> {l['target']}\\n"
    prompt += "\\n--- Dashboard Summaries ---\\n"
    for data in dashboard_data_for_llm:
        prompt += f"Dashboard: {data['name']}\\n{data['summary']}\\n\\n"
    try:
        result = llm.invoke(prompt)
        return {"summary": result.content.strip()}
    except Exception as e:
        import traceback
        print(f"--- AI CALL FAILED in kpi_graph.py summary ---\\n{e}")
        return {"summary": "I am experiencing connection issues to the AI provider. Please check your network and API keys."}
