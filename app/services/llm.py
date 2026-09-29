"""LLM summary generation (Ollama via LangChain).

The model never sees raw rows. It gets the computed statistics as JSON, which
keeps prompts small, avoids leaking the whole file, and stops it inventing
numbers it can't see.
"""
import json

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from app.config import get_settings

PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are a senior business data analyst. Write the entire report in {language}, "
        "including every heading and bullet point. Keep column names and figures unchanged. "
        "Use ONLY the figures in the JSON you are given. Never invent numbers. "
        "If the data can't answer something, say so plainly.",
    ),
    (
        "human",
        "Statistics computed from an uploaded CSV file:\n\n{stats}\n\n"
        "Write a concise, professional report with these sections:\n"
        "1. Overview: what the data contains\n"
        "2. Key findings: the most important figures\n"
        "3. Trends: direction and period-over-period change, if a time series exists\n"
        "4. Data quality: issues and their impact\n"
        "5. Recommendations: 2-4 concrete next steps\n"
        "Use short bullet points and quote the actual figures.",
    ),
])


def generate_summary(stats: dict, language: str | None = None, model: str | None = None) -> str:
    settings = get_settings()
    llm = ChatOllama(
        model=model or settings.ollama_model,
        base_url=settings.ollama_base_url,
        temperature=0.2,
        client_kwargs={"timeout": settings.llm_timeout},
    )
    chain = PROMPT | llm | StrOutputParser()
    return chain.invoke({
        "language": language or settings.report_language,
        "stats": json.dumps(stats, ensure_ascii=False, indent=1),
    }).strip()
