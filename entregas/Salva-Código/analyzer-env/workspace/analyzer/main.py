"""
Entry point do pipeline.

    python -m analyzer <caminho-do-repo> [opções]

Orquestra três etapas determinísticas, depois entrega ao time de agentes:

    coletar  ->  normalizar  ->  pontuar  ->  redigir+revisar (agent_radar)
    (detectores) (taxonomia)   (determinístico)   (agno: Relator + Revisor)

A redação e a revisão do relatório NÃO fazem parte deste módulo: são feitas
por `agent_radar.py`, que recebe os achados já pontuados e nunca recalcula
score, prioridade ou ordem — só os lê pela tool `pontuar_repositorio`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import load_business_profile, load_taxonomy
from .detectors.registry import collect, detect_language
from .scoring import score_all


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="analyzer",
        description=(
            "Radar de Débitos Técnicos — analisa um repositório, normaliza os "
            "achados e os prioriza com um scoring determinístico baseado no "
            "contexto de negócio."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "exemplos:\n"
            "  python -m analyzer ./bad-codebase-python\n"
            "  python -m analyzer ./bad-codebase-python --no-external\n"
            "  python -m analyzer ./bad-codebase --skip-report\n"
        ),
    )
    parser.add_argument("repo", type=Path, help="caminho do repositório a analisar")
    parser.add_argument(
        "--language", choices=("python", "php"), default=None,
        help="força a linguagem em vez de detectar automaticamente",
    )
    parser.add_argument(
        "--no-external", action="store_true",
        help=(
            "ignora bandit/radon/pylint/phpstan e usa apenas os detectores "
            "nativos — prova que o pipeline funciona sem nenhuma ferramenta instalada"
        ),
    )
    parser.add_argument(
        "--with-semgrep", action="store_true",
        help="inclui semgrep (requer rede para baixar o ruleset; desligado por padrão)",
    )
    parser.add_argument(
        "--business-profile", type=Path, default=None,
        help="perfil de negócio alternativo (.toml)",
    )
    parser.add_argument(
        "--taxonomy", type=Path, default=None,
        help="taxonomia alternativa (.toml)",
    )
    parser.add_argument(
        "--fail-on", choices=("none", "critica", "alta"), default="none",
        help=(
            "código de saída 1 se houver débito na prioridade indicada — "
            "útil para usar o radar como gate de CI (padrão: none)"
        ),
    )
    parser.add_argument(
        "--skip-report", action="store_true",
        help=(
            "para depois do scoring e não invoca o time de agentes (agent_radar). "
            "Útil quando só o JSON dos achados pontuados interessa."
        ),
    )
    parser.add_argument(
        "--report-model", default=None,
        help="modelo Gemini usado pelo agent_radar (padrão: o dele mesmo)",
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help="grava o relatório final (Markdown aprovado pelo Revisor) neste arquivo",
    )
    parser.add_argument("--quiet", action="store_true", help="suprime o resumo no terminal")
    parser.add_argument("--version", action="version", version=f"analyzer {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    repo: Path = args.repo.resolve()
    if not repo.is_dir():
        print(f"erro: `{args.repo}` não é um diretório.", file=sys.stderr)
        return 2

    taxonomy = load_taxonomy(str(args.taxonomy) if args.taxonomy else None)
    profile = load_business_profile(
        str(args.business_profile) if args.business_profile else None
    )

    language = args.language or detect_language(repo)
    if language == "unknown":
        print(
            f"erro: não foi possível detectar a linguagem de `{repo}`. "
            "Use --language python|php.",
            file=sys.stderr,
        )
        return 2

    # ── 1. Coleta ────────────────────────────────────────────────────
    detection = collect(
        repo,
        language=language,
        use_external=not args.no_external,
        use_semgrep=args.with_semgrep,
    )

    # ── 2. Normalização ──────────────────────────────────────────────
    from .normalize import normalize

    findings, unmapped, suppressed = normalize(detection.raw_findings, taxonomy, profile)

    # ── 3. Scoring determinístico ────────────────────────────────────
    scored = score_all(findings, profile)

    if not args.quiet:
        _print_summary(scored, repo, detection)

    if args.fail_on != "none":
        from .models import Priority

        target = Priority.CRITICAL if args.fail_on == "critica" else Priority.HIGH
        blocking = [s for s in scored if s.priority is target or (
            target is Priority.HIGH and s.priority is Priority.CRITICAL
        )]
        if blocking and args.skip_report:
            return 1

    # ── 4. Redação + revisão — delegado ao time de agentes ───────────
    if args.skip_report:
        return 0

    from agent_radar import build_knowledge, build_team

    knowledge = build_knowledge(Path(__file__).parent, Path("tmp/chromadb"))
    team_kwargs = {"model_id": args.report_model} if args.report_model else {}
    team = build_team(knowledge=knowledge, **_default_model_kwarg(args, team_kwargs))

    prompt = (
        f"Gere o relatório de débitos técnicos do repositório `{repo}`.\n\n"
        "O Relator deve rodar a tool `pontuar_repositorio` com "
        f"repo='{repo}' e redigir o Markdown. O Revisor então audita o "
        "resultado contra o código e os dados da tool. Repitam até APROVADO."
    )
    response = team.run(prompt)

    if not args.quiet:
        print("\n" + response.content)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(response.content, encoding="utf-8")
        if not args.quiet:
            print(f"\nrelatório: {args.out}", file=sys.stderr)

    if args.fail_on != "none":
        from .models import Priority

        target = Priority.CRITICAL if args.fail_on == "critica" else Priority.HIGH
        blocking = [s for s in scored if s.priority is target or (
            target is Priority.HIGH and s.priority is Priority.CRITICAL
        )]
        if blocking:
            return 1
    return 0


def _default_model_kwarg(args: argparse.Namespace, team_kwargs: dict) -> dict:
    """Só passa `model_id` se o usuário pediu; senão usa o padrão do agent_radar."""
    return team_kwargs


def _print_summary(scored, repo: Path, detection) -> None:
    tools_on = [t for t, ok in detection.tools_available.items() if ok]
    tools_off = [t for t, ok in detection.tools_available.items() if not ok]

    print(f"\nRadar de Débitos Técnicos — {repo.name} ({detection.language})")
    print("─" * 72)
    print(f"ferramentas ativas : {', '.join(tools_on) or 'nenhuma'}")
    if tools_off:
        print(f"indisponíveis      : {', '.join(tools_off)}")
    print(f"achados brutos     : {len(detection.raw_findings)}")

    total_ocorrencias = sum(s.finding.occurrences for s in scored)
    esforco_total = round(sum(s.finding.effort_points for s in scored), 2)
    print(f"débitos agregados  : {len(scored)} ({total_ocorrencias} ocorrências)")
    print(f"esforço total      : {esforco_total} SP")
    print()

    por_prioridade: dict[str, int] = {}
    for s in scored:
        por_prioridade[s.priority.value] = por_prioridade.get(s.priority.value, 0) + 1
    print("  ".join(f"{k}: {v}" for k, v in por_prioridade.items()))
    print()


if __name__ == "__main__":
    raise SystemExit(main())
