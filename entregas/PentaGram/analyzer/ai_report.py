"""Gemini interpretation layer for the deterministic analyzer report."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

try:
    from google import genai
except ImportError:  # Keep deterministic pipeline usable without the optional SDK.
    genai = None

try:
    from dotenv import load_dotenv
except ImportError:  # Keep local execution usable before optional dependencies install.
    load_dotenv = None


MODEL_NAME = "gemini-3.5-flash-lite"


def generate_ai_report(report_path: Path, output_path: Path) -> Path:
    """Interpret an existing deterministic report and save a Markdown report.

    Only the parsed report JSON is sent to Gemini. The source repositories and
    detector JSONs never enter the prompt.
    """

    report = _load_report(report_path)
    _load_local_environment()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not configured; deterministic reports were preserved."
        )
    if genai is None:
        raise RuntimeError(
            "google-genai is not installed; deterministic reports were preserved."
        )

    prompt = _build_prompt(report)
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
    text = getattr(response, "text", None)
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("Gemini returned an empty response; deterministic reports were preserved.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return output_path


def _load_report(report_path: Path) -> dict[str, Any]:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read report JSON '{report_path}': {exc}") from exc
    if not isinstance(report, dict) or not isinstance(report.get("summary"), dict):
        raise ValueError("report.json must contain an object field named 'summary'.")
    if not isinstance(report.get("results"), list):
        raise ValueError("report.json must contain an array field named 'results'.")
    return report


def _load_local_environment() -> None:
    if load_dotenv is not None:
        load_dotenv()


def _build_prompt(report: dict[str, Any]) -> str:
    report_data = json.dumps(_prompt_report(report), ensure_ascii=False, indent=2)
    return f"""Você é um analista assistente do Radar de Débitos Técnicos da HourTrack Ltda.

Contexto empresarial:
- SaaS B2B de controle de horas faturáveis; 47 agências, aproximadamente 180 usuários e R$28 mil de MRR.
- Equipe de 8 pessoas, com 2 desenvolvedores full-stack; o principal desenvolvedor escreveu cerca de 90% do código e sai em 6 semanas.
- Release v2.1 em 14 dias e questionário de segurança de cliente enterprise em 30 dias.
- O cliente enterprise tem mais de 200 usuários e representa R$8 mil/mês; 3 clientes representam 60% da receita.
- Não existe staging, alterações são feitas diretamente em produção e SQLite está versionado no repositório.

Objetivo: apresentar os resultados já produzidos pelo Radar de Débitos Técnicos para uma apresentação de hackathon.

Regras obrigatórias:
- O JSON abaixo é a única fonte de verdade. Não crie findings e não invente fatos, arquivos, linhas, causas ou impactos comprovados.
- Preserve literalmente category, priority, deadline_tier, blocks_release, questionnaire_items, esforco_pontos, classification_priority, score, score_priority e score_priority_mapped.
- Não recalcule score nem altere prioridades. `priority` é a prioridade final: critical, high, medium ou low.
- NÃO REORDENE os findings. A ordem do array `results` é a decisão determinística do motor de priorização, não sugestão: prazo primeiro (tier 0 = bloqueia o release de 14 dias e responde o questionário; 1 = bloqueia o release; 2 = questionário; 3 = sem prazo) e, dentro do tier 2, esforço crescente. Apresente na ordem em que vierem.
- A coluna de score pode parecer fora de ordem: ela ordena apenas dentro do mesmo prazo. Não "corrija" isso nem sugira que é erro.
- Explique a prioridade de cada item pelo prazo que ele atende, usando o campo deadline_rationale. Não invente outra justificativa.
- Todos os resultados vêm de análise estática, sem execução do sistema. Descreva-os como evidências técnicas, sem transformar hipótese em fato.
- Ferramentas estáticas podem gerar falsos positivos. Não execute o sistema e não proponha novas detecções.
- Recomendações são interpretações dos dados existentes, não decisões do motor determinístico.

Escreva em português profissional, claro e específico, usando exatamente estes títulos:
# Radar de Débitos Técnicos — Análise Assistida por IA
## 1. Resumo executivo
## 2. Principais riscos
## 3. Segurança
## 4. Confiabilidade e disponibilidade
## 5. Manutenibilidade e qualidade
## 6. Priorização
Inclua uma tabela com ID/conceito, categoria, score e prioridades. Inclua ferramentas quando disponíveis em factors.source_tools.
## 7. Plano de ação
## 8. O que a IA sugeriu que estava errado, e por quê
Explique que a IA recebeu resultados de ferramentas estáticas e do motor determinístico e que não corrigiu nem criou findings.
## 9. Limitações
Inclua as limitações de análise estática, possíveis falsos positivos, resultados ambientais quando indicados pelos dados, motor determinístico e ausência de execução do sistema.

Dados agregados do report.json:
{report_data}
"""


def _prompt_report(report: dict[str, Any]) -> dict[str, Any]:
    """Keep the AI context focused on presentation-relevant report fields."""

    results = []
    for result in report["results"]:
        factors = result.get("factors", {})
        results.append(
            {
                "group_id": result.get("group_id"),
                "concept": result.get("concept"),
                "category": result.get("category"),
                "classification_priority": result.get("classification_priority"),
                # Campos de prazo: sem eles o Gemini nao tem como explicar a
                # ordem, e a priorizacao por deadline sumiria do relatorio.
                "priority": result.get("priority"),
                "deadline_tier": result.get("deadline_tier"),
                "blocks_release": result.get("blocks_release"),
                "questionnaire_items": result.get("questionnaire_items", []),
                "esforco_pontos": result.get("esforco_pontos"),
                "deadline_rationale": result.get("deadline_rationale"),
                "score": result.get("score"),
                "score_priority": result.get("score_priority"),
                "score_priority_mapped": result.get("score_priority_mapped"),
                "source_tools": factors.get("source_tools", []),
                "evidence_count": factors.get("evidence_count"),
            }
        )
    return {"summary": report["summary"], "results": results}