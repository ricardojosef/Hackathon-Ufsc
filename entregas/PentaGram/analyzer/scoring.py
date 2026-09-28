"""Deterministic quantitative scoring for classified finding groups."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from classification import ClassifiedFindingGroup
from models import FindingKind
from deadlines import (
    blocks_release,
    deadline_tier,
    questionnaire_items,
    tier_label,
    tier_rationale,
)


# ====================================================================
# ⚠️ EQUIPE: MUDAR AQUI (PESOS DA EMPRESA) ⚠️
# Estes são os pesos globais. Ajustem conforme a estratégia de vocês.
# ====================================================================
PESOS_AGRAVANTES: dict[str, float] = {
    "financeiro": 2.0, #1.0,
    "seguranca": 3.0, #2.5,
    "aumento_problema": 1.0, #1.2,
    "imagem_empresa": 1.5,
    "emocional": 0.5, #0,8,
}

# Parâmetros mortos removidos. O único atenuante real é o esforço.
PESOS_ATENUANTES: dict[str, float] = {
    "tempo": 1.0, # Esse peso pode ficar em 1.0, a variação acontece na nota do problema
}

# Esforço estimado por conceito, em story points.
#
# Substitui o "tempo" fixo por bucket: a granularidade por conceito é o que
# permite ordenar DENTRO do tier do questionário (barato primeiro). Com um tempo
# único por categoria, todos os itens de segurança empatariam.
#
# Calibrado contra a capacidade real do business-context: 2 devs, ~6 pontos por
# semana (reuniões, suporte e bugs consomem ~40%).
ESFORCO_BY_CONCEPT: dict[str, float] = {
    "debug_enabled": 0.5,               # remover debug=True de run.py
    "missing_timeout": 0.5,             # acrescentar timeout= na chamada
    "unnecessary_else_after_return": 0.5,
    "unused_variable": 0.5,
    "shadowed_builtin": 0.5,
    "todo_comment": 0.5,
    "import_error": 0.5,                # instalar dep ou corrigir o import
    "hardcoded_secret": 1.0,            # mover para variável de ambiente
    "swallowed_exception": 1.0,
    "broad_exception": 1.0,
    "dynamic_sql": 2.0,                 # parametrizar a query
    "inconsistent_returns": 2.0,
    "excessive_returns": 2.0,
    "excessive_locals": 2.0,
    "excessive_branches": 3.0,
    "weak_password_hash": 3.0,          # trocar hash + migrar senhas existentes
    "cyclomatic_complexity": 5.0,       # refatorar função grande sem rede de testes
}
ESFORCO_DEFAULT = 2.0

# Expoente do esforço por tier.
#
# Um FATOR constante por tier não serviria de nada: como o tier é a chave
# primária da ordenação, multiplicar todos os scores de um tier pela mesma
# constante escala tudo igualmente e não reordena nada (A/2 vs B/2 tem a mesma
# ordem que A vs B). O expoente sim -- ele muda o trade-off entre gravidade e
# custo, porque A1/E1**k vs A2/E2**k troca de vencedor conforme k.
#
# Tiers 0 e 1 vão ser feitos de todo jeito para desbloquear o release, então o
# esforço só sequencia. O tier 2 (questionário) concorre com o release pela
# mesma capacidade do time, então ali o esforço domina: barato primeiro.
EXPOENTE_ESFORCO_POR_TIER: dict[int, float] = {
    0: 0.5,
    1: 0.5,
    2: 1.5,
    3: 1.0,
}

LIMIAR_ALTO = 300.0
LIMIAR_MEDIO = 200.0

# debug_enabled entra aqui porque debug ligado em produção vaza stack trace e
# habilita o debugger do Werkzeug (execução remota) -- não é ruído de config.
_SECURITY_CONCEPTS = {
    "dynamic_sql",
    "hardcoded_secret",
    "weak_password_hash",
    "debug_enabled",
}


@dataclass(frozen=True)
class ScoredFindingGroup:
    """Serializable scoring result layered on top of Classification V1."""
    group_id: str
    concept: str
    category: str
    classification_priority: str | None
    priority: str
    deadline_tier: int
    blocks_release: bool
    questionnaire_items: tuple[int, ...]
    esforco_pontos: float
    deadline_rationale: str
    score: float
    score_priority: str
    score_priority_mapped: str
    notes: dict[str, float]
    formula: str
    factors: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "concept": self.concept,
            "category": self.category,
            "classification_priority": self.classification_priority,
            "priority": self.priority,
            "deadline_tier": self.deadline_tier,
            "blocks_release": self.blocks_release,
            "questionnaire_items": list(self.questionnaire_items),
            "esforco_pontos": self.esforco_pontos,
            "deadline_rationale": self.deadline_rationale,
            "score": self.score,
            "score_priority": self.score_priority,
            "score_priority_mapped": self.score_priority_mapped,
            "notes": self.notes,
            "formula": self.formula,
            "factors": self.factors,
        }


def calculate_score(classified_group: ClassifiedFindingGroup) -> ScoredFindingGroup:
    """Calculate one deterministic score without changing the V1 result."""

    notes = notes_for_group(classified_group)
    
    peso_sev = peso_severidade(classified_group.group.representative_finding)
    aggravating_product = peso_sev * _product(
        notes.get(name, 1.0) * weight
        for name, weight in PESOS_AGRAVANTES.items()
    )
    
    # Agora pega a nota de 'tempo' que veio dinamicamente, em vez de chumbar 1.0
    mitigating_product = _product(
        notes.get(name, 1.0) * weight
        for name, weight in PESOS_ATENUANTES.items()
    )
    
    if mitigating_product == 0:
        mitigating_product = 0.0001

    score = aggravating_product / mitigating_product
    score_priority = _priority_for_score(score)
    finding = classified_group.group.representative_finding
    concept = classified_group.concept
    tier = deadline_tier(concept, finding.file_path)
    esforco = esforco_pontos(concept)
    group_id = _group_id(classified_group)
    formula = (
        "product(note * aggravating_weight) / product(note * mitigating_weight), "
        "com tempo = esforco_pontos ** expoente_do_tier"
    )
    factors = {
        "aggravating_weights": dict(PESOS_AGRAVANTES),
        "mitigating_weights": dict(PESOS_ATENUANTES),
        "aggravating_product": aggravating_product,
        "mitigating_product": mitigating_product,
        "native_severity": finding.severity,
        "peso_severidade": peso_sev,
        "source_tools": classified_group.group.source_tools,
        "evidence_count": len(classified_group.group.evidences),
        "effort": notes.get("tempo", 1.0), # Salva o esforço no relatório
        "esforco_pontos": esforco,
        "expoente_esforco": EXPOENTE_ESFORCO_POR_TIER[tier],
    }
    return ScoredFindingGroup(
        group_id=group_id,
        concept=classified_group.concept,
        category=classified_group.category,
        classification_priority=classified_group.priority,
        priority=tier_label(tier, score, LIMIAR_ALTO),
        deadline_tier=tier,
        blocks_release=blocks_release(concept, finding.file_path),
        questionnaire_items=questionnaire_items(concept),
        esforco_pontos=esforco,
        deadline_rationale=tier_rationale(concept, finding.file_path),
        score=score,
        score_priority=score_priority,
        score_priority_mapped=score_priority_label(score_priority),
        notes=notes,
        formula=formula,
        factors=factors,
    )


def score_groups(
    classified_groups: list[ClassifiedFindingGroup],
) -> list[ScoredFindingGroup]:
    return [calculate_score(group) for group in classified_groups]


def rank_groups(scored: list[ScoredFindingGroup]) -> list[ScoredFindingGroup]:
    """Ordena pela regra de priorização por prazo.

    Chave lexicográfica: ``(deadline_tier, -score, group_id)``.

    - ``deadline_tier`` primeiro é o que **garante** a regra: nenhum finding que
      não bloqueia o release fica acima de um que bloqueia, qualquer que seja o
      score. Nenhum ajuste de peso consegue dar essa garantia -- a faixa de score
      do motor é de centenas de vezes.
    - ``group_id`` como desempate final é obrigatório, não cosmético: existem
      scores que colidem exatamente. Sem ele a ordem dependeria da ordem de
      entrada, e scoring não determinístico é desclassificação pelo briefing.
    """

    return sorted(
        scored,
        key=lambda item: (item.deadline_tier, -item.score, item.group_id),
    )


def esforco_pontos(concept: str) -> float:
    """Esforço estimado em story points, com default explícito."""

    return ESFORCO_BY_CONCEPT.get(concept, ESFORCO_DEFAULT)


def notes_for_group(classified_group: ClassifiedFindingGroup) -> dict[str, float]:
    concept = classified_group.concept
    category = classified_group.category
    finding = classified_group.group.representative_finding
    tier = deadline_tier(concept, finding.file_path)

    # ====================================================================
    # ⚠️ EQUIPE: MUDAR AS NOTAS AQUI (DE 1.0 A 5.0) ⚠️
    # As notas são a política de risco do time, em estado bruto. A severidade
    # da ferramenta é aplicada depois, UMA vez sobre o produto, em
    # peso_severidade() -- aplicá-la aqui nota por nota a comprimia a
    # peso ** 5 e engolia o esforço.
    # ====================================================================
    
    if concept in _SECURITY_CONCEPTS or category == "security":
        notes = {
            "financeiro": 5.0,
            "seguranca": 5.0,
            "aumento_problema": 4.0,
            "imagem_empresa": 4.0,
            "emocional": 1.0,
        }
        # tempo vem de ESFORCO_BY_CONCEPT (ver _tempo_de_esforco)

    elif concept == "cyclomatic_complexity" or category == "maintainability":
        notes = {
            "financeiro": 1.0,
            "seguranca": 1.0,
            "aumento_problema": 4.0,
            "imagem_empresa": 1.0,
            "emocional": 5.0,
        }
        # tempo vem de ESFORCO_BY_CONCEPT (cyclomatic_complexity = 5 pontos)

    elif category == "availability":
        # VPS única, sem monitoramento, sem staging: o business-context diz que
        # "clientes avisam quando cai". Indisponibilidade é perda de receita
        # direta e queima de imagem imediata.
        notes = {
            "financeiro": 3.0,
            "seguranca": 1.0,
            "aumento_problema": 3.0,
            "imagem_empresa": 4.0,
            "emocional": 3.0,
        }

    elif category == "reliability":
        notes = {
            "financeiro": 2.0,
            "seguranca": 1.0,
            "aumento_problema": 4.0,
            "imagem_empresa": 3.0,
            "emocional": 2.0,
        }

    elif category == "environmental":
        # Environmental geralmente não afeta o cliente real
        notes = {
            "financeiro": 1.0,
            "seguranca": 1.0,
            "aumento_problema": 2.0,
            "imagem_empresa": 1.0,
            "emocional": 2.0,
        }

    else:
        # Code Quality e outros
        notes = {
            "financeiro": 1.0,
            "seguranca": 1.0,
            "aumento_problema": 2.0,
            "imagem_empresa": 1.0,
            "emocional": 2.0,
        }

    # O atenuante "tempo" é o esforço estimado do conceito, já elevado ao
    # expoente do tier -- é o que faz o tier do questionário sair do mais
    # barato para o mais caro.
    return {
        "tempo": _tempo_de_esforco(concept, tier),
        **notes,
    }


def _tempo_de_esforco(concept: str, tier: int) -> float:
    return esforco_pontos(concept) ** EXPOENTE_ESFORCO_POR_TIER[tier]


def peso_severidade(finding) -> float:
    """Multiplicador de severidade, aplicado UMA vez sobre o produto agravante.

    Aplicar por nota comprimia o peso a ``peso ** 5`` (faixa de 3125x entre HIGH
    e LOW), o que engolia o esforço e desmontava a ordenação dentro do tier. Uma
    aplicação só deixa a faixa em ~3x, e o esforço volta a decidir.

    O despacho é por tipo de achado porque as escalas não são comparáveis: o
    bandit fala HIGH/MEDIUM/LOW, o pylint fala error/warning/refactor e o radon
    devolve um rank cuja escala é INVERTIDA (A é o melhor, F o pior).
    """

    if finding.kind == FindingKind.METRIC:
        return _peso_metrica(finding)
    return _peso_severidade_nativa(finding.severity)


def _peso_metrica(finding) -> float:
    """Peso de uma métrica pela magnitude, não pela letra do rank.

    Usa ``metric_value`` (a complexidade ciclomática em si) contra os limiares de
    ``docs/ferramentas.md``: 11-15 complexa, 16-20 refatorar, 21+ muito alta.

    O rank do radon não serve como severidade: a escala é invertida (A = simples,
    F = inalterável sem reescrita), então mapeá-lo como severidade fazia a função
    MAIS complexa pontuar MENOS -- media 3800x ao contrário.
    """

    valor = finding.metric_value or 0
    if valor >= 21:
        return 1.0
    if valor >= 16:
        return 0.8
    if valor >= 11:
        return 0.6
    return 0.2


def _peso_severidade_nativa(severity: str | None) -> float:
    """Severidade textual das ferramentas de achado (bandit, semgrep, pylint)."""

    sev = str(severity or "").upper()
    if sev in {"HIGH", "CRITICAL", "ERROR", "FATAL"}:
        return 1.0
    if sev in {"MEDIUM", "WARNING"}:
        return 0.6
    if sev in {"LOW", "INFO", "INFORMATIONAL", "REFACTOR", "CONVENTION"}:
        return 0.3
    # Severidade ausente ou desconhecida é neutra: não temos base para punir.
    return 0.6


def _priority_for_score(score: float) -> str:
    if score > LIMIAR_ALTO:
        return "alto"
    if score > LIMIAR_MEDIO:
        return "medio"
    return "baixo"


def score_priority_label(score_priority: str) -> str:
    return {"alto": "high", "medio": "medium", "baixo": "low"}[score_priority]


def _group_id(classified_group: ClassifiedFindingGroup) -> str:
    finding = classified_group.group.representative_finding
    location = f"{finding.file_path or '<unknown>'}:{finding.line or 0}"
    return f"{classified_group.concept}@{location}"


def _product(values: Any) -> float:
    result = 1.0
    for value in values:
        result *= value
    return result
