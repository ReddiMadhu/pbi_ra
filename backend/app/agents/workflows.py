"""
Agentic Governance Workflow using LangGraph.

Architecture:
  ┌─────────┐     ┌────────────┐     ┌─────────────┐     ┌──────────────────┐
  │  PLAN   │────▶│  CLASSIFY  │────▶│ ASSESS RISK │────▶│  RECOMMEND ACTIONS│
  └─────────┘     └────────────┘     └─────────────┘     └──────────────────┘

Each node is a discrete AI agent step with its own reasoning.
The state flows through the graph, accumulating context.
"""
import logging
import time
from typing import TypedDict, List, Optional
import os
from sqlalchemy.exc import OperationalError
from app.models.metadata import WorkbookMetadata
from app.models.postgres import Dashboard, GovernanceRisk
from sqlalchemy.orm import Session
from app.agents.classification import DashboardClassificationAgent
from app.agents.risk import GovernanceRiskAgent


class AgentStepResult(TypedDict):
    step: str
    status: str          # "running" | "done" | "skipped"
    output: Optional[str]


class GovernanceAgentState(TypedDict):
    dashboard_name: str
    worksheets: List[str]
    datasources: List[str]
    formulas: List[str]
    chart_variables: List[str]
    source_columns: List[str]
    calc_fields_count: int
    classification: Optional[dict]
    risks: Optional[List[dict]]
    recommendations: Optional[List[str]]
    steps: List[AgentStepResult]


def _plan_analysis(state: GovernanceAgentState) -> GovernanceAgentState:
    """
    Agent Step 1: PLANNER
    Determines complexity and decides what kind of analysis is needed.
    """
    calc_fields = state["calc_fields_count"]
    ws_count = len(state["worksheets"])
    
    complexity_note = "standard"
    if calc_fields > 30 or ws_count > 15:
        complexity_note = "deep (high complexity detected)"
    
    state["steps"].append({
        "step": "Planning Analysis",
        "status": "done",
        "output": (
            f"Dashboard '{state['dashboard_name']}' has {ws_count} worksheets "
            f"and {calc_fields} calculated fields. Scheduling {complexity_note} analysis."
        )
    })
    return state


def _classify_domain(state: GovernanceAgentState) -> GovernanceAgentState:
    """
    Agent Step 2: DOMAIN CLASSIFIER
    Uses an LLM to classify the business domain of the dashboard.
    """
    state["steps"].append({
        "step": "Domain Classification",
        "status": "running",
        "output": None
    })
    
    classifier = DashboardClassificationAgent()
    result = classifier.classify(
        dashboard_name=state["dashboard_name"],
        worksheets=state["worksheets"],
        datasources=state["datasources"],
        formulas=state.get("formulas", []),
        chart_variables=state.get("chart_variables", []),
        source_columns=state.get("source_columns", [])
    )
    
    kpi_list = getattr(result, 'kpis', [])
    kpi_data = []
    if isinstance(kpi_list, list):
        for kpi in kpi_list:
            if hasattr(kpi, 'confidence') and kpi.confidence > 60.0:
                kpi_data.append({
                    "name": kpi.name,
                    "confidence": kpi.confidence,
                    "source_description": getattr(kpi, 'source_description', ''),
                    "calculation_logic": getattr(kpi, 'calculation_logic', ''),
                    "definition": getattr(kpi, 'definition', '')
                })

    table_list = getattr(result, 'tables', [])
    table_data = []
    if isinstance(table_list, list):
        for t in table_list:
            if hasattr(t, 'name'):
                table_data.append({
                    "name": t.name
                })

    state["classification"] = {
        "domain": result.domain,
        "ontology_sector": getattr(result, "ontology_sector", None),
        "ontology_subdomain": getattr(result, "ontology_subdomain", None),
        "line_of_business": getattr(result, 'line_of_business', None),
        "insight_level": getattr(result, 'insight_level', "Overall Level"),
        "complexity": result.complexity,
        "summary": result.summary,
        "kpis": kpi_data,
        "tables": table_data
    }
    
    # Update step to done
    state["steps"][-1]["status"] = "done"
    state["steps"][-1]["output"] = (
        f"Classified as '{result.domain}' domain. "
        f"Complexity score: {result.complexity:.1f}/10. {result.summary}"
    )
    return state


