"""Mapeamento explícito e determinístico entre findings e os prazos da HourTrack.

Os dois prazos vêm de ``docs/business-context.md`` e ``docs/cenario-do-desafio.md``:

- **Release v2.1 em 14 dias** — "nova funcionalidade de relatório por projeto", já
  prometida a 3 clientes grandes; dois ameaçaram cancelar o contrato se atrasar.
- **Questionário de segurança em 30 dias** — cliente enterprise de 200+ usuários e
  R$ 8.000/mês, que dobra o MRR atual se fechar.

A priorização resultante é **lexicográfica**: o tier decide primeiro e o score só
ordena dentro do tier. É o que garante que nenhum finding que não bloqueia o release
fique acima de um que bloqueia, qualquer que seja o score. Um multiplicador não daria
essa garantia: a faixa de score do motor é de ~960x, então o multiplicador teria de
passar disso e o score viraria decoração.

Este módulo é deliberadamente puro — recebe ``concept`` e ``file_path``, não importa
nada do pipeline — para poder ser testado isolado.
"""

from __future__ import annotations

from pathlib import PurePosixPath


# Caminho do código que o release v2.1 precisa modificar.
#
# Levantado seguindo os imports a partir da rota de relatório no alvo:
#
#   app/routes/report_routes.py  (ReportController.monthly)
#     └── app/services/billing_service.py  (BillingService)
#           ├── app/services/notification_service.py
#           └── app/helpers/date_helper.py  (handle_date, CC=29)
#
# app/everything.py entra porque expõe /api/report (linha 210) que monthly()
# duplica — o comentário no próprio alvo diz "Duplica everything.report() com
# pequenas diferenças que criam inconsistência". Entregar um relatório novo
# obriga a encarar essa duplicação.
RELEASE_PATH_SUFFIXES: tuple[str, ...] = (
    "app/routes/report_routes.py",
    "app/services/billing_service.py",
    "app/services/notification_service.py",
    "app/helpers/date_helper.py",
    "app/everything.py",
)

# Conceitos que bloqueiam o release onde quer que estejam. A justificativa é o
# ambiente descrito no business-context: sem staging, sem cobertura de testes e
# deploy = `git pull` em produção. Um erro de correctness aí impede subir.
RELEASE_BLOCKING_CONCEPTS = frozenset(
    {
        "import_error",
        "inconsistent_returns",
    }
)

# Conceitos que nunca bloqueiam um release, onde quer que estejam.
#
# Estar no arquivo que o release vai mexer não é a mesma coisa que impedir o
# release: ninguém segura uma entrega prometida a 3 clientes por causa de um
# `# TODO` ou de uma variável não usada. Sem esta lista, qualquer lint cosmético
# dentro de app/everything.py (que é o monolito com dashboard, save e delete,
# além da rota de relatório) entraria no tier 1 e passaria na frente de
# vulnerabilidade real -- e o briefing desconta ponto por falso positivo.
NEVER_BLOCKS_RELEASE = frozenset(
    {
        "todo_comment",
        "unused_variable",
        "shadowed_builtin",
        "unnecessary_else_after_return",
    }
)

# Conceito -> perguntas que ele destrava em docs/security-questionnaire.md.
# O número serve de rastreabilidade: o relatório consegue dizer qual resposta do
# questionário cada finding libera.
QUESTIONNAIRE_CONCEPTS: dict[str, tuple[int, ...]] = {
    "dynamic_sql": (1,),           # Q1 — proteção contra SQL Injection
    "weak_password_hash": (3, 7),  # Q3 — hash seguro; Q7 — sem MD5/SHA-1
    "hardcoded_secret": (4,),      # Q4 — credenciais fora do código-fonte
    "debug_enabled": (6,),         # Q6 — debug desativado em produção
}


TIER_RELEASE_E_QUESTIONARIO = 0
TIER_RELEASE = 1
TIER_QUESTIONARIO = 2
TIER_SEM_PRAZO = 3

TIER_NOMES: dict[int, str] = {
    TIER_RELEASE_E_QUESTIONARIO: "release+questionario",
    TIER_RELEASE: "release",
    TIER_QUESTIONARIO: "questionario",
    TIER_SEM_PRAZO: "sem_prazo",
}


