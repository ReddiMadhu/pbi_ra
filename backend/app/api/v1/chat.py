"""
chat.py — Conversational BI endpoint.

Routes natural language questions to the right handler:
  - Metadata questions → SQLite query
  - Data questions     → Hyper extract query
  - Concept questions  → LLM answer
"""
import os
import json
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.db.session import get_db
from app.models.postgres import Workbook, Dashboard, DatasourceModel, TableModel, CalculatedField

router = APIRouter()


class ChatRequest(BaseModel):
    question: str
    workbook_name: str


def _get_llm():
    from app.core.llm import get_llm
    return get_llm(temperature=0.2)


def _route_question(question: str, llm) -> str:
    """Use LLM to decide which handler to use."""
    if not llm:
        # Keyword-based fallback routing
        q = question.lower()
        if any(kw in q for kw in ["table", "dashboard", "sheet", "field", "column", "datasource", "workbook", "how many"]):
            return "metadata"
        if any(kw in q for kw in ["row", "data", "value", "show me", "first", "record", "sample"]):
            return "data"
        return "llm"

    prompt = f"""You are routing a user question to the right data handler.

Question: "{question}"

Choose one:
- "metadata" → question is about Tableau structure (dashboards, worksheets, tables, calculated fields, datasources)
- "data" → question asks for actual data values from tables (rows, records, samples)
- "llm" → general explanation, interpretation, or governance advice

Reply with ONLY ONE WORD: metadata, data, or llm"""

    try:
        result = llm.invoke(prompt)
        content = result.content.strip().lower()
        if "metadata" in content:
            return "metadata"
        if "data" in content:
            return "data"
        return "llm"
    except Exception as e:
        import traceback
        print(f"--- AI CALL FAILED in _route_question ---\n{e}")
        return "metadata"


def _answer_metadata(question: str, workbook_name: str, db: Session, llm) -> dict:
    """Query SQLite for structural metadata and answer with LLM."""
    if workbook_name == "Global Portfolio":
        dashboards = db.query(Dashboard).all()
        context_lines = []
        for d in dashboards:
            wb_name = d.workbook.source_file if d.workbook else "Unknown"
            line = f"Dashboard: {d.name} (File: {wb_name})"
            for w in d.worksheets:
                chart = w.mark_type or "Automatic"
                cols = w.columns or []
                rows = w.rows or []
                line += f"\n  - Worksheet: {w.name} (Chart: {chart}, Columns: {cols}, Rows: {rows})"
            context_lines.append(line)
        
        context = "Global Portfolio Metadata:\n" + "\n".join(context_lines)
        
        if not llm:
            return {"answer": f"Portfolio has {len(dashboards)} dashboards loaded. Please enable LLM for detailed answers.", "source": "metadata"}
            
        prompt = f"""You are a Tableau governance assistant. Answer the user question using strictly only the metadata below.
Your responses MUST be extremely concise and accurate. Do not include any filler text, conversational pleasantries, or additional info.
If the user asks about a dashboard containing specific information, you must reply exactly in this format: 
'Yes we have dashboard on [Topic they asked about]. Here are they:
- [Dashboard Name](nav://<Workbook File Name>) (Worksheets: Worksheet 1, Worksheet 2, ...)
- [Another Dashboard Name](nav://<Workbook File Name>) (Worksheets: Worksheet 3, ...)'

- Replace [Topic they asked about] with the actual topic.
- You MUST format each dashboard as a markdown list item with a link using 'nav://' as shown above.
- Group ALL relevant worksheets under their respective dashboard entry. Do NOT repeat the same dashboard name multiple times.
- Replace <Workbook File Name> with the exact 'File' name provided in the context.

{context}

Question: {question}
Answer:"""
        try:
            result = llm.invoke(prompt)
            text = result.content.strip()
            
            import re
            import urllib.parse
            dashboards = re.findall(r"\[(.*?)\]\(nav://[^\)]+\)", text)
            print("EXTRACTED DASHBOARDS:", dashboards)
            if dashboards:
                unique_dashboards = list(dict.fromkeys(dashboards))
                print("UNIQUE DASHBOARDS:", unique_dashboards)
                if len(unique_dashboards) > 1:
                    encoded = urllib.parse.quote(','.join(unique_dashboards))
                    text += f"\n\n[Go to graphs](nav://kpi_graph|{encoded})"
                    print("APPENDED GRAPH LINK")
            
            return {"answer": text, "source": "metadata"}
        except Exception as e:
            import traceback
            print(f"--- AI CALL FAILED in _answer_metadata (Portfolio) ---\n{e}")
            return {"answer": "I am experiencing connection issues to the AI provider. Please check your network and API keys.", "source": "metadata"}

    workbook = db.query(Workbook).filter(Workbook.name.like(f"%{workbook_name}%")).first()
    if not workbook:
        return {"answer": "I couldn't find this workbook in the current session. Please re-upload the file.", "source": "metadata"}

    dashboards = workbook.dashboards
    datasources = db.query(DatasourceModel).filter(DatasourceModel.workbook_id == workbook.id).all()
    tables = db.query(TableModel).join(DatasourceModel).filter(DatasourceModel.workbook_id == workbook.id).all()
    calc_fields = [cf for d in dashboards for cf in d.calculated_fields]

    context = f"""Workbook File Name: {workbook.source_file}
Workbook: {workbook.name}
Dashboards ({len(dashboards)}): {', '.join(d.name for d in dashboards)}
Datasources ({len(datasources)}): {', '.join(ds.caption or ds.name for ds in datasources)}
Physical Tables ({len(tables)}): {', '.join(t.name for t in tables[:20])}
Calculated Fields ({len(calc_fields)}): {', '.join(cf.name for cf in calc_fields[:15])}"""

    if not llm:
        return {
            "answer": f"Workbook has {len(dashboards)} dashboards, {len(tables)} tables, {len(datasources)} datasources, and {len(calc_fields)} calculated fields.",
            "source": "metadata",
            "raw": context
        }

    prompt = f"""You are a Tableau governance assistant. Answer the user question using strictly only the metadata below.
Your responses MUST be extremely concise and accurate. Do not include any filler text, conversational pleasantries, or additional info.
If the user asks about a dashboard containing specific information, you must reply exactly in this format: 
'Yes we have dashboard on [Topic they asked about]. Here are they:
- [Dashboard Name](nav://<Workbook File Name>) (Worksheets: Worksheet 1, Worksheet 2, ...)
- [Another Dashboard Name](nav://<Workbook File Name>) (Worksheets: Worksheet 3, ...)'

- Replace [Topic they asked about] with the actual topic.
- You MUST format each dashboard as a markdown list item with a link using 'nav://' as shown above.
- Group ALL relevant worksheets under their respective dashboard entry. Do NOT repeat the same dashboard name multiple times.
- Replace <Workbook File Name> with the exact 'Workbook File Name' provided in the context.

{context}

Question: {question}
Answer:"""

    try:
        result = llm.invoke(prompt)
        text = result.content.strip()
        
        import re
        import urllib.parse
        dashboards = re.findall(r"\[(.*?)\]\(nav://[^\)]+\)", text)
        print("EXTRACTED DASHBOARDS (Specific):", dashboards)
        if dashboards:
            unique_dashboards = list(dict.fromkeys(dashboards))
            print("UNIQUE DASHBOARDS (Specific):", unique_dashboards)
            if len(unique_dashboards) > 1:
                encoded = urllib.parse.quote(','.join(unique_dashboards))
                text += f"\n\n[Go to graphs](nav://kpi_graph|{encoded})"
                print("APPENDED GRAPH LINK (Specific)")
                
        return {"answer": text, "source": "metadata"}
    except Exception as e:
        import traceback
        print(f"--- AI CALL FAILED in _answer_metadata (Workbook) ---\n{e}")
        return {"answer": "I am experiencing connection issues to the AI provider. Please check your network and API keys.", "source": "metadata"}


