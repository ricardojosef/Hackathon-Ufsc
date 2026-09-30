"""
Scoring model determinístico.

═══════════════════════════════════════════════════════════════════════
 CONTRATO DE DETERMINISMO
═══════════════════════════════════════════════════════════════════════
Este módulo:
  - não faz I/O, não abre rede, não lê relógio (`datetime.now()` é proibido);
  - não itera sobre `set` sem ordenar;
  - usa `Decimal` com quantização explícita, nunca float acumulado;
  - recebe os prazos como DIAS RESTANTES vindos de business_profile.toml,
    e não de calendário — rodar amanhã dá o mesmo resultado.

Rodado duas vezes no mesmo repositório, produz bytes idênticos. O briefing
desclassifica scoring não-determinístico como entrega técnica.

═══════════════════════════════════════════════════════════════════════
 A FÓRMULA
═══════════════════════════════════════════════════════════════════════

    score = base(severidade) × Π(multiplicadores) + Σ(bônus) − penalidade_esforço

Cada parcela é registrada em `ScoreComponent` com sua justificativa, de modo
que o relatório consegue mostrar POR QUE cada item ficou onde ficou.

═══════════════════════════════════════════════════════════════════════
 AS REGRAS E SUA JUSTIFICATIVA NO CONTEXTO DA HOURTRACK
═══════════════════════════════════════════════════════════════════════

BASE — severidade técnica do achado, antes do negócio:
    CRÍTICA 100 | ALTA 60 | MÉDIA 30 | BAIXA 10

MULTIPLICADORES (compõem entre si):

  questionario (×1.8) — Segurança que responde a uma das 7 perguntas do
      cliente enterprise. Prazo de 30 dias, contrato de R$8.000/mês que
      DOBRA o MRR de R$28.000. Cada "Não" exige plano de remediação. É a
      maior alavanca de receita disponível ao time hoje.

  multi_tenant (×1.6) — Permite ler ou apagar dado de outro cliente. O
      business-context registra que "os clientes não sabem que qualquer
      usuário pode ver e deletar dados de qualquer outro cliente" e que
      vazamento "poderia gerar processo". Risco existencial, não técnico.

  release_path (×1.4) — O arquivo já será modificado pela v2.1 em 14 dias.
      O custo marginal de corrigir junto é muito menor que o de uma
      intervenção dedicada, e sem staging cada deploy extra é risco.

  corroboracao (×1.15) — Duas ou mais ferramentas independentes apontaram o
      mesmo ponto. Falso positivo desconta pontos no desafio; corroboração
      é evidência direta contra isso.

  fonte_unica_nao_seguranca (×0.9) — Achado não-Segurança visto por uma só
      ferramenta. Desconto de confiança simétrico ao anterior. NÃO se aplica
      a achados não-corroboráveis (ausência de testes, banco commitado): ali
      a falta de uma segunda fonte não é sinal de dúvida, é característica do
      que está sendo medido.

BÔNUS (aditivos, aplicados após os multiplicadores):

  bus_factor (+25) — O dev que escreveu 90% do código sai em 6 semanas.
      Conhecimento tácito preso em função de CC 29 sem nenhum teste evapora
      junto com ele. Esta janela fecha e não reabre.

  sistemico (+20) — 3 ou mais ocorrências: é padrão da base de código, não
      incidente isolado. Some o mesmo erro em toda parte e a chance de um
      deles ser explorado cresce junto.

  data_loss (+20) — Pode destruir dados. Sem backup, sem staging, banco
      SQLite versionado no repo: não existe caminho de volta.

PENALIDADE DE ESFORÇO — a única regra que REDUZ prioridade:

  A capacidade real é 6 SP/semana. Até a release v2.1 (14 dias) há ~12 SP,
  e ela não pode atrasar — dois clientes ameaçaram cancelar. Item caro
  compete diretamente com uma entrega já prometida.

      penalidade = 0            se esforço ≤ 3 SP
      penalidade = (esforço−3)×4, com TETO de 35

  O teto é deliberado e é a decisão mais contestável do modelo. Sem ele, um
  item de 13 SP perderia para trivialidades e o modelo recomendaria arrumar
  variável não usada antes de SQL Injection. Com ele, esforço nunca zera um
  achado crítico: SQL Injection continua Crítica mesmo custando 13 SP.

  O que o esforço muda de fato é a JANELA, não a prioridade — por isso a
  saída tem dois eixos (ver `Window`).

CORTES DE PRIORIDADE:
    ≥ 140 Crítica | ≥ 90 Alta | ≥ 50 Média | < 50 Baixa

═══════════════════════════════════════════════════════════════════════
 O SEGUNDO EIXO: A JANELA (quando fazer)
═══════════════════════════════════════════════════════════════════════
Prioridade diz QUÃO importante; janela diz QUANDO cabe. São independentes
de propósito — "Crítico mas não cabe antes da release" é informação útil,
não contradição. Regras, na ordem de avaliação:

  pre-release          — relevante (score ≥ 90) e ≤ 3 SP: cabe nos ~12 SP
                         disponíveis até a v2.1.
  sprint-seguranca-30d — responde ao questionário; OU é Crítico e caro
                         demais para a release; OU é Segurança barata
                         (≤ 3 SP) que o cliente enterprise vai auditar.
  pos-v2.1             — o resto: adiado de forma consciente e registrada.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from .config import BusinessProfile
from .models import (
    Category,
    Finding,
    Priority,
    ScoreComponent,
    ScoredFinding,
    Severity,
    Window,
)

# ── Constantes do modelo ────────────────────────────────────────────────
# Todas nomeadas e reunidas aqui para que auditar o modelo seja ler um bloco.

BASE_BY_SEVERITY: dict[Severity, int] = {
    Severity.CRITICAL: 100,
    Severity.HIGH: 60,
    Severity.MEDIUM: 30,
    Severity.LOW: 10,
}

MULT_QUESTIONARIO = Decimal("1.8")
MULT_MULTI_TENANT = Decimal("1.6")
MULT_RELEASE_PATH = Decimal("1.4")
MULT_CORROBORADO = Decimal("1.15")
MULT_FONTE_UNICA = Decimal("0.9")

BONUS_BUS_FACTOR = 25
BONUS_SISTEMICO = 20
BONUS_DATA_LOSS = 20

SISTEMICO_MIN_OCORRENCIAS = 3

EFFORT_FREE_SP = Decimal("3")
EFFORT_PENALTY_PER_SP = Decimal("4")
EFFORT_PENALTY_CAP = Decimal("35")

THRESHOLD_CRITICA = 140
THRESHOLD_ALTA = 90
THRESHOLD_MEDIA = 50

# Um achado abaixo deste esforço é "barato o bastante para caber antes da
# release", desde que seja relevante. Equivale a meio dia de um dev.
PRE_RELEASE_MAX_SP = Decimal("3")


def score_finding(finding: Finding, profile: BusinessProfile) -> ScoredFinding:
    """Pontua UM achado. Puro: mesma entrada, mesma saída, sempre."""
    components: list[ScoreComponent] = []

    # ── 1. Base ──────────────────────────────────────────────────────
    base = BASE_BY_SEVERITY[finding.severity]
    components.append(
        ScoreComponent(
            rule="base_severidade",
            kind="base",
            value=float(base),
            rationale=f"Severidade técnica {finding.severity.label} do achado.",
        )
    )
    value = Decimal(base)

    # ── 2. Multiplicadores de contexto ───────────────────────────────
    questionario = sorted(t for t in finding.tags if t.startswith("questionario:"))
    if questionario and finding.category is Category.SECURITY:
        qids = ", ".join(q.split(":", 1)[1] for q in questionario)
        prazo = profile.questionario_prazo
        value *= MULT_QUESTIONARIO
        components.append(
            ScoreComponent(
                rule="questionario_seguranca",
                kind="multiplier",
                value=float(MULT_QUESTIONARIO),
                rationale=(
                    f"Responde à(s) pergunta(s) {qids} do questionário do cliente "
                    f"enterprise (prazo {prazo.get('dias_restantes', 30)} dias, "
                    f"R$ {prazo.get('contrato_mensal_brl', 8000)}/mês — dobra o MRR). "
                    "Hoje a resposta honesta é 'Não'."
                ),
            )
        )

    if "multi-tenant" in finding.tags:
        value *= MULT_MULTI_TENANT
        components.append(
            ScoreComponent(
                rule="isolamento_multi_tenant",
                kind="multiplier",
                value=float(MULT_MULTI_TENANT),
                rationale=(
                    "Permite acessar ou alterar dados de outro cliente. Os 47 clientes "
                    "compartilham a mesma base sem isolamento e não sabem disso; "
                    "vazamento de dados de contrato pode gerar processo."
                ),
            )
        )

    if "release-path" in finding.tags:
        value *= MULT_RELEASE_PATH
        components.append(
            ScoreComponent(
                rule="caminho_da_release",
                kind="multiplier",
                value=float(MULT_RELEASE_PATH),
                rationale=(
                    "Está em arquivo que a release v2.1 já vai modificar em "
                    f"{profile.release.get('dias_restantes', 14)} dias — corrigir junto "
                    "custa muito menos que uma intervenção dedicada, e evita um "
                    "deploy extra num ambiente sem staging."
                ),
            )
        )

    if finding.corroborated:
        value *= MULT_CORROBORADO
        components.append(
            ScoreComponent(
                rule="corroboracao",
                kind="multiplier",
                value=float(MULT_CORROBORADO),
                rationale=(
                    "Confirmado independentemente por: "
                    + ", ".join(sorted(set(finding.sources)))
                    + " — baixa probabilidade de falso positivo."
                ),
            )
        )
    elif finding.category is not Category.SECURITY and finding.corroborable:
        # O desconto só vale quando OUTRA ferramenta poderia ter confirmado.
        # Achados de propriedade do repositório (ausência de testes, banco
        # commitado) não são corroboráveis por construção — descontá-los seria
        # puni-los por uma evidência que não existe para ninguém.
        value *= MULT_FONTE_UNICA
        components.append(
            ScoreComponent(
                rule="fonte_unica_nao_seguranca",
                kind="multiplier",
                value=float(MULT_FONTE_UNICA),
                rationale=(
                    "Reportado por uma única ferramenta e fora de Segurança — "
                    "desconto de confiança para não inflar a lista."
                ),
            )
        )

    # ── 3. Bônus aditivos ────────────────────────────────────────────
    if "bus-factor" in finding.tags:
        semanas = profile.time.get("saida_dev_principal_semanas", 6)
        value += BONUS_BUS_FACTOR
        components.append(
            ScoreComponent(
                rule="bus_factor",
                kind="bonus",
                value=float(BONUS_BUS_FACTOR),
                rationale=(
                    f"O dev que escreveu 90% do código sai em {semanas} semanas. "
                    "Conhecimento preso neste ponto sai junto — a janela para "
                    "documentar ou cobrir com teste fecha e não reabre."
                ),
            )
        )

    if finding.occurrences >= SISTEMICO_MIN_OCORRENCIAS:
        value += BONUS_SISTEMICO
        components.append(
            ScoreComponent(
                rule="padrao_sistemico",
                kind="bonus",
                value=float(BONUS_SISTEMICO),
                rationale=(
                    f"{finding.occurrences} ocorrências em "
                    f"{len({loc.file for loc in finding.locations})} arquivo(s): é padrão "
                    "da base de código, não caso isolado."
                ),
            )
        )

    if "data-loss" in finding.tags:
        value += BONUS_DATA_LOSS
        components.append(
            ScoreComponent(
                rule="risco_perda_de_dados",
                kind="bonus",
                value=float(BONUS_DATA_LOSS),
                rationale=(
                    "Pode destruir dados, e não há backup, staging nem monitoramento — "
                    "a empresa descobriria pelo cliente, sem caminho de volta."
                ),
            )
        )

    # ── 4. Penalidade de esforço ─────────────────────────────────────
    effort = Decimal(str(finding.effort_points))
    if effort > EFFORT_FREE_SP:
        raw_penalty = (effort - EFFORT_FREE_SP) * EFFORT_PENALTY_PER_SP
        penalty = min(raw_penalty, EFFORT_PENALTY_CAP)
        value -= penalty
        capped = " (teto aplicado)" if raw_penalty > EFFORT_PENALTY_CAP else ""
        components.append(
            ScoreComponent(
                rule="penalidade_esforco",
                kind="penalty",
                value=-float(penalty),
                rationale=(
                    f"Custa {finding.effort_points} SP de uma capacidade de "
                    f"{profile.time.get('capacidade_sp_semana', 6)} SP/semana; restam "
                    f"~{profile.release.get('orcamento_sp', 12)} SP até a release v2.1, "
                    f"que não pode atrasar{capped}."
                ),
            )
        )

    score = int(max(Decimal(0), value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    return ScoredFinding(
        id="",  # atribuído em `score_all`, após a ordenação final
        finding=finding,
        score=score,
        priority=_priority_for(score),
        window=_window_for(finding, score),
        risk=_risk_for(finding),
        components=tuple(components),
    )


def score_all(findings: list[Finding], profile: BusinessProfile) -> list[ScoredFinding]:
    """
    Pontua e ordena todos os achados, atribuindo os IDs DT-NN.

    A ordenação usa chave TOTAL — `(-score, rule_id, arquivo, linha)`. Empate
    em score nunca cai na ordem de descoberta, que dependeria do sistema de
    arquivos. É o que garante que DT-01 seja sempre o mesmo item.
    """
    scored = [score_finding(f, profile) for f in findings]
    scored.sort(key=lambda s: (-s.score, *s.finding.sort_key()))

    width = max(2, len(str(len(scored))))
    return [
        ScoredFinding(
            id=f"DT-{str(idx).zfill(width)}",
            finding=s.finding,
            score=s.score,
            priority=s.priority,
            window=s.window,
            risk=s.risk,
            components=s.components,
            business_impact=s.business_impact,
            impact_source=s.impact_source,
        )
        for idx, s in enumerate(scored, start=1)
    ]


def _priority_for(score: int) -> Priority:
    if score >= THRESHOLD_CRITICA:
        return Priority.CRITICAL
    if score >= THRESHOLD_ALTA:
        return Priority.HIGH
    if score >= THRESHOLD_MEDIA:
        return Priority.MEDIUM
    return Priority.LOW


def _window_for(finding: Finding, score: int) -> Window:
    """
    Quando fazer — eixo independente da prioridade.

    Responde diretamente à pergunta central do desafio ("o que faria primeiro
    e o que deixaria para depois"). Um item pode ser Crítico e mesmo assim
    não caber antes da release: isso é informação, não contradição.
    """
    effort = Decimal(str(finding.effort_points))
    relevante = score >= THRESHOLD_ALTA

    # Barato e relevante: cabe no orçamento de ~12 SP até a v2.1.
    if relevante and effort <= PRE_RELEASE_MAX_SP:
        return Window.PRE_RELEASE

    # Responde ao questionário: tem prazo próprio de 30 dias e receita atrelada.
    if any(t.startswith("questionario:") for t in finding.tags):
        return Window.SECURITY_SPRINT

    # Caro demais para a release, mas ainda crítico: entra no sprint de
    # segurança, que tem o dobro do orçamento.
    if score >= THRESHOLD_CRITICA:
        return Window.SECURITY_SPRINT

    # Correção de segurança barata: mesmo sem responder a uma pergunta do
    # questionário, o cliente enterprise vai auditar o código. Um item de
    # Segurança que custa ≤ 3 SP não tem por que esperar o pós-release.
    if finding.category is Category.SECURITY and effort <= PRE_RELEASE_MAX_SP:
        return Window.SECURITY_SPRINT

    return Window.POST_RELEASE


def describe_model() -> dict[str, object]:
    """
    Descreve o modelo a partir das CONSTANTES reais do módulo.

    O relatório renderiza esta estrutura em vez de repetir os números num
    texto paralelo. Assim a documentação das regras não pode ficar
    desatualizada em relação ao código — mudar uma constante muda o relatório.
    """
    return {
        "deterministic": True,
        "uses_llm_for_priority": False,
        "formula": (
            "score = base(severidade) × Π(multiplicadores) "
            "+ Σ(bônus) − penalidade_esforço"
        ),
        "base_by_severity": {
            sev.label: points for sev, points in sorted(BASE_BY_SEVERITY.items(), reverse=True)
        },
        "thresholds": {
            "Crítica": THRESHOLD_CRITICA,
            "Alta": THRESHOLD_ALTA,
            "Média": THRESHOLD_MEDIA,
        },
        "rules": [
            {
                "rule": "questionario_seguranca",
                "effect": f"×{MULT_QUESTIONARIO}",
                "rationale": (
                    "Achado de Segurança que responde a uma das 7 perguntas do cliente "
                    "enterprise. Prazo de 30 dias, contrato que dobra o MRR."
                ),
            },
            {
                "rule": "isolamento_multi_tenant",
                "effect": f"×{MULT_MULTI_TENANT}",
                "rationale": (
                    "Permite ler ou apagar dados de outro cliente. 47 clientes na mesma "
                    "base sem isolamento; vazamento de dados de contrato gera exposição "
                    "jurídica."
                ),
            },
            {
                "rule": "caminho_da_release",
                "effect": f"×{MULT_RELEASE_PATH}",
                "rationale": (
                    "Arquivo que a v2.1 já vai modificar em 14 dias — custo marginal de "
                    "corrigir junto é baixo e evita um deploy extra sem staging."
                ),
            },
            {
                "rule": "corroboracao",
                "effect": f"×{MULT_CORROBORADO}",
                "rationale": (
                    "Confirmado por 2+ ferramentas independentes: evidência direta "
                    "contra falso positivo, que é penalizado no desafio."
                ),
            },
            {
                "rule": "fonte_unica_nao_seguranca",
                "effect": f"×{MULT_FONTE_UNICA}",
                "rationale": (
                    "Achado não-Segurança visto por uma só ferramenta, quando outra "
                    "poderia tê-lo confirmado. Desconto de confiança."
                ),
            },
            {
                "rule": "bus_factor",
                "effect": f"+{BONUS_BUS_FACTOR}",
                "rationale": (
                    "O dev que escreveu 90% do código sai em 6 semanas; o conhecimento "
                    "preso neste ponto sai junto. A janela fecha e não reabre."
                ),
            },
            {
                "rule": "padrao_sistemico",
                "effect": f"+{BONUS_SISTEMICO}",
                "rationale": (
                    f"{SISTEMICO_MIN_OCORRENCIAS}+ ocorrências: é padrão da base de "
                    "código, não incidente isolado."
                ),
            },
            {
                "rule": "risco_perda_de_dados",
                "effect": f"+{BONUS_DATA_LOSS}",
                "rationale": (
                    "Pode destruir dados, e não há backup, staging nem monitoramento — "
                    "não existe caminho de volta."
                ),
            },
            {
                "rule": "penalidade_esforco",
                "effect": (
                    f"−(SP−{EFFORT_FREE_SP})×{EFFORT_PENALTY_PER_SP}, "
                    f"teto {EFFORT_PENALTY_CAP}"
                ),
                "rationale": (
                    "Item caro compete com a release v2.1, que não pode atrasar. O teto "
                    "é deliberado: esforço muda a JANELA, não a prioridade — SQL "
                    "Injection continua Crítica mesmo custando 13 SP."
                ),
            },
        ],
    }


def _risk_for(finding: Finding) -> str:
    """
    Risco = probabilidade de o problema se manifestar (campo exigido pelo
    briefing), distinto de impacto.

    Alta severidade com muitas ocorrências e superfície exposta é quase certo;
    um smell interno de baixa severidade pode nunca incomodar ninguém.
    """
    exposto = bool(
        finding.tags & {"auth", "multi-tenant", "pii"}
    ) or finding.category is Category.SECURITY

    if finding.severity >= Severity.CRITICAL and exposto:
        return "Alto"
    if finding.severity >= Severity.HIGH and (exposto or finding.occurrences >= 3):
        return "Alto"
    if finding.severity >= Severity.HIGH or finding.occurrences >= 3:
        return "Médio"
    if finding.severity is Severity.MEDIUM:
        return "Médio"
    return "Baixo"