def is_in_release_path(file_path: str | None) -> bool:
    """Diz se o arquivo está no caminho que o release v2.1 precisa mexer.

    O casamento é por **sufixo de path normalizado**, nunca por igualdade. O
    ``file_path`` que as ferramentas devolvem depende de como foram invocadas:
    ``/repos/python/app/everything.py`` dentro do container (ver
    ``docs/ferramentas.md``) mas ``app/everything.py`` se rodadas da raiz do alvo.
    Comparar por igualdade faria ``blocks_release()`` devolver ``False`` para tudo,
    em silêncio, e o sistema de tiers inteiro pararia de funcionar sem erro nenhum.
    """

    if not file_path:
        return False
    normalized = PurePosixPath(file_path.replace("\\", "/")).as_posix()
    return any(
        normalized == suffix or normalized.endswith("/" + suffix)
        for suffix in RELEASE_PATH_SUFFIXES
    )


def blocks_release(concept: str, file_path: str | None) -> bool:
    """Bloqueia o release por estar no caminho dele ou por ser correctness.

    Conceitos cosméticos (ver ``NEVER_BLOCKS_RELEASE``) nunca bloqueiam, mesmo
    dentro do caminho do relatório.
    """

    if concept in NEVER_BLOCKS_RELEASE:
        return False
    return concept in RELEASE_BLOCKING_CONCEPTS or is_in_release_path(file_path)


def questionnaire_items(concept: str) -> tuple[int, ...]:
    """Perguntas do questionário de segurança que este conceito destrava."""

    return QUESTIONNAIRE_CONCEPTS.get(concept, ())


def deadline_tier(concept: str, file_path: str | None) -> int:
    """Tier de prazo: 0 = release+questionário, 1 = release, 2 = questionário, 3 = nenhum."""

    blocks = blocks_release(concept, file_path)
    in_questionnaire = bool(questionnaire_items(concept))
    if blocks and in_questionnaire:
        return TIER_RELEASE_E_QUESTIONARIO
    if blocks:
        return TIER_RELEASE
    if in_questionnaire:
        return TIER_QUESTIONARIO
    return TIER_SEM_PRAZO


def tier_label(tier: int, score: float, high_threshold: float) -> str:
    """Rótulo de prioridade derivado do tier.

    O rótulo conta a mesma história que a ordem: quem está acima na lista tem
    prioridade mais alta. ``high_threshold`` é recebido por parâmetro para este
    módulo não depender de ``scoring``.
    """

    if tier == TIER_RELEASE_E_QUESTIONARIO:
        return "critical"
    if tier == TIER_RELEASE:
        return "high"
    if tier == TIER_QUESTIONARIO:
        return "medium"
    return "medium" if score > high_threshold else "low"


def tier_rationale(concept: str, file_path: str | None) -> str:
    """Justificativa legível do tier, para a coluna de prioridade do relatório."""

    tier = deadline_tier(concept, file_path)
    items = questionnaire_items(concept)
    perguntas = ", ".join(f"Q{item}" for item in items)

    if tier == TIER_RELEASE_E_QUESTIONARIO:
        return (
            f"Bloqueia o release de 14 dias ({_motivo_release(concept, file_path)}) "
            f"e responde {perguntas} do questionário de 30 dias."
        )
    if tier == TIER_RELEASE:
        return (
            f"Bloqueia o release de 14 dias ({_motivo_release(concept, file_path)}); "
            "fora do questionário de segurança."
        )
    if tier == TIER_QUESTIONARIO:
        return (
            f"Responde {perguntas} do questionário de 30 dias; fora do caminho do "
            "release. Ordenado por esforço: o mais barato primeiro, porque concorre "
            "com o release pela mesma capacidade do time."
        )
    return "Sem prazo associado; ordenado apenas pelo score de gravidade."


def _motivo_release(concept: str, file_path: str | None) -> str:
    if concept in RELEASE_BLOCKING_CONCEPTS:
        return f"conceito '{concept}' impede build/deploy"
    return "está no caminho do código do relatório"
