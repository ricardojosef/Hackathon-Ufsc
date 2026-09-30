"""
Time de agentes (framework agno) sobre o Radar de Débitos Técnicos.

    python agent_radar.py /repos/python
    python agent_radar.py /caminho/absoluto/do/repo --model gemini-2.5-flash

Dois agentes em ciclo de revisão:

    Relator   — chama a tool `pontuar_repositorio` (scoring determinístico do
                pipeline) e redige o relatório em Markdown.
    Revisor   — confronta o Markdown com os dados brutos da mesma tool e
                devolve APROVADO ou REPROVADO com as correções exigidas.

A tool é a fronteira que mantém o time honesto: a prioridade continua vindo de
`analyzer/scoring.py`, que é determinístico e não conhece LLM. Os agentes
redigem e revisam texto — não calculam score, prioridade, esforço ou janela.

Este módulo é a última etapa do pipeline (ver `analyzer/main.py`): coleta,
normalização e scoring continuam 100% determinísticos e sem LLM; só a
redação e a revisão do relatório passam pelo time de agentes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from agno.agent import Agent
from agno.knowledge.embedder.google import GeminiEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.google import Gemini
from agno.team import Team
from agno.team.mode import TeamMode
from agno.tools import tool
from agno.vectordb.chroma import ChromaDb
from agno.vectordb.search import SearchType

from analyzer.config import load_business_profile, load_taxonomy
from analyzer.detectors.registry import collect, detect_language
from analyzer.normalize import normalize
from analyzer.scoring import describe_model, score_all

DEFAULT_MODEL = "gemini-2.5-flash"
EMBEDDER_ID = "gemini-embedding-001"


# ══════════════════════════════════════════════════════════════════════
#  A TOOL — scoring determinístico exposto ao agente
# ══════════════════════════════════════════════════════════════════════


@tool(
    name="pontuar_repositorio",
    description=(
        "Executa o pipeline determinístico do Radar de Débitos Técnicos sobre um "
        "repositório e devolve os débitos já pontuados e priorizados. Esta é a "
        "ÚNICA fonte válida de score, prioridade e esforço."
    ),
    cache_results=True,
)
def pontuar_repositorio(repo: str, incluir_externas: bool = True) -> str:
    """
    Analisa um repositório e devolve o resultado do scoring determinístico.

    Roda as quatro primeiras etapas do pipeline (coleta -> normalização ->
    scoring -> montagem do documento) e devolve JSON. A etapa de redação fica
    com o agente, que é justamente o que esta função NÃO faz: ela não escreve
    narrativa, só computa números auditáveis.

    Args:
        repo (str): Caminho absoluto do repositório a analisar.
        incluir_externas (bool): Usa bandit/radon/pylint/phpstan além dos
            detectores nativos. Padrão True.

    Returns:
        str: JSON com summary, findings (cada um com id, score, prioridade,
             janela, esforço e os componentes que explicam o score),
             questionário de segurança e plano de remediação em 3 ondas.
    """
    repo_path = Path(repo).resolve()
    if not repo_path.is_dir():
        return json.dumps(
            {"erro": f"`{repo}` não é um diretório acessível."}, ensure_ascii=False
        )

    language = detect_language(repo_path)
    if language == "unknown":
        return json.dumps(
            {"erro": f"Não foi possível detectar a linguagem de `{repo}`."},
            ensure_ascii=False,
        )

    taxonomy = load_taxonomy()
    profile = load_business_profile()

    detection = collect(repo_path, language=language, use_external=incluir_externas)
    findings, unmapped, suppressed = normalize(detection.raw_findings, taxonomy, profile)
    scored = score_all(findings, profile)

    doc = _build_doc(
        scored,
        repo=repo_path,
        language=detection.language,
        profile=profile,
        tools_available=detection.tools_available,
        tool_counts=detection.tool_counts,
        tool_errors=detection.tool_errors,
        unmapped=unmapped,
        suppressed=suppressed,
    )
    return json.dumps(doc, ensure_ascii=False, indent=2)


def _build_doc(
    scored,
    *,
    repo: Path,
    language: str,
    profile,
    tools_available: dict,
    tool_counts: dict,
    tool_errors: dict,
    unmapped,
    suppressed,
) -> dict:
    """
    Documento que a tool devolve ao agente — dados puros, sem narrativa.

    Deliberadamente sem timestamp (determinismo) e sem texto redigido: quem
    escreve a narrativa é o Relator, não esta função.
    """
    by_priority: dict[str, int] = {}
    for s in scored:
        by_priority[s.priority.value] = by_priority.get(s.priority.value, 0) + 1

    nao = []
    for qid in sorted(profile.questionario):
        entry = profile.questionario[qid]
        rules = set(entry.get("regras", []))
        hits = [s for s in scored if s.finding.rule_id in rules]
        nao.append(
            {
                "id": qid,
                "pergunta": entry.get("pergunta", ""),
                "resposta_real": "Não" if hits else "Sim",
                "evidencias": [s.id for s in hits],
            }
        )

    return {
        "repository": {"path": repo.name, "language": language},
        "environment": {
            "tools_available": dict(sorted(tools_available.items())),
            "raw_findings_by_tool": dict(sorted(tool_counts.items())),
            "tool_errors": dict(sorted(tool_errors.items())),
        },
        "business_context": {
            "empresa": profile.empresa.get("nome"),
            "mrr_brl": profile.empresa.get("mrr_brl"),
            "capacidade_sp_semana": profile.time.get("capacidade_sp_semana"),
            "release_v21_dias": profile.release.get("dias_restantes"),
            "questionario_dias": profile.questionario_prazo.get("dias_restantes"),
            "questionario_contrato_brl": profile.questionario_prazo.get("contrato_mensal_brl"),
        },
        "scoring_model": describe_model(),
        "summary": {
            "total_debitos": len(scored),
            "total_ocorrencias": sum(s.finding.occurrences for s in scored),
            "esforco_total_sp": round(sum(s.finding.effort_points for s in scored), 2),
            "por_prioridade": by_priority,
        },
        "security_questionnaire": nao,
        "findings": [
            {
                "id": s.id,
                "rule_id": s.finding.rule_id,
                "categoria": s.finding.category.value,
                "nome": s.finding.name,
                "descricao": s.finding.description,
                "risco": s.risk,
                "esforco_sp": s.finding.effort_points,
                "prioridade": s.priority.value,
                "janela": s.window.value,
                "score": s.score,
                "severidade_base": s.finding.severity.label,
                "ocorrencias": s.finding.occurrences,
                "tags": sorted(s.finding.tags),
                "fontes": list(s.finding.sources),
                "corroborado": s.finding.corroborated,
                "remediacao": s.finding.remediation,
                "locais": [
                    {"arquivo": loc.file, "linha": loc.line, "trecho": loc.evidence}
                    for loc in s.finding.locations
                ],
                "score_components": [
                    {"rule": c.rule, "kind": c.kind, "value": c.value, "rationale": c.rationale}
                    for c in s.components
                ],
            }
            for s in scored
        ],
        "unmapped_findings": [
            {"source": u.source, "native_id": u.native_id, "file": u.file, "line": u.line}
            for u in unmapped
        ],
        "suppressed_findings": [
            {"source": item.source, "file": item.file, "motivo": reason}
            for item, reason in suppressed
        ],
    }


# ══════════════════════════════════════════════════════════════════════
#  Knowledge (RAG) — os arquivos do próprio projeto
# ══════════════════════════════════════════════════════════════════════


def build_knowledge(project_dir: Path, db_path: Path) -> Knowledge:
    """
    Indexa o código do projeto para que os agentes possam consultá-lo.

    O revisor precisa disso: para julgar se o relatório condiz com as falhas
    reais, ele tem que conseguir ler o código-fonte, não só o JSON da tool.
    """
    knowledge = Knowledge(
        vector_db=ChromaDb(
            collection="radar-debitos",
            path=str(db_path),
            persistent_client=True,
            search_type=SearchType.hybrid,
            embedder=GeminiEmbedder(id=EMBEDDER_ID),
        ),
    )
    knowledge.insert(path=str(project_dir))
    return knowledge


# ══════════════════════════════════════════════════════════════════════
#  Os agentes
# ══════════════════════════════════════════════════════════════════════


def build_relator(model_id: str, knowledge: Knowledge) -> Agent:
    return Agent(
        name="Relator",
        role="Gera o relatório de débitos técnicos em Markdown",
        model=Gemini(id=model_id),
        tools=[pontuar_repositorio],
        knowledge=knowledge,
        search_knowledge=True,
        markdown=True,
        instructions=[
            "SEMPRE execute a tool `pontuar_repositorio` antes de escrever "
            "qualquer coisa. Ela é obrigatória, mesmo que você ache que já sabe "
            "a resposta ou que já a executou numa rodada anterior.",
            "NUNCA invente, estime ou ajuste score, prioridade, esforço ou "
            "janela. Esses valores vêm exclusivamente da tool — se não estão no "
            "retorno dela, não entram no relatório.",
            "Seu trabalho é redigir, não calcular. A tool computa; você explica "
            "em linguagem de negócio o que ela computou.",
            "Responda SEMPRE em Markdown, com esta estrutura: título, sumário "
            "executivo, tabela dos débitos (ID, Categoria, Nome, Risco, Esforço, "
            "Prioridade, Score), uma seção por débito e o plano em 3 ondas.",
            "Cite arquivo e linha de cada débito, usando os campos `locais` do "
            "retorno da tool.",
            "Se o Revisor devolver correções, refaça o relatório atendendo cada "
            "ponto — rode a tool de novo para reconferir os números.",
        ],
    )


def build_revisor(model_id: str, knowledge: Knowledge) -> Agent:
    return Agent(
        name="Revisor",
        role="Audita o relatório contra o código e os dados da tool",
        model=Gemini(id=model_id),
        tools=[pontuar_repositorio],
        knowledge=knowledge,
        search_knowledge=True,
        markdown=True,
        instructions=[
            "Você recebe um relatório em Markdown e precisa decidir se ele "
            "condiz com as falhas reais do código.",
            "Execute `pontuar_repositorio` para obter os números corretos e "
            "consulte a base de conhecimento para ler o código-fonte citado.",
            "Verifique: (1) todo débito do relatório existe no retorno da tool; "
            "(2) score, prioridade, esforço e janela batem exatamente; "
            "(3) arquivos e linhas citados existem no código; "
            "(4) nenhum débito Crítico ou Alto foi omitido; "
            "(5) o relatório não inventou débito que a tool não reportou.",
            "Comece sua resposta com APROVADO ou REPROVADO na primeira linha.",
            "Se REPROVADO, liste cada divergência como um item acionável: o que "
            "está escrito, o que deveria estar, e onde. Sem correção vaga.",
            "Não reescreva o relatório você mesmo — seu papel é apontar, o do "
            "Relator é corrigir.",
        ],
    )


def build_team(knowledge: Knowledge, model_id: str = DEFAULT_MODEL) -> Team:
    return Team(
        name="Radar de Débitos Técnicos",
        members=[build_relator(model_id, knowledge), build_revisor(model_id, knowledge)],
        model=Gemini(id=model_id),
        mode=TeamMode.tasks,
        max_iterations=6,
        markdown=True,
        instructions=[
            "Fluxo obrigatório, nesta ordem:",
            "1. Delegue ao Relator a geração do relatório em Markdown.",
            "2. Delegue ao Revisor a auditoria desse relatório.",
            "3. Se o Revisor responder REPROVADO, devolva as correções ao "
            "Relator e repita a partir do passo 2.",
            "4. Só encerre quando o Revisor responder APROVADO.",
            "Sua resposta final deve ser o relatório Markdown aprovado, "
            "completo e sem comentários do processo de revisão.",
        ],
    )


# ══════════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════════


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent_radar",
        description=(
            "Time de agentes agno que gera e audita o relatório de débitos "
            "técnicos. O scoring continua determinístico — os agentes só "
            "redigem e revisam."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "exemplos:\n"
            "  python agent_radar.py /repos/python\n"
            "  python agent_radar.py /repos/php --model gemini-2.5-pro\n"
            "  python agent_radar.py /repos/python --out relatorio.md\n"
        ),
    )
    parser.add_argument("repo", type=Path, help="caminho absoluto do repositório a analisar")
    parser.add_argument(
        "--model", default=DEFAULT_MODEL,
        help=f"modelo Gemini usado pelos agentes (padrão: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--knowledge-dir", type=Path, default=Path(__file__).parent / "analyzer",
        help="diretório indexado como base de conhecimento (padrão: ./analyzer)",
    )
    parser.add_argument(
        "--db-path", type=Path, default=Path("tmp/chromadb"),
        help="diretório do banco vetorial ChromaDB (padrão: tmp/chromadb)",
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help="grava o relatório aprovado neste arquivo além de imprimi-lo",
    )
    parser.add_argument(
        "--stream", action="store_true",
        help="imprime a resposta em streaming em vez de esperar o resultado final",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not os.environ.get("GOOGLE_API_KEY", "").strip():
        print(
            "erro: GOOGLE_API_KEY não definida.\n"
            "  export GOOGLE_API_KEY='sua-chave'   (obtenha em aistudio.google.com)",
            file=sys.stderr,
        )
        return 2

    repo = args.repo.resolve()
    if not repo.is_dir():
        print(f"erro: `{args.repo}` não é um diretório.", file=sys.stderr)
        return 2

    knowledge = build_knowledge(args.knowledge_dir.resolve(), args.db_path)
    team = build_team(args.model, knowledge)

    prompt = (
        f"Gere o relatório de débitos técnicos do repositório `{repo}`.\n\n"
        "O Relator deve rodar a tool `pontuar_repositorio` com "
        f"repo='{repo}' e redigir o Markdown. O Revisor então audita o "
        "resultado contra o código e os dados da tool. Repitam até APROVADO."
    )

    if args.stream:
        team.print_response(prompt, stream=True, show_member_responses=True)
        return 0

    response = team.run(prompt)
    print(response.content)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(response.content, encoding="utf-8")
        print(f"\nrelatório gravado em: {args.out}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
