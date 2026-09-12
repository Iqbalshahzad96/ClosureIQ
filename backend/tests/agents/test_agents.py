"""
AI Agents Structural Tests
"""

import asyncio
from app.agents.financial_review import FinancialReviewAgent
from app.agents.exception_analysis import ExceptionAnalysisAgent


def test_financial_review_agent_structure():
    agent = FinancialReviewAgent()
    assert agent.model_name == "gemini-1.5-pro"
    result = asyncio.run(agent.review_financial_summary(
        reconciliation_summary={"reconciled": True},
        context_policies=[]
    ))
    assert result["agent"] == "FinancialReviewAgent"
    assert result["status"] == "ready"


def test_exception_analysis_agent_structure():
    agent = ExceptionAnalysisAgent()
    assert agent.model_name == "gemini-1.5-pro"
    result = asyncio.run(agent.analyze_exception(
        exception_data={"id": "exc_01"},
        rag_policy_evidence=[]
    ))
    assert result["agent"] == "ExceptionAnalysisAgent"
    assert result["exception_id"] == "exc_01"
