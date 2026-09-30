"""
Modelo de dados normalizado do pipeline.

A razão de existir deste módulo: o scoring model precisa operar sem saber de
onde o achado veio. `RawFinding` é o que cada adapter (bandit, phpstan, AST
nativo) produz; `Finding` é o contrato canônico, independente de linguagem;
`ScoredFinding` é o resultado do scoring determinístico.

Nenhuma classe aqui faz I/O ou importa rede — é o núcleo puro do pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import IntEnum, StrEnum
from typing import Any


class Category(StrEnum):
    """Categorias exigidas pelo briefing (cenario-do-desafio.md)."""

    SECURITY = "Segurança"
    DESIGN = "Design"
    MAINTAINABILITY = "Manutenibilidade"
    PERFORMANCE = "Performance"
    ARCHITECTURE = "Arquitetura"


class Severity(IntEnum):
    """
    Severidade base do achado, ANTES do contexto de negócio.

    IntEnum (e não StrEnum) porque o scoring faz aritmética e comparação
    ordinal sobre este valor. Os nomes em português ficam em `label`.
    """

    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4

    @property
    def label(self) -> str:
        return {1: "Baixa", 2: "Média", 3: "Alta", 4: "Crítica"}[int(self)]

    @classmethod
    def parse(cls, value: str) -> "Severity":
        """Aceita as grafias das ferramentas externas (LOW/MEDIUM/HIGH/ERROR...)."""
        key = (value or "").strip().upper()
        table = {
            "LOW": cls.LOW,
            "INFO": cls.LOW,
            "INFORMATION": cls.LOW,
            "NOTE": cls.LOW,
            "CONVENTION": cls.LOW,
            "REFACTOR": cls.LOW,
            "MEDIUM": cls.MEDIUM,
            "WARNING": cls.MEDIUM,
            "MODERATE": cls.MEDIUM,
            "HIGH": cls.HIGH,
            "ERROR": cls.HIGH,
            "CRITICAL": cls.CRITICAL,
            "FATAL": cls.CRITICAL,
            "BLOCKER": cls.CRITICAL,
        }
        return table.get(key, cls.MEDIUM)


class Priority(StrEnum):
    """Saída do scoring — eixo 'quão importante'."""

    CRITICAL = "Crítica"
    HIGH = "Alta"
    MEDIUM = "Média"
    LOW = "Baixa"


class Window(StrEnum):
    """
    Saída do scoring — eixo 'quando'.

    Separado de `Priority` de propósito. A pergunta central do desafio é "o que
    faria primeiro e o que deixaria para depois"; um único eixo não consegue
    dizer "isto é crítico MAS não cabe antes da release v2.1".
    """

    PRE_RELEASE = "pre-release"          # cabe nos ~12 SP até a v2.1 (14 dias)
    SECURITY_SPRINT = "sprint-seguranca-30d"  # janela do questionário enterprise
    POST_RELEASE = "pos-v2.1"            # consciente e documentadamente adiado


# Regras verificadas por inspeção do repositório, e não por análise de código.
# Nenhuma ferramenta externa as reporta, então a ausência de corroboração não
# é sinal de nada (ver Finding.corroborable).
NON_CORROBORABLE_RULES = frozenset({
    "ARCH.NO_TESTS",
    "ARCH.GOD_MODULE",
    "ARCH.NO_API_VERSIONING",
    "SEC.COMMITTED_SECRET_FILE",
})


@dataclass(frozen=True)
class Location:
    """Um local concreto onde o padrão foi detectado."""

    file: str          # SEMPRE relativo ao repo — determinismo entre máquinas
    line: int | None = None
    evidence: str = ""

    def __str__(self) -> str:
        return f"{self.file}:{self.line}" if self.line else self.file


@dataclass(frozen=True)
class RawFinding:
    """
    Saída bruta de um detector, antes da taxonomia.

    `native_id` é o identificador na ferramenta de origem (B608, W0612,
    'formatted-sql-query'). A normalização traduz isso para um `rule_id`
    canônico via config/taxonomy.toml.
    """

    source: str                 # "bandit", "native-ast", "phpstan"
    native_id: str
    message: str
    file: str
    line: int | None = None
    severity_hint: Severity | None = None
    evidence: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Finding:
    """
    O contrato canônico. O scoring model só conhece esta estrutura.

    Agregado: um `Finding` representa um PADRÃO (ex.: "SQL Injection por
    interpolação"), não uma linha. As N linhas onde ele ocorre ficam em
    `locations`. Isso é o que separa um relatório de um dump de linter.
    """

    rule_id: str                       # canônico: "SEC.SQLI", nunca "B608"
    category: Category
    name: str
    description: str
    severity: Severity
    locations: tuple[Location, ...]
    effort_points: float               # story points; time entrega ~6 SP/semana
    tags: frozenset[str] = frozenset()
    sources: tuple[str, ...] = ()      # ferramentas que corroboraram
    remediation: str = ""

    @property
    def occurrences(self) -> int:
        return len(self.locations)

    @property
    def primary_location(self) -> Location | None:
        return self.locations[0] if self.locations else None

    @property
    def corroborated(self) -> bool:
        """Visto por 2+ ferramentas independentes — reduz risco de falso positivo."""
        return len(set(self.sources)) >= 2

    @property
    def corroborable(self) -> bool:
        """
        Se faz sentido esperar que OUTRA ferramenta confirme este achado.

        Achados de propriedade do repositório — ausência de testes, banco
        commitado, módulo monolítico — são verificados por inspeção do
        sistema de arquivos, e nenhum linter tem opinião sobre eles. Aplicar
        desconto de confiança a eles puniria o achado por uma corroboração
        que é impossível por construção, não por ele ser duvidoso.
        """
        return self.rule_id not in NON_CORROBORABLE_RULES

    def sort_key(self) -> tuple:
        """Chave TOTAL para ordenação estável (determinismo)."""
        loc = self.primary_location
        return (self.rule_id, loc.file if loc else "", loc.line or 0 if loc else 0)


@dataclass(frozen=True)
class ScoreComponent:
    """
    Uma parcela do score, preservada para o relatório.

    O briefing exige regras 'explícitas e justificáveis'. Guardar cada parcela
    com sua justificativa torna o score auditável linha a linha, em vez de um
    número mágico no fim.
    """

    rule: str            # identificador da regra de scoring
    kind: str            # "base" | "multiplier" | "bonus" | "penalty"
    value: float         # multiplicador (1.8) ou parcela aditiva (+25)
    rationale: str       # por que o contexto de negócio justifica isto


@dataclass(frozen=True)
class ScoredFinding:
    """Finding + resultado determinístico do scoring."""

    id: str                            # "DT-01", atribuído após a ordenação final
    finding: Finding
    score: int
    priority: Priority
    window: Window
    risk: str                          # Alto / Médio / Baixo
    components: tuple[ScoreComponent, ...]
    business_impact: str = ""          # narrativa (template ou LLM)
    impact_source: str = "template"    # "template" | "llm" — auditabilidade

    # Delegações de conveniência para o renderer não cavar em .finding.*
    @property
    def category(self) -> Category:
        return self.finding.category

    @property
    def name(self) -> str:
        return self.finding.name

    def with_impact(self, text: str, source: str) -> "ScoredFinding":
        return replace(self, business_impact=text, impact_source=source)