def _answer_data(question: str, workbook_name: str, llm) -> dict:
    """Try to answer by querying the hyper extract."""
    try:
        from app.services.parser.hyper_reader import read_hyper_previews
        # We can't re-query the hyper from workbook_name alone (need file path)
        # Return a helpful message
        return {
            "answer": "I can show you table data previews in the 'Table Data Preview' section on this page. For specific queries, I need the original .twbx file path to query the extract directly.",
            "source": "data"
        }
    except Exception as e:
        return {"answer": f"Data query failed: {str(e)}", "source": "data"}


def _answer_llm(question: str, workbook_name: str, llm) -> dict:
    """Pure LLM answer for general governance/Tableau questions."""
    if not llm:
        return {
            "answer": "AI answers require an OPENAI_API_KEY. Configure it in your .env file to enable conversational AI.",
            "source": "llm"
        }
    prompt = f"""You are an expert Tableau governance and BI assistant.
The user is analyzing a Tableau workbook named '{workbook_name}'.
Answer their question clearly and helpfully with your Tableau/governance expertise.

Question: {question}
Answer:"""
    try:
        result = llm.invoke(prompt)
        return {"answer": result.content.strip(), "source": "llm"}
    except Exception as e:
        import traceback
        print(f"--- AI CALL FAILED in _answer_llm ---\n{e}")
        return {"answer": "I am experiencing connection issues to the AI provider. Please check your network and API keys.", "source": "llm"}


@router.post("/query")
async def chat_query(payload: ChatRequest, db: Session = Depends(get_db)):
    llm = _get_llm()
    route = _route_question(payload.question, llm)

    if route == "metadata":
        return _answer_metadata(payload.question, payload.workbook_name, db, llm)
    elif route == "data":
        return _answer_data(payload.question, payload.workbook_name, llm)
    else:
        return _answer_llm(payload.question, payload.workbook_name, llm)
