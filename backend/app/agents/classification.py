import os
from app.core.llm import get_llm
from app.services.ontology.taxonomy import normalize_scope, suggest_from_legacy_domain
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field
from typing import List

class KPIResult(BaseModel):
    name: str = Field(description="The name of the KPI (e.g., 'Loss Ratio', 'Total Sales'). Note: the worksheet name can be a KPI, but not necessarily.")
    confidence: float = Field(description="Confidence score between 0.0 and 100.0 based on how likely this is a key metric for the dashboard.")
    source_description: str = Field(description="Explanation of where this KPI was taken from within the dashboard (e.g. from specific calculated fields, worksheets, or datasources).")
    calculation_logic: str = Field(description="How this KPI is calculated based on the formulas or fields, or standard business calculation if not explicitly provided.")
    definition: str = Field(description="The clear business definition of this KPI.")

class TableResult(BaseModel):
    name: str = Field(description="The name of the conceptual data table (e.g., 'Claims Master', 'Policy Details').")

class ClassificationResult(BaseModel):
    worksheet_and_field_analysis: str = Field(default="Analysis not provided.", description="A detailed step-by-step analysis of the worksheets, the charts within them, and their underlying fields. Explain what they measure and what insights they provide. You must generate this analysis BEFORE determining the domain.")
    domain: str = Field(default="General", description="The business domain of the dashboard. Must be one of: 'Claims & Risk', 'Customer Service', 'New Business Ops', 'Sales & pipeline', 'Product Level Performance'. If none of these fit, invent a highly specific custom domain name based on the dashboard context. Base this decision on your worksheet_and_field_analysis.")
    ontology_sector: str = Field(default="insurance", description="Ontology sector for KPI matching. Must be exactly one of: 'insurance', 'banking', 'finance', 'operational'. For insurance dashboards use 'insurance'.")
    ontology_subdomain: str = Field(default="actuarial_and_risk", description="Ontology subdomain within the sector. For insurance use exactly one of: 'marketing', 'distribution', 'actuarial_and_risk', 'underwriting', 'claims_litigation', 'service_and_operations', 'cx_and_digital'. marketing=sales funnel/campaign; distribution=channel/agency; actuarial_and_risk=reserving/pricing/product portfolio; underwriting=IGO/NIGO/submission quality; claims_litigation=loss ratio/severity/fraud/litigation; service_and_operations=ops TAT/SLA/back-office; cx_and_digital=NPS/digital journeys/app/portal/self-serve.")
    line_of_business: str = Field(default="L&A", description="The line of business the dashboard belongs to. Must be exactly one of: 'L&A', 'P&C', 'Worker compensation', 'reisurance', 'Auto insurance', 'health'. Choose the most appropriate based on analysis.")
    insight_level: str = Field(default="Overall Level", description="The primary level of granularity for the dashboard. MUST be exactly one of: 'Overall Level', 'Agent Level', 'State Level', 'Region Level', 'Product Level'. Use these strict rules: Choose 'Agent Level' ONLY if every KPI is related to agent-level analysis. Choose 'State Level' ONLY if every KPI is related to state-level analysis. Choose 'Region Level' ONLY if every KPI is related to region-level analysis. Choose 'Product Level' ONLY if every KPI is related to product-level analysis. Choose 'Overall Level' if the dashboard contains a mix of different granularities (e.g., some by state, some by region, some by agent).")
    complexity: float = Field(default=5.0, description="A complexity score from 1.0 to 10.0 based on the number of worksheets, datasources, and calculated fields.")
    summary: str = Field(default="Summary not provided.", description="A comprehensive description of the dashboard focusing entirely on its business value. MUST be exactly 1 or 2 lines (sentences) maximum. Do NOT mention technical details like the number of worksheets or datasources. Instead, concisely explain what the dashboard shows and explicitly state the intended audience.")
    kpis: List[KPIResult] = Field(default=[], description="A comprehensive list of ALL extracted key performance indicators (KPIs) and their confidence scores. Do not limit the count.")
    tables: List[TableResult] = Field(default=[], description="A list of conceptual AI tables generated based on the KPIs.")
    is_real_ai: bool = True

