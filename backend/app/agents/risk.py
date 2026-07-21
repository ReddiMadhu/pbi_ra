"""Governance Risk Assessment Agent.

Uses deterministic, auditable rules as the primary risk engine.
These are threshold-based best-practice checks that are:
- Fast (no API call, no cost)
- Deterministic (same input → same output every time)
- Explainable (auditors can trace every decision to a concrete rule)

LLM is wasted on this task — the inputs are three numbers (name, worksheet
count, calc field count). Threshold checks are an ``if`` statement, not a
language understanding problem.
"""

from pydantic import BaseModel, Field
from typing import List


class RiskItem(BaseModel):
    risk_type: str = Field(description="Type of risk (e.g., 'High Complexity', 'No Owner', 'Stale Data')")
    description: str = Field(description="Detailed explanation of the risk")
    severity: str = Field(description="Severity: 'High', 'Medium', or 'Low'")
    rule_id: str = Field(default="", description="Identifier for the governance rule that triggered this risk")


class RiskAssessment(BaseModel):
    risks: List[RiskItem] = Field(description="List of identified governance risks")


# ---------------------------------------------------------------------------
# Configurable governance thresholds
# ---------------------------------------------------------------------------
WORKSHEET_HIGH_THRESHOLD = 12
WORKSHEET_MEDIUM_THRESHOLD = 6
CALC_FIELD_HIGH_THRESHOLD = 30
CALC_FIELD_MEDIUM_THRESHOLD = 15


class GovernanceRiskAgent:
    """Rule-based risk assessor. No LLM required.

    Every risk finding is backed by a named governance rule (``rule_id``),
    making the output fully auditable and SOX-friendly.
    """

    def assess(
        self,
        dashboard_name: str,
        num_worksheets: int,
        calc_fields_count: int,
    ) -> RiskAssessment:
        risks: list[RiskItem] = []

        # Rule GOV-R001: Worksheet complexity
        if num_worksheets > WORKSHEET_HIGH_THRESHOLD:
            risks.append(RiskItem(
                risk_type="High Complexity",
                description=(
                    f"Dashboard '{dashboard_name}' contains {num_worksheets} worksheets. "
                    f"Having >{WORKSHEET_HIGH_THRESHOLD} worksheets creates visual overload "
                    f"and increases load times."
                ),
                severity="High",
                rule_id="GOV-R001",
            ))
        elif num_worksheets > WORKSHEET_MEDIUM_THRESHOLD:
            risks.append(RiskItem(
                risk_type="Medium Complexity",
                description=(
                    f"Dashboard '{dashboard_name}' contains {num_worksheets} worksheets, "
                    f"which is moderately complex and may affect usability."
                ),
                severity="Medium",
                rule_id="GOV-R001",
            ))

        # Rule GOV-R002: Calculated field overhead
        if calc_fields_count > CALC_FIELD_HIGH_THRESHOLD:
            risks.append(RiskItem(
                risk_type="Heavy Calculation Overhead",
                description=(
                    f"Contains {calc_fields_count} custom calculated fields. "
                    f"This business logic should be materialized in the data layer."
                ),
                severity="High",
                rule_id="GOV-R002",
            ))
        elif calc_fields_count > CALC_FIELD_MEDIUM_THRESHOLD:
            risks.append(RiskItem(
                risk_type="Calculation Overlap",
                description=(
                    f"Dashboard defines {calc_fields_count} calculations locally. "
                    f"Consider certified data sources."
                ),
                severity="Medium",
                rule_id="GOV-R002",
            ))

        # Rule GOV-R003: No worksheets at all (possibly broken)
        if num_worksheets == 0:
            risks.append(RiskItem(
                risk_type="Empty Dashboard",
                description="Dashboard has zero worksheets. It may be unused or broken.",
                severity="Medium",
                rule_id="GOV-R003",
            ))

        # Rule GOV-R004: Zero calculated fields with many worksheets
        # (suggests raw data dump rather than analytical dashboard)
        if calc_fields_count == 0 and num_worksheets > 3:
            risks.append(RiskItem(
                risk_type="Raw Data Exposure",
                description=(
                    f"Dashboard has {num_worksheets} worksheets but zero calculated fields. "
                    f"This may be exposing raw data tables without analytical transformation."
                ),
                severity="Low",
                rule_id="GOV-R004",
            ))

        if not risks:
            risks.append(RiskItem(
                risk_type="Low Risk Profile",
                description="Dashboard complies with all design and structural governance thresholds.",
                severity="Low",
                rule_id="GOV-R000",
            ))

        return RiskAssessment(risks=risks)
