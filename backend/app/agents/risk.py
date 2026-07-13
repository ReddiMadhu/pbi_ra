import os
from app.core.llm import get_llm
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field
from typing import List

class RiskItem(BaseModel):
    risk_type: str = Field(description="Type of risk (e.g., 'High Complexity', 'No Owner', 'Stale Data')")
    description: str = Field(description="Detailed explanation of the risk")
    severity: str = Field(description="Severity: 'High', 'Medium', or 'Low'")

class RiskAssessment(BaseModel):
    risks: List[RiskItem] = Field(description="List of identified governance risks")

class GovernanceRiskAgent:
    def __init__(self):
        self.llm = get_llm(temperature=0.2)
        self.parser = PydanticOutputParser(pydantic_object=RiskAssessment)

    def _generate_fallback(self, dashboard_name: str, num_worksheets: int, calc_fields_count: int) -> RiskAssessment:
        risks = []
        if num_worksheets > 12:
            risks.append(RiskItem(
                risk_type="High Complexity",
                description=f"Dashboard contains {num_worksheets} worksheets. Having >12 worksheets creates visual overload and increases load times.",
                severity="High"
            ))
        elif num_worksheets > 6:
            risks.append(RiskItem(
                risk_type="Medium Complexity",
                description=f"Dashboard contains {num_worksheets} worksheets, which is moderately complex and may affect usability.",
                severity="Medium"
            ))
            
        if calc_fields_count > 30:
            risks.append(RiskItem(
                risk_type="Heavy Calculation Overhead",
                description=f"Contains {calc_fields_count} custom calculated fields. This business logic should be materialized in the data layer.",
                severity="High"
            ))
        elif calc_fields_count > 15:
            risks.append(RiskItem(
                risk_type="Calculation Overlap",
                description=f"Dashboard defines {calc_fields_count} calculations locally. Consider certified data sources.",
                severity="Medium"
            ))
            
        if not risks:
            risks.append(RiskItem(
                risk_type="Low Risk Profile",
                description="Dashboard complies with all design and structural governance thresholds.",
                severity="Low"
            ))
            
        return RiskAssessment(risks=risks)

    def assess(self, dashboard_name: str, num_worksheets: int, calc_fields_count: int) -> RiskAssessment:
        if not self.llm:
            return self._generate_fallback(dashboard_name, num_worksheets, calc_fields_count)

        prompt = PromptTemplate(
            template="""You are a Data Governance Risk Assessor.
Review the following dashboard metrics and identify potential governance risks based on best practices.
For example, >15 worksheets or >50 calculated fields is high complexity/maintenance risk.

Dashboard Name: {dashboard_name}
Total Worksheets: {num_worksheets}
Total Calculated Fields: {calc_fields_count}

{format_instructions}
""",
            input_variables=["dashboard_name", "num_worksheets", "calc_fields_count"],
            partial_variables={"format_instructions": self.parser.get_format_instructions()}
        )

        try:
            _input = prompt.format_prompt(
                dashboard_name=dashboard_name,
                num_worksheets=num_worksheets,
                calc_fields_count=calc_fields_count
            )
            
            output = self.llm.invoke(_input.to_string())
            return self.parser.parse(output.content)
        except Exception as e:
            # Catch LLM errors gracefully and return best-practice rule assessment
            return self._generate_fallback(dashboard_name, num_worksheets, calc_fields_count)