class DashboardClassificationAgent:
    def __init__(self):
        self.llm = get_llm(temperature=0.1)
        self.parser = PydanticOutputParser(pydantic_object=ClassificationResult)

    def _generate_fallback(self, name: str, worksheets: list, datasources: list, formulas: list = None) -> ClassificationResult:
        # Determine business domain based on keywords in the name/worksheets
        name_lower = name.lower()
        worksheets_str = " ".join(worksheets).lower()
        
        # Build dynamic domain name
        name_parts = [p for p in name.replace('.twbx', '').replace('.twb', '').replace('-', ' ').split('_') if len(p) > 2]
        core_topic = "General"
        if name_parts:
            core_topic = " ".join(p.capitalize() for p in name_parts[:2])
            
        dash_count = len(worksheets)
        ds_count = len(datasources)
        
        type_str = "Reporting"
        if dash_count > 3: type_str = "Analytics"
        elif ds_count > 3: type_str = "Data Ops"
        
        domain = f"{core_topic} {type_str}"
        sector, subdomain = suggest_from_legacy_domain(domain)
        
        # Calculate a highly realistic complexity score based on counts
        complexity = min(10.0, max(1.0, float(len(worksheets) * 1.2 + len(datasources) * 1.5)))
        
        # Build an intelligent, specific summary based on fields
        summary = f"This dashboard provides comprehensive visibility into {core_topic} {type_str.lower()}. "
        summary += f"It is primarily designed to be used by {core_topic} Analysts and Operations teams to optimize workflows and monitor key metrics."
            
        # Generate fallback KPIs from worksheets only (exclude formulas/calculated fields)
        fallback_kpis = [w for w in worksheets[:3]]
        if not fallback_kpis:
            fallback_kpis = [f"{core_topic} Volume", "Total Value", "Completion Rate"]
            
        return ClassificationResult(
            worksheet_and_field_analysis="Fallback generation used. No in-depth analysis available.",
            domain=domain,
            ontology_sector=sector,
            ontology_subdomain=subdomain,
            line_of_business="L&A",
            insight_level="Overall Level",
            complexity=round(complexity, 1),
            summary=summary,
            kpis=[KPIResult(
                name=k, 
                confidence=70.0, 
                source_description="Extracted from fallback logic using dashboard worksheets.",
                calculation_logic="Standard aggregate calculation.",
                definition="A standard key metric for this business domain."
            ) for k in fallback_kpis],
            tables=[],
            is_real_ai=False
        )

    def classify(self, dashboard_name: str, worksheets: list, datasources: list, formulas: list = None, chart_variables: list = None, source_columns: list = None) -> ClassificationResult:
        formulas = formulas or []
        chart_variables = chart_variables or []
        source_columns = source_columns or []
        if not self.llm:
            return self._generate_fallback(dashboard_name, worksheets, datasources, formulas)

        prompt = PromptTemplate(
            template="""You are an elite Data Governance AI and a deep Domain Expert in the Insurance and Reinsurance industry.
Analyze the following Tableau Dashboard metadata carefully (dashboard name, worksheets, chart variables, etc.).

Categories to choose from and their STRICT metric requirements:
You MUST ONLY classify a dashboard into one of the following categories IF you explicitly find the matching metrics listed below in the dashboard's worksheets, charts, or formulas. 

1. Claims & Risk:
   - STRICT LOGIC: Classify as "Claims & Risk" ONLY IF the primary focus in on claims analysis across policies/customers/agents/State (e.g., loss ration,claims severity , fraud detction, incident patterns), and NOT tied to analyzing the performance of a specific insurnace product or product attributes,
   - IMPORTANT EXCLUSION : If claims metrics (e.g., claim amount , frequency) are combined with product-specific attribures (e.g., car brand , model, year,product type) and the intent is to evaluate product/portfolio performance, then classify under "Product- Level Performance" instead of "Claims & Risk".]

2. Customer Service:
   - STRICT LOGIC: ONLY classify here IF you find metrics like case/enquiry/service request tracking, ageing of cases or TAT, SLA complaints, ticket backlog, resolution metrics, or customer interaction/support performance.

3. New Business Ops:
   - STRICT LOGIC: ONLY classify here IF you find metrics like policy application processing, IGO or NIGO, Proposal quality, rejection reasons, Underwriting workflow, or Agent/Channel submission quality.

4. Sales & pipeline:
   - STRICT LOGIC: ONLY classify here IF you find metrics like Sales funnel stages (lead->qualify->negotiate->close), opportunity tracking, revenue pipeline and forecasting, conversion rates, cross-sell revenue, upsell,premium amount or  invoice renewals.

5. Product Level Performance:
   - STRICT LOGIC: ONLY classify here IF the dashboard analyzes a specific product line (e.g., motor insurance, health insurance) using a mix of policies, premiums, AND claims data, especially when combined with product attribures (e.g. car model, year, coverage type)
   - EVEN IF  claims metrics are present , priortize this category when the intent is portfolio/ product analysis rathet than pure claims investigation.

If none of these categories accurately describe the dashboard based on these strict rules, you must invent a concise, accurate custom domain name based on the dashboard context.

ONTOLOGY SCOPING (required for KPI bank matching):
After domain classification, also set ontology_sector and ontology_subdomain for hierarchical ontology matching.
- ontology_sector: one of insurance, banking, finance, operational (use insurance for insurance/reinsurance dashboards)
- ontology_subdomain for insurance (use these exact keys):
  * marketing — sales funnel, campaign, lead conversion, premium pipeline
  * distribution — channel, agency, broker, distribution network
  * actuarial_and_risk — reserving, pricing models, product-level portfolio / risk performance
  * underwriting — IGO/NIGO, proposal quality, submission quality, new business ops
  * claims_litigation — loss ratio, claim severity, fraud, litigation, pure claims investigation
  * service_and_operations — back-office ops, case/TAT/SLA metrics, operations workflow
  * cx_and_digital — customer experience, NPS, digital journeys, app/portal/self-serve usage

CRITICAL INSTRUCTION:
Do not write a generic summary. You MUST first thoroughly analyze the Worksheets, the name of the worksheets, the Worksheet Charts, Variables, and Calculated Field Formulas. In your `worksheet_and_field_analysis`, explain step-by-step what these specific charts (e.g., bar charts, line graphs) and variables (e.g., loss_ratio, premium_amount) are measuring and what insights they provide. 
After conducting this analysis, classify the dashboard strictly into one of the provided categories based on your findings and the STRICT metric requirements above. 
Write a highly detailed description of the actual business insights this dashboard delivers, avoiding vague statements like 'This dashboard shows metrics'. Explain exactly WHAT is being analyzed and WHY it matters.

For KPIs, you act as a Tableau Metadata KPI Extraction Engine. 
Your task is to identify the FINAL BUSINESS KPIs represented ONLY across the dashboard's worksheets.

CRITICAL PRIORITY RULE:
- Detect and extract KPIs ONLY from the worksheets that are used in making this dashboard.
- Do NOT extract or detect KPIs from calculated fields, formulas, or raw source columns. The worksheets and their variables are the sole source of truth for KPIs.

Your Responsibilities:
1. Analyze worksheet metadata and extract business KPIs from them.
2. Deduplicate semantically similar KPIs.
3. Convert technical names into business-friendly KPI names.
4. Ignore Tableau-generated calculation IDs like Calculation_80361114492071937.
5. Standardize naming conventions.
6. Extract ALL final KPIs, do not limit the count.
7. Do not explain reasoning in the final list.

KPI Extraction Rules:

FROM WORKSHEETS:
- You MUST extract EVERY distinct combination of metric and dimension as a separate KPI.
- If a chart shows a metric broken down by a dimension (e.g., bar chart of Total Paid per Agent), you MUST name it "<Metric> by <Dimension>" (e.g., "Total Paid by Agent").
- Do NOT just extract the high-level metric (e.g., "Total Paid"). If there are dimensions, you MUST extract the breakdown KPIs (e.g., "Total Paid by Agent", "Number of Closed Claims by Agent", "Average Days to Close by Agent").
- KPI cards/text tables without dimensions become standalone KPIs.
- Pie/line/bar charts ALWAYS infer breakdown KPIs.
- CRITICAL PRIORITY: If a worksheet's name implies one dimension (e.g., "Region") but the actual chart variables/axes use a different dimension (e.g., "State"), ALWAYS prioritize the actual chart variables. For example, if a worksheet is named "Claims by Region" but the rows/columns use "State", the KPI MUST be named "Claims by State".
Examples:
- Car Make + Total Insurance Policies -> Total Insurance Policies by Car Make
- Agent + Total Paid -> Total Paid by Agent

Deduplication Examples:
- "Cases" and "Total Cases" -> Keep "Total Cases"
- "Average Processed Days" and "Avg Processed Days" -> Keep worksheet naming if available
- "SLA %" and "SLA Compliance Rate" -> Keep clearer business-friendly name
- CRITICAL: "Loss Ratio" and "Loss Ratio by State" (or any KPI vs its breakdown/subset) -> KEEP BOTH. Do NOT combine them.
- CRITICAL: Do NOT deduplicate a metric with its dimensional breakdown. "Total Paid" and "Total Paid by Agent" are DIFFERENT KPIs. Keep both.
- CRITICAL: "Region" and "State" are completely different dimensions. DO NOT combine them. "Claims by Region" and "Claims by State" must both be kept as distinct KPIs.

For each KPI you extract, provide a confidence score (0-100), its 'source_description', 'calculation_logic', and business 'definition'. Include all extracted KPIs and assign the appropriate confidence score.

CONCEPTUAL TABLES INSTRUCTION:
Based on the KPIs you extracted, deduce the conceptual data tables that would be needed to compute these KPIs (e.g., 'Claims Master', 'Policy Details'). Do NOT just rename the existing physical tables. Invent the required conceptual tables.

# Dashboard Name: {dashboard_name}

Worksheets Included: {worksheets}
Worksheet Charts and Variables (Rows/Columns/Filters): {chart_variables}
Underlying Datasources: {datasources}
Source Table Columns: {source_columns}
Calculated Field Formulas: {formulas}

{format_instructions}
""",
            input_variables=["dashboard_name", "worksheets", "chart_variables", "datasources", "source_columns", "formulas"],
            partial_variables={"format_instructions": self.parser.get_format_instructions()}
        )

        try:
            _input = prompt.format_prompt(
                dashboard_name=dashboard_name, 
                worksheets=", ".join(worksheets),
                chart_variables=" | ".join(chart_variables) if chart_variables else "None",
                datasources=", ".join(datasources),
                source_columns=", ".join(source_columns) if source_columns else "None",
                formulas=" | ".join(formulas) if formulas else "None provided"
            )
            
            output = self.llm.invoke(_input.to_string())
            
            try:
                result = self.parser.parse(output.content)
            except Exception as parse_err:
                print(f"Warning: Pydantic parser failed, attempting manual JSON recovery: {parse_err}")
                import json
                import re
                
                content = output.content or ""
                json_match = re.search(r"(\{.*\})", content, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                else:
                    json_str = content
                
                data = json.loads(json_str)
                raw_kpis = data.get("kpis", [])
                if not isinstance(raw_kpis, list):
                    raw_kpis = []
                kpis = []
                for k in raw_kpis:
                    if isinstance(k, dict) and "name" in k:
                        kpis.append(KPIResult(
                            name=k["name"],
                            confidence=float(k.get("confidence", 90.0)),
                            source_description=str(k.get("source_description", "Extracted from worksheets.")),
                            calculation_logic=str(k.get("calculation_logic", "Standard aggregation.")),
                            definition=str(k.get("definition", "Business KPI."))
                        ))
                
                if not kpis:
                    raise parse_err
                
                fallback = self._generate_fallback(dashboard_name, worksheets, datasources, formulas)
                result = ClassificationResult(
                    worksheet_and_field_analysis=data.get("worksheet_and_field_analysis") or "Parsed via manual JSON recovery.",
                    domain=data.get("domain") or fallback.domain,
                    ontology_sector=data.get("ontology_sector") or fallback.ontology_sector,
                    ontology_subdomain=data.get("ontology_subdomain") or fallback.ontology_subdomain,
                    line_of_business=data.get("line_of_business") or fallback.line_of_business,
                    insight_level=data.get("insight_level") or fallback.insight_level,
                    complexity=float(data.get("complexity") or fallback.complexity),
                    summary=data.get("summary") or fallback.summary,
                    kpis=kpis,
                    tables=[TableResult(name=t.get("name")) for t in data.get("tables", []) if isinstance(t, dict) and "name" in t] or fallback.tables,
                    is_real_ai=True
                )

            sector, subdomain = normalize_scope(
                getattr(result, "ontology_sector", None),
                getattr(result, "ontology_subdomain", None),
                legacy_domain=result.domain,
            )
            result.ontology_sector = sector
            result.ontology_subdomain = subdomain
            return result
        except Exception as e:
            import traceback
            print(f"--- AI CALL FAILED in DashboardClassificationAgent.classify ---\n{e}")
            return self._generate_fallback(dashboard_name, worksheets, datasources, formulas)

class AreaDescriptionResult(BaseModel):
    description: str = Field(description="A highly concise summary of the business area and dashboard relationships. MUST BE strictly 1 or 2 sentences maximum.")

class AreaDescriptionAgent:
    def __init__(self):
        self.llm = get_llm(temperature=0.3)
        self.parser = PydanticOutputParser(pydantic_object=AreaDescriptionResult)

    def _generate_fallback(self, area_name: str, dashboard_names: list = None) -> AreaDescriptionResult:
        dash_str = ", ".join(dashboard_names[:3]) if dashboard_names else "key metrics"
        return AreaDescriptionResult(description=f"This area focuses on {area_name}, including insights derived from {dash_str}. These dashboards provide deep operational and strategic visibility into core business processes.")

    def generate(self, area_name: str, dashboard_metadata: list) -> AreaDescriptionResult:
        if not self.llm:
            names = [d.get("name", "") for d in dashboard_metadata] if dashboard_metadata else []
            return self._generate_fallback(area_name, names)

        import json
        dashboards_json = json.dumps(dashboard_metadata, indent=2)

        prompt = PromptTemplate(
            template="""You are an elite Data Governance AI and an Insurance Domain Expert.
The user is viewing the business area: '{area_name}'.
The following dashboards and their metadata (KPIs, user groups, tables used) are classified under this area:
{dashboards}

Write an EXTREMELY CONCISE Dashboard Landscape Summary (STRICT MAXIMUM of 2 sentences).
{dynamic_insight_instruction}
Do not list every single detail. Combine these insights into a brief, high-level strategic summary of the business value.

{format_instructions}""",
            input_variables=["area_name", "dashboards"],
            partial_variables={"format_instructions": self.parser.get_format_instructions()}
        )
        
        if len(dashboard_metadata) == 1:
            dynamic_insight_instruction = "CRITICAL INSTRUCTIONS: Since there is only one dashboard in this area, provide key insights specific to this single dashboard."
        else:
            dynamic_insight_instruction = "CRITICAL INSTRUCTIONS: Since there are multiple dashboards, focus EXCLUSIVELY on combined insights, relationships (shared teams, shared KPIs, or shared tables), and isolated dashboards. DO NOT describe the dashboards individually."

        try:
            _input = prompt.format_prompt(
                area_name=area_name,
                dashboards=dashboards_json,
                dynamic_insight_instruction=dynamic_insight_instruction
            )
            output = self.llm.invoke(_input.to_string())
            return self.parser.parse(output.content)
        except Exception as e:
            import traceback
            print(f"--- AI CALL FAILED in AreaDescriptionAgent.generate ---\n{e}")
            names = [d.get("name", "") for d in dashboard_metadata] if dashboard_metadata else []
            return self._generate_fallback(area_name, names)

