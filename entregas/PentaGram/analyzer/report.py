"""Markdown and JSON rendering for the analyzer pipeline."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from deadlines import TIER_NOMES
from scoring import ScoredFindingGroup, rank_groups, score_priority_label


CONCEPT_GUIDANCE: dict[str, dict[str, str]] = {
    "dynamic_sql": {
        "description": "Construção de consultas SQL com dados dinâmicos em vez de parâmetros seguros.",
        "impact": "Pode permitir alteração indevida da consulta e exposição ou alteração de dados.",
        "recommendation": "Validar a origem dos valores e usar consultas parametrizadas ou APIs de composição segura.",
    },
    "hardcoded_secret": {
        "description": "Uma senha, credencial ou segredo aparece diretamente no código.",
        "impact": "O segredo pode ser exposto a qualquer pessoa com acesso ao repositório ou aos artefatos.",
        "recommendation": "Remover o valor do código, revogar o segredo quando aplicável e usar configuração segura.",
    },
    "weak_password_hash": {
        "description": "Uso de algoritmo de hash inadequado para proteger senhas.",
        "impact": "Senhas podem ficar mais suscetíveis a recuperação caso os dados armazenados sejam expostos.",
        "recommendation": "Validar o fluxo e migrar para um algoritmo de hash de senha resistente a ataques de força bruta.",
    },
    "missing_timeout": {
        "description": "Uma chamada externa não define limite explícito de tempo de espera.",
        "impact": "A operação pode ficar bloqueada e consumir recursos, afetando a disponibilidade do serviço.",
        "recommendation": "Definir timeouts adequados e tratar timeout, retry e falhas de forma controlada.",
    },
    "broad_exception": {
        "description": "O código captura uma classe ampla de exceções.",
        "impact": "Erros diferentes podem ser tratados da mesma forma e dificultar diagnóstico ou recuperação.",
        "recommendation": "Capturar exceções específicas e registrar ou propagar cada falha conforme o caso.",
    },
    "swallowed_exception": {
        "description": "Uma exceção é capturada sem tratamento ou sinalização suficiente.",
        "impact": "Falhas podem desaparecer silenciosamente e produzir comportamento incorreto difícil de investigar.",
        "recommendation": "Tratar a condição explicitamente, registrar contexto útil e preservar a sinalização do erro.",
    },
    "inconsistent_returns": {
        "description": "Um fluxo de função retorna valores diferentes ou não retorna em todos os caminhos.",
        "impact": "Chamadores podem receber resultados inesperados e precisar lidar com estados implícitos.",
        "recommendation": "Definir um contrato de retorno único e cobrir todos os caminhos de execução.",
    },
    "import_error": {
        "description": "A ferramenta não conseguiu resolver um import durante a análise.",
        "impact": "Pode indicar dependência ausente ou apenas uma diferença entre o ambiente da ferramenta e o ambiente de execução.",
        "recommendation": "Verificar o ambiente e as dependências antes de tratar o resultado como defeito confirmado.",
    },
    "cyclomatic_complexity": {
        "description": "A função ou método possui muitos caminhos condicionais de execução.",
        "impact": "Aumenta o esforço de entendimento, teste e manutenção do comportamento.",
        "recommendation": "Validar os caminhos e considerar decomposição em funções menores e coesas.",
    },
    "excessive_branches": {
        "description": "Uma função possui quantidade elevada de ramificações condicionais.",
        "impact": "Torna o fluxo mais difícil de testar e aumenta o risco de comportamento não coberto.",
        "recommendation": "Simplificar o fluxo ou separar responsabilidades em unidades menores.",
    },
    "excessive_returns": {
        "description": "Uma função possui muitos pontos de retorno.",
        "impact": "Pode dificultar a leitura do fluxo e a verificação de invariantes da função.",
        "recommendation": "Revisar o fluxo e reduzir saídas dispersas quando isso melhorar a clareza.",
    },
    "excessive_locals": {
        "description": "Uma função utiliza muitas variáveis locais.",
        "impact": "Indica concentração de responsabilidades e aumenta a carga cognitiva para manutenção.",
        "recommendation": "Revisar responsabilidades e extrair operações coesas quando apropriado.",
    },
    "unused_variable": {
        "description": "Uma variável atribuída não é utilizada posteriormente.",
        "impact": "Pode indicar lógica residual, erro de implementação ou intenção não expressa.",
        "recommendation": "Confirmar a intenção e remover a variável ou completar o uso necessário.",
    },
    "shadowed_builtin": {
        "description": "Um nome local sobrescreve o nome de uma função ou tipo embutido da linguagem.",
        "impact": "Pode confundir leitores e impedir o uso esperado da operação embutida naquele escopo.",
        "recommendation": "Renomear o identificador para preservar a clareza e o acesso à operação original.",
    },
    "unnecessary_else_after_return": {
        "description": "Um bloco else aparece depois de um caminho que já retorna.",
        "impact": "Adiciona aninhamento desnecessário e torna o fluxo mais difícil de ler.",
        "recommendation": "Remover o else quando equivalente e manter o caminho principal mais direto.",
    },
    "todo_comment": {
        "description": "Existe um comentário TODO indicando trabalho pendente no código.",
        "impact": "A pendência pode permanecer sem responsável, prazo ou decisão explícita.",
        "recommendation": "Avaliar a pendência, convertê-la em tarefa rastreável ou removê-la se não for mais necessária.",
    },
}

BUSINESS_CONTEXT: dict[str, str] = {
    "dynamic_sql": "Em uma SaaS B2B com cliente enterprise e avaliação de segurança próxima, uma consulta mal parametrizada pode aumentar o risco de incidente, perda de confiança ou impacto em dados de clientes.",
    "hardcoded_secret": "Na HourTrack, uma credencial exposta pode afetar integrações ou dados de clientes e elevar o risco durante o questionário de segurança empresarial.",
    "weak_password_hash": "Como a HourTrack processa dados de clientes, proteção inadequada de senhas pode comprometer confiança e dificultar a avaliação de segurança empresarial.",
    "missing_timeout": "Com equipe pequena e alterações diretamente em produção, chamadas sem limite de espera podem consumir recursos e dificultar a disponibilidade para dezenas de clientes.",
    "broad_exception": "Para uma equipe de apenas dois desenvolvedores full-stack, tratamento amplo pode esconder a origem de incidentes e aumentar o tempo de diagnóstico durante a release.",
    "swallowed_exception": "Falhas silenciosas podem afetar operações de uma SaaS sem alertar a equipe pequena, dificultando a continuidade do atendimento aos clientes.",
    "inconsistent_returns": "Contratos de retorno pouco claros aumentam o risco de comportamento inesperado em uma release urgente e tornam a saída do principal desenvolvedor mais difícil de absorver.",
    "import_error": "O resultado pode ser apenas ambiental; distinguir isso rapidamente evita gastar a janela de 14 dias da release em um problema que não ocorre no ambiente real.",
    "cyclomatic_complexity": "Complexidade elevada concentra conhecimento em poucos trechos, um risco relevante quando o principal desenvolvedor deixará a empresa em seis semanas.",
    "excessive_branches": "Fluxos muito ramificados aumentam o esforço de revisão e teste, especialmente sem staging e com uma release próxima.",
    "excessive_returns": "Muitos pontos de saída elevam a carga de entendimento para uma equipe pequena e podem tornar revisões urgentes menos previsíveis.",
    "excessive_locals": "Muitas variáveis locais podem sinalizar concentração de responsabilidade, dificultando a transferência de conhecimento antes da saída do principal desenvolvedor.",
    "unused_variable": "Resíduos de implementação aumentam ruído no código e consomem tempo de uma equipe pequena que precisa priorizar a release e o atendimento aos clientes.",
    "shadowed_builtin": "Nomes ambíguos aumentam o custo de revisão e manutenção em uma equipe pequena, sobretudo quando alterações são feitas diretamente em produção.",
    "unnecessary_else_after_return": "Aninhamento desnecessário reduz a clareza das revisões e pode consumir tempo limitado antes da release v2.1.",
    "todo_comment": "Pendências sem rastreamento podem sobreviver à release e à transição de conhecimento, aumentando o risco de manutenção futura.",
}


def _guidance_for(concept: str) -> dict[str, str]:
    guidance = CONCEPT_GUIDANCE.get(
        concept,
        {
            "description": "Resultado técnico identificado por uma ferramenta estática.",
            "impact": "O impacto depende da validação do contexto indicado no grupo.",
            "recommendation": "Revisar a ocorrência e confirmar a ação adequada antes de alterar o código.",
        },
    )
    return {
        **guidance,
        "technical_impact": guidance["impact"],
        "business_impact": BUSINESS_CONTEXT.get(
            concept,
            "O impacto de negócio depende da validação do contexto indicado no grupo.",
        ),
    }


def _result_payload(result: ScoredFindingGroup) -> dict[str, Any]:
    payload = result.to_dict()
    payload.update(_guidance_for(result.concept))
    return payload


def report_payload(results: list[ScoredFindingGroup]) -> dict[str, Any]:
    # Fonte única de ordenação: qualquer render sai na ordem de prioridade por
    # prazo, sem depender de quem chamou ter ordenado antes.
    ordered = rank_groups(results)
    distribution = Counter(result.priority for result in ordered)
    por_tier = Counter(result.deadline_tier for result in ordered)
    return {
        "summary": {
            "scored_groups": len(ordered),
            "critical": distribution["critical"],
            "high": distribution["high"],
            "medium": distribution["medium"],
            "low": distribution["low"],
            "without_priority": 0,
            "por_tier": {
                TIER_NOMES[tier]: por_tier.get(tier, 0) for tier in sorted(TIER_NOMES)
            },
        },
        "ordering_rule": (
            "Ordem lexicográfica (deadline_tier, -score, group_id). O tier vem "
            "primeiro para garantir que nenhum finding que não bloqueia o release "
            "de 14 dias fique acima de um que bloqueia. Dentro do tier do "
            "questionário o esforço domina: mais barato primeiro, porque concorre "
            "com o release pela mesma capacidade do time."
        ),
        "results": [_result_payload(result) for result in ordered],
    }


def render_json(results: list[ScoredFindingGroup]) -> str:
    return json.dumps(report_payload(results), ensure_ascii=False, indent=2) + "\n"


def render_markdown(results: list[ScoredFindingGroup]) -> str:
    payload = report_payload(results)
    summary = payload["summary"]
    ordered = rank_groups(results)
    category_counts = Counter(result.category for result in ordered)
    lines = [
        "# Radar de Débitos Técnicos — Relatório Determinístico",
        "",
        "## Resumo executivo",
        "",
        f"O pipeline consolidou **{summary['scored_groups']} grupos de débito** a partir das evidências dos analisadores. A distribuição atual é **{summary['critical']} critical**, **{summary['high']} high**, **{summary['medium']} medium** e **{summary['low']} low**.",
        "",
        f"A ordem é definida pelos dois prazos da empresa: **{summary['por_tier']['release+questionario']}** grupos bloqueiam o release de 14 dias *e* respondem o questionário de segurança de 30 dias, **{summary['por_tier']['release']}** apenas bloqueiam o release, **{summary['por_tier']['questionario']}** apenas respondem o questionário e **{summary['por_tier']['sem_prazo']}** não têm prazo associado.",
        "",
        f"As categorias mais representadas são maintainability ({category_counts['maintainability']}), security ({category_counts['security']}) e code_quality ({category_counts['code_quality']}). Para a HourTrack, os grupos high de segurança e disponibilidade merecem investigação antes da release v2.1: a empresa atende uma base B2B, tem equipe pequena, não possui staging e possui compromissos próximos de segurança empresarial.",
        "",
        "Cada linha detalhada representa um **grupo de débito**, isto é, uma ocorrência consolidada por conceito e localização. As evidências retidas em `evidence_count` e `source_tools` mostram os resultados das ferramentas que sustentam o grupo; elas não são novos débitos.",
        "",
        "## Principais riscos",
        "",
        "### Segurança",
        "Consultas SQL dinâmicas, credenciais no código e hash inadequado de senhas não comprovam exploração ou vazamento, mas podem indicar exposição de dados ou credenciais. Devem ser revisados antes do questionário de segurança empresarial, preservando a prioridade produzida pelo scoring.",
        "",
        "### Disponibilidade e confiabilidade",
        "Chamadas sem timeout e tratamentos de exceção amplos ou silenciosos podem dificultar a continuidade e o diagnóstico de falhas. Isso é especialmente relevante para uma equipe pequena que mantém uma SaaS sem staging e com alterações em produção.",
        "",
        "### Manutenção e qualidade",
        "Complexidade, branches, returns e outros sinais de qualidade aumentam o custo de teste e transferência de conhecimento. A saída do principal desenvolvedor torna essa revisão importante, mas a prioridade continua sendo a do motor determinístico.",
        "",
        "A ordem é produzida pelo motor determinístico e segue os prazos, não o score isolado: nenhum grupo que não bloqueia o release de 14 dias fica acima de um que bloqueia, qualquer que seja o score. Por isso a coluna de score pode parecer fora de ordem — ela ordena apenas dentro do mesmo prazo. Dentro do grupo do questionário o desempate é por esforço: o mais barato primeiro, porque concorre com o release pela mesma capacidade do time.",
        "",
        "## Principais problemas",
        "",
        "| Conceito | Problema | Impacto técnico | Impacto de negócio | Prioridade | Prazo | Score | Ferramentas |",
        "|---|---|---|---|---|---|---:|---|",
    ]
    by_concept: dict[str, list[ScoredFindingGroup]] = {}
    for result in ordered:
        by_concept.setdefault(result.concept, []).append(result)
    for concept, concept_results in sorted(
        by_concept.items(),
        key=lambda item: (
            min(entry.deadline_tier for entry in item[1]),
            -max(entry.score for entry in item[1]),
            item[0],
        ),
    ):
        representative = rank_groups(concept_results)[0]
        guidance = _guidance_for(concept)
        tools = sorted(
            {
                tool
                for item in concept_results
                for tool in item.factors.get("source_tools", [])
            }
        )
        lines.append(
            f"| {concept} | {guidance['description']} | {guidance['technical_impact']} | {guidance['business_impact']} | {representative.priority} | {TIER_NOMES[representative.deadline_tier]} | {representative.score:.2f} | {', '.join(tools) or 'não informado'} |"
        )
    lines.extend(
        [
            "",
            "## Plano de ação",
            "",
            "| Ordem | Prioridade | O que fazer | Por quê |",
            "|---:|---|---|---|",
            "| 1º | critical | Corrigir os grupos que estão no caminho do código do relatório **e** respondem o questionário: SQL dinâmico, credenciais no código e hash de senha. | O mesmo trabalho rende nos dois prazos — desbloqueia o release de 14 dias e já responde perguntas do questionário de 30 dias. |",
            "| 2º | high | Corrigir o que bloqueia o release mas não conta para o questionário: chamadas sem timeout e complexidade no caminho do relatório. | Sem isso a release v2.1 não sai, e dois clientes grandes ameaçaram cancelar se atrasar. |",
            "| 3º | medium | Responder o questionário na ordem apresentada, do mais barato para o mais caro. | A capacidade é de ~6 story points por semana e o release consome parte dela: o critério é quantas respostas se destravam por ponto gasto. |",
            "| 4º | low | Organizar exceções, branches, returns, variáveis e pendências em tarefas de manutenção. | Sem prazo associado. Reduz custo futuro e facilita a transferência de conhecimento antes da saída do dev principal. |",
            "",
            "Para cada grupo, confirmar a evidência, definir responsável e registrar a correção sem confundir ferramentas corroborantes com novos débitos.",
            "",
            "## Origem das recomendações",
            "",
            "As recomendações deste relatório são explicações determinísticas baseadas no conceito e nos resultados já produzidos pelas ferramentas. Elas não alteram categoria, prioridade, score ou quantidade de grupos. Uma camada opcional de IA generativa pode interpretar o `report.json`, mas não é necessária para gerar este relatório nem é fonte de verdade.",
            "",
            "## Como interpretar o scoring",
            "",
            "O score é produzido pelo motor determinístico com os pesos, notas, fórmula e fatores preservados no `report.json`. A prioridade scoring é derivada por limiares fixos e não é recalculada nesta apresentação. A Prioridade V1 é uma classificação qualitativa independente; quando os dois campos diferem, isso representa duas visões comparáveis, não uma alteração do resultado.",
            "",
            "## Limitações",
            "",
            "- A análise é estática e não executa o sistema.",
            "- Ferramentas estáticas podem produzir falsos positivos; cada evidência deve ser revisada no contexto.",
            "- O score e as prioridades são definidos pelo motor determinístico e não são recalculados na apresentação.",
            "- Resultados ambientais, como imports não resolvidos, podem refletir configuração do ambiente de análise.",
            "- O relatório não afirma que um problema foi explorado, que houve vazamento ou que causou incidente real.",
            "",
            "## Grupos e evidências",
            "",
            "A tabela abaixo mantém a rastreabilidade completa. `evidence_count` é a quantidade de evidências retidas no grupo e `source_tools` lista as ferramentas correspondentes.",
            "",
            "| # | Grupo | Conceito | Categoria | Prioridade | Prazo | Bloqueia release | Questionário | Esforço | Score | Evidências | Ferramentas |",
            "|---:|---|---|---|---|---|---|---|---:|---:|---:|---|",
        ]
    )
    for position, result in enumerate(ordered, start=1):
        factors = result.factors
        lines.append(
            "| {pos} | {group_id} | {concept} | {category} | {priority} | {prazo} "
            "| {release} | {questionario} | {esforco:g} | {score:.2f} | "
            "{evidence_count} | {tools} |".format(
                pos=position,
                group_id=result.group_id,
                concept=result.concept,
                category=result.category,
                priority=result.priority,
                prazo=TIER_NOMES[result.deadline_tier],
                release="sim" if result.blocks_release else "—",
                questionario=(
                    ", ".join(f"Q{item}" for item in result.questionnaire_items) or "—"
                ),
                esforco=result.esforco_pontos,
                score=result.score,
                evidence_count=factors.get("evidence_count", 0),
                tools=", ".join(factors.get("source_tools", [])) or "não informado",
            )
        )
    lines.extend(
        [
            "",
            "## Distribuição",
            "",
            f"- critical: {summary['critical']}",
            f"- high: {summary['high']}",
            f"- medium: {summary['medium']}",
            f"- low: {summary['low']}",
            "",
            "### Por prazo",
            "",
        ]
    )
    lines.extend(f"- {nome}: {total}" for nome, total in summary["por_tier"].items())
    lines.extend(["", "## Regra de ordenação", "", payload["ordering_rule"], ""])
    return "\n".join(lines)