"""
Normalização: RawFinding[] -> Finding[].

Três operações, nesta ordem:

  1. Tradução via taxonomia   — "bandit:B608" vira "SEC.SQLI".
  2. Dedupe por local         — o mesmo problema visto por 2 ferramentas é
                                UM achado com 2 fontes, não dois achados.
  3. Agregação por padrão     — 6 SQL Injections em 4 arquivos viram UM débito
                                com 6 ocorrências.

A agregação é o que separa "pipeline" de "dump bruto de ferramenta" — que o
briefing penaliza explicitamente. O relatório é para alguém decidir alocação
de 6 story points por semana, não para listar linhas.
"""

from __future__ import annotations

from collections import defaultdict

from .config import BusinessProfile, Taxonomy
from .models import Category, Finding, Location, RawFinding, Severity


def normalize(
    raw: list[RawFinding],
    taxonomy: Taxonomy,
    profile: BusinessProfile,
) -> tuple[list[Finding], list[RawFinding], list[tuple[RawFinding, str]]]:
    """
    Devolve (findings canônicos, não mapeados, suprimidos).

    Os NÃO MAPEADOS são achados que nenhuma regra da taxonomia reconhece. Não
    recebem categoria genérica — seria inventar débito. Aparecem no JSON como
    `unmapped_findings`, para que a lacuna fique visível em vez de silenciosa.

    Os SUPRIMIDOS são achados de ferramenta que uma análise mais precisa
    determinou serem falso positivo, cada um com a justificativa escrita em
    `config/taxonomy.toml`. São reportados separadamente: suprimir em silêncio
    seria indistinguível de não detectar.
    """
    unmapped: list[RawFinding] = []
    suppressed: list[tuple[RawFinding, str]] = []
    # (rule_id, file, line) -> lista de RawFinding que apontam o mesmo ponto
    by_location: dict[tuple[str, str, int], list[RawFinding]] = defaultdict(list)

    suppressions = taxonomy.suppressions()

    for item in raw:
        rule_id = taxonomy.resolve(item.source, item.native_id)
        if rule_id is None or taxonomy.rule(rule_id) is None:
            unmapped.append(item)
            continue
        reason = suppressions.get((rule_id, item.file, item.line or 0))
        if reason is not None:
            suppressed.append((item, reason))
            continue
        by_location[(rule_id, item.file, item.line or 0)].append(item)

    # ---- Agregação por regra ----
    grouped: dict[str, list[tuple[tuple[str, int], list[RawFinding]]]] = defaultdict(list)
    for (rule_id, file, line), items in by_location.items():
        grouped[rule_id].append(((file, line), items))

    findings: list[Finding] = []
    for rule_id in sorted(grouped):
        spec = taxonomy.rule(rule_id)
        assert spec is not None  # garantido pelo filtro acima

        entries = sorted(grouped[rule_id], key=lambda kv: (kv[0][0], kv[0][1]))
        locations: list[Location] = []
        sources: set[str] = set()
        severity = Severity.parse(spec.severidade)

        for (file, line), items in entries:
            # Evidência: a primeira não-vazia, em ordem determinística.
            evidence = next(
                (i.evidence for i in sorted(items, key=lambda i: i.source) if i.evidence),
                "",
            )
            locations.append(Location(file=file, line=line or None, evidence=evidence))
            sources.update(i.source for i in items)
            # Severidade sobe se uma ferramenta reportou algo mais grave que a
            # base da regra, mas nunca desce: a base é o piso definido pelo
            # contexto do produto, não pela opinião da ferramenta.
            for i in items:
                if i.severity_hint is not None and i.severity_hint > severity:
                    severity = i.severity_hint

        findings.append(
            Finding(
                rule_id=rule_id,
                category=Category(spec.categoria),
                name=spec.nome,
                description=spec.descricao,
                severity=severity,
                locations=tuple(locations),
                effort_points=_scaled_effort(spec.esforco_sp, len(locations)),
                tags=_build_tags(rule_id, spec.tags, locations, profile),
                sources=tuple(sorted(sources)),
                remediation=spec.remediacao,
            )
        )

    findings.sort(key=lambda f: f.sort_key())
    unmapped.sort(key=lambda r: (r.source, r.file, r.line or 0, r.native_id))
    suppressed.sort(key=lambda kv: (kv[0].file, kv[0].line or 0, kv[0].source))
    return findings, unmapped, suppressed


def _scaled_effort(base_sp: float, occurrences: int) -> float:
    """
    Esforço do padrão, não da linha.

    Corrigir 6 SQL Injections não custa 6× corrigir uma: o trabalho é entender
    o padrão uma vez e aplicá-lo. Modelamos isso como um acréscimo decrescente
    sobre a base, com teto — um padrão espalhado custa mais, mas não linearmente.
    """
    if occurrences <= 1:
        return base_sp
    extra = min(occurrences - 1, 10) * 0.25
    return round(base_sp * (1 + extra / 2), 2)


def _build_tags(
    rule_id: str,
    base_tags: tuple[str, ...],
    locations: list[Location],
    profile: BusinessProfile,
) -> frozenset[str]:
    """
    Junta as tags da taxonomia com as derivadas do contexto de negócio.

    Estas tags são o acoplamento entre achado técnico e pressão de negócio —
    é o que permite ao scoring justificar prioridade em vez de só ordenar
    por severidade.
    """
    tags = set(base_tags)

    # Responde a alguma pergunta do questionário do cliente enterprise?
    for question in profile.questions_for_rule(rule_id):
        tags.add(f"questionario:{question}")

    # Está num arquivo que a release v2.1 vai tocar de qualquer forma?
    release_files = {f.lower() for f in profile.release_files()}
    if any(loc.file.lower() in release_files for loc in locations):
        tags.add("release-path")

    return frozenset(tags)