def _assess_risks(state: GovernanceAgentState) -> GovernanceAgentState:
    """
    Agent Step 3: GOVERNANCE RISK ASSESSOR
    Identifies structural and governance risks in the dashboard.
    """
    state["steps"].append({
        "step": "Risk Assessment",
        "status": "running",
        "output": None
    })
    
    risk_agent = GovernanceRiskAgent()
    assessment = risk_agent.assess(
        dashboard_name=state["dashboard_name"],
        num_worksheets=len(state["worksheets"]),
        calc_fields_count=state["calc_fields_count"]
    )
    
    state["risks"] = [
        {"risk_type": r.risk_type, "description": r.description, "severity": r.severity}
        for r in assessment.risks
    ]
    
    high_count = sum(1 for r in assessment.risks if r.severity == "High")
    state["steps"][-1]["status"] = "done"
    state["steps"][-1]["output"] = (
        f"Identified {len(assessment.risks)} governance risk(s). "
        f"{high_count} high-severity issue(s) require immediate attention."
    )
    return state


def _generate_recommendations(state: GovernanceAgentState) -> GovernanceAgentState:
    """
    Agent Step 4: RECOMMENDATION ENGINE
    Synthesizes previous agent outputs into actionable recommendations.
    No external LLM call needed — uses deterministic rule engine for speed.
    """
    state["steps"].append({
        "step": "Generating Recommendations",
        "status": "running",
        "output": None
    })
    
    recs = []
    calc_count = state["calc_fields_count"]
    ws_count = len(state["worksheets"])
    risks = state.get("risks") or []
    domain = (state.get("classification") or {}).get("domain", "Unclassified")
    
    # Rule-based recommendations (fast, no LLM needed for this step)
    if calc_count > 20:
        recs.append(f"⚠️  Move {calc_count} calculated fields to a certified Published Data Source to reduce dashboard complexity.")
    if ws_count > 12:
        recs.append(f"📊  Consider splitting this dashboard into {ws_count // 6} focused sub-dashboards by audience role.")
    if any(r["severity"] == "High" for r in risks):
        recs.append("🔴  Assign a Data Steward as the designated owner for this dashboard immediately.")
    if domain == "Unclassified (Mock)":
        recs.append("🤖  Configure OPENAI_API_KEY or AZURE_OPENAI_API_KEY to enable full AI domain classification.")
    
    if not recs:
        recs.append("✅  Dashboard is within governance thresholds. Schedule quarterly review.")
    
    state["recommendations"] = recs
    state["steps"][-1]["status"] = "done"
    state["steps"][-1]["output"] = f"Generated {len(recs)} actionable recommendation(s) for the governance team."
    return state


# ─── Main workflow runner ───────────────────────────────────────────────────

