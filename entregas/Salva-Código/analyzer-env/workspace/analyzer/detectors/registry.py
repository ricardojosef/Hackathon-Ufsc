"""
Detecção de linguagem e orquestração dos detectores.

Política central: os detectores NATIVOS (tier 0) sempre rodam; os EXTERNOS
(tier 1) entram quando disponíveis. Não é "externo OU nativo" — é "nativo
SEMPRE, externo enriquece". Isso dá três coisas de uma vez:

  1. o pipeline funciona num ambiente sem nenhuma ferramenta instalada;
  2. os achados ganham corroboração cruzada, que o scoring usa como sinal
     de confiança contra falso positivo;
  3. o relatório declara honestamente quais ferramentas estavam presentes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..models import RawFinding
from .base import Detector, iter_source_files
from .php import (
    PhplocDetector,
    PhpmetricsDetector,
    PhpNativeDetector,
    PhpstanDetector,
)
from .python_external import (
    BanditDetector,
    PylintDetector,
    RadonDetector,
    SemgrepDetector,
)
from .python_native import PythonNativeDetector

# Arquivos que identificam a stack de forma inequívoca.
PYTHON_MARKERS = ("requirements.txt", "pyproject.toml", "setup.py", "Pipfile")
PHP_MARKERS = ("composer.json", "artisan", "composer.lock")


@dataclass
class DetectionResult:
    """Saída da etapa de coleta, com metadados para o relatório."""

    language: str
    raw_findings: list[RawFinding] = field(default_factory=list)
    #: nome da ferramenta -> rodou?
    tools_available: dict[str, bool] = field(default_factory=dict)
    #: nome da ferramenta -> quantos achados brutos produziu
    tool_counts: dict[str, int] = field(default_factory=dict)
    #: ferramentas que existiam mas falharam/não produziram JSON válido
    tool_errors: dict[str, str] = field(default_factory=dict)


def detect_language(repo: Path) -> str:
    """
    Detecta a linguagem do repositório: 'python', 'php' ou 'unknown'.

    Marcadores de projeto têm prioridade sobre contagem de arquivos — um
    projeto Laravel com um script Python solto continua sendo PHP.
    """
    has_python_marker = any((repo / m).is_file() for m in PYTHON_MARKERS)
    has_php_marker = any((repo / m).is_file() for m in PHP_MARKERS)

    if has_python_marker and not has_php_marker:
        return "python"
    if has_php_marker and not has_python_marker:
        return "php"

    # Ambíguo (ou nenhum marcador): decide pela massa de código.
    py_count = len(iter_source_files(repo, (".py",)))
    php_count = len(iter_source_files(repo, (".php",)))
    if py_count == 0 and php_count == 0:
        return "unknown"
    return "python" if py_count >= php_count else "php"


def detectors_for(
    language: str,
    *,
    use_external: bool = True,
    use_semgrep: bool = False,
) -> list[Detector]:
    """Monta a lista de detectores, em ordem fixa (nativo primeiro)."""
    chain: list[Detector] = []

    if language == "python":
        chain.append(PythonNativeDetector())
        if use_external:
            chain.extend([BanditDetector(), RadonDetector(), PylintDetector()])
    elif language == "php":
        chain.append(PhpNativeDetector())
        if use_external:
            chain.extend([PhpstanDetector(), PhpmetricsDetector(), PhplocDetector()])

    # semgrep é multi-linguagem, mas depende de rede para baixar regras —
    # por isso fica atrás de um flag explícito (ver SemgrepDetector).
    if use_semgrep and language in {"python", "php"}:
        chain.append(SemgrepDetector())

    return chain


def collect(
    repo: Path,
    *,
    language: str | None = None,
    use_external: bool = True,
    use_semgrep: bool = False,
) -> DetectionResult:
    """Roda a cadeia de detectores e devolve os achados brutos consolidados."""
    lang = language or detect_language(repo)
    result = DetectionResult(language=lang)

    for detector in detectors_for(lang, use_external=use_external, use_semgrep=use_semgrep):
        available = detector.is_available()
        result.tools_available[detector.name] = available
        if not available:
            result.tool_counts[detector.name] = 0
            continue
        detector.last_error = None
        try:
            found = detector.run(repo)
        except Exception as exc:  # ferramenta quebrada não derruba o pipeline
            result.tool_errors[detector.name] = f"{type(exc).__name__}: {exc}"
            result.tool_counts[detector.name] = 0
            continue
        # A ferramenta rodou mas não entregou saída utilizável: registrar o
        # motivo, senão "0 achados" mente por omissão no relatório.
        if detector.last_error:
            result.tool_errors[detector.name] = detector.last_error
        result.tool_counts[detector.name] = len(found)
        result.raw_findings.extend(found)

    # Ordem determinística e independente da ordem de execução das ferramentas.
    result.raw_findings.sort(key=lambda f: (f.file, f.line or 0, f.source, f.native_id))
    return result