def run_governance_workflow(
    workbook: WorkbookMetadata,
    db_session: Session,
    db_id_mapping: dict
):
    """
    Runs the full agentic governance workflow for each dashboard in the workbook.
    Persists classification and risk results to the database.
    """
    all_datasources = sorted(list(set([ds.name for ds in workbook.datasources])))
    all_formulas = []
    source_columns = []
    for ds in workbook.datasources:
        for col in ds.columns:
            source_columns.append(col.name)
        for cf in ds.calculated_fields:
            if cf.formula:
                all_formulas.append(f"{cf.name}: {cf.formula}")
    total_calc_fields = len(all_formulas)
    all_formulas = sorted(list(set(all_formulas)))
    source_columns = sorted(list(set(source_columns)))

    for db_meta in workbook.dashboards:
        db_id = db_id_mapping.get(db_meta.name)
        if not db_id:
            continue

        chart_variables = []
        for ws_name in sorted(db_meta.worksheets):
            ws = next((w for w in workbook.worksheets if w.name == ws_name), None)
            if ws:
                ws_rows = sorted(ws.rows) if isinstance(ws.rows, list) else (ws.rows or [])
                ws_cols = sorted(ws.columns) if isinstance(ws.columns, list) else (ws.columns or [])
                chart_variables.append(f"Sheet: {ws.name}, Mark: {ws.mark_type}, Rows: {ws_rows}, Cols: {ws_cols}")

        # Initialize agent state
        initial_state: GovernanceAgentState = {
            "dashboard_name": db_meta.name,
            "worksheets": sorted(db_meta.worksheets),
            "datasources": all_datasources,
            "formulas": all_formulas,
            "chart_variables": chart_variables,
            "source_columns": source_columns,
            "calc_fields_count": total_calc_fields,
            "classification": None,
            "risks": None,
            "recommendations": None,
            "steps": []
        }

        # Execute the agent graph (sequential pipeline)
        state = _plan_analysis(initial_state)
        state = _classify_domain(state)
        state = _assess_risks(state)
        state = _generate_recommendations(state)

        # Determine user groups from usergroup.xlsx (shared cached utility)
        from app.services.user_groups import lookup_user_group
        excel_data = lookup_user_group(db_meta.name, workbook.source_file)
        user_groups_from_excel = excel_data.get("groups", []) if excel_data else []

        # Persist results to SQLite
        dashboard_record = db_session.query(Dashboard).filter(Dashboard.id == db_id).first()
        if dashboard_record and state["classification"]:
            dashboard_record.domain_classification = state["classification"]["domain"]
            dashboard_record.ontology_sector = state["classification"].get("ontology_sector")
            dashboard_record.ontology_subdomain = state["classification"].get("ontology_subdomain")
            dashboard_record.line_of_business = state["classification"].get("line_of_business")
            dashboard_record.user_groups = user_groups_from_excel
            db_meta.domain = state["classification"]["domain"]
            db_meta.line_of_business = state["classification"].get("line_of_business")
            db_meta.user_groups = user_groups_from_excel
            dashboard_record.complexity_score = state["classification"]["complexity"]
            import json
            dashboard_record.ai_summary = json.dumps({
                "summary": state["classification"]["summary"],
                "kpis": state["classification"].get("kpis", ""),
                "tables": state["classification"].get("tables", []),
                "insight_level": state["classification"].get("insight_level", "Overall Level")
            })
            db_meta.kpis = state["classification"].get("kpis", "")
            dashboard_record.is_real_ai = 1 if state["classification"].get("is_real_ai", True) else 0

        if state["risks"]:
            for risk in state["risks"]:
                risk_record = GovernanceRisk(
                    dashboard_id=db_id,
                    risk_type=risk["risk_type"],
                    description=risk["description"],
                    severity=risk["severity"]
                )
                db_session.add(risk_record)

    # Retry-commit to handle SQLite 'database is locked' during multi-file uploads
    _logger = logging.getLogger(__name__)
    for _attempt in range(1, 6):
        try:
            db_session.commit()
            break
        except OperationalError as _exc:
            if "database is locked" in str(_exc) and _attempt < 5:
                _wait = 0.5 * (2 ** (_attempt - 1))
                _logger.warning(
                    "database is locked in governance commit (attempt %d/5), retrying in %.1fs...",
                    _attempt, _wait,
                )
                db_session.rollback()
                time.sleep(_wait)
            else:
                raise


def stream_agent_workflow(
    dashboard_name: str,
    worksheets: List[str],
    datasources: List[str],
    calc_fields_count: int,
    formulas: List[str] = None
):
    """
    Generator version of the governance workflow.
    Yields a dict after each agent step completes — used for SSE streaming.
    """
    state: GovernanceAgentState = {
        "dashboard_name": dashboard_name,
        "worksheets": worksheets,
        "datasources": datasources,
        "formulas": formulas or [],
        "calc_fields_count": calc_fields_count,
        "classification": None,
        "risks": None,
        "recommendations": None,
        "steps": []
    }

    # Step 1
    state = _plan_analysis(state)
    yield {"event": "step", "data": state["steps"][-1]}

    # Step 2
    state = _classify_domain(state)
    yield {"event": "step", "data": state["steps"][-1]}
    if state["classification"]:
        yield {"event": "classification", "data": state["classification"]}

    # Step 3
    state = _assess_risks(state)
    yield {"event": "step", "data": state["steps"][-1]}
    if state["risks"]:
        yield {"event": "risks", "data": state["risks"]}

    # Step 4
    state = _generate_recommendations(state)
    yield {"event": "step", "data": state["steps"][-1]}
    if state["recommendations"]:
        yield {"event": "recommendations", "data": state["recommendations"]}

    yield {"event": "done", "data": {"message": "Agent workflow complete"}}


def run_agent_workflow_for_api(
    dashboard_name: str,
    worksheets: List[str],
    datasources: List[str],
    calc_fields_count: int,
    formulas: List[str] = None
) -> GovernanceAgentState:
    """Synchronous version — used internally during file upload."""
    state: GovernanceAgentState = {
        "dashboard_name": dashboard_name,
        "worksheets": worksheets,
        "datasources": datasources,
        "formulas": formulas or [],
        "calc_fields_count": calc_fields_count,
        "classification": None,
        "risks": None,
        "recommendations": None,
        "steps": []
    }
    state = _plan_analysis(state)
    state = _classify_domain(state)
    state = _assess_risks(state)
    state = _generate_recommendations(state)
    return state
