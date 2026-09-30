"""
Contrato comum dos detectores.

Todo detector — externo (subprocess) ou nativo (AST) — implementa esta
interface. O pipeline nunca sabe qual é qual; só consulta `is_available()`
e chama `run()`.
"""

from __future__ import annotations

import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

from ..models import RawFinding

# Diretórios que nunca devem ser analisados: dependências de terceiros e
# artefatos de build poluiriam o relatório com achados que não são débito
# do time (e contariam como falso positivo).
SKIP_DIRS = frozenset({
    ".git", "__pycache__", ".venv", "venv", "env", "node_modules",
    "vendor", ".pytest_cache", ".mypy_cache", "dist", "build",
    ".idea", ".vscode", "storage", "bootstrap",
})

# Timeout por ferramenta. Uma ferramenta travada não pode travar a entrega:
# o detector devolve lista vazia e o pipeline segue com os demais.
TOOL_TIMEOUT_S = 180


class Detector(ABC):
    """Adapter de uma fonte de achados."""

    #: Motivo pelo qual a última execução não produziu achados, quando a causa
    #: foi uma falha e não uma ausência genuína de problemas.
    #:
    #: Sem isto, os dois casos são indistinguíveis no relatório: uma ferramenta
    #: que quebrou ao parsear a saída e uma que analisou e nada encontrou
    #: aparecem igualmente como "ativa, 0 achados". O registry promove esta
    #: mensagem para `DetectionResult.tool_errors`, que já é renderizado.
    last_error: str | None = None

    name: str = "unnamed"
    language: str = "python"
    #: 0 = nativo (sempre roda, sem dependência externa)
    #: 1 = externo (roda quando a ferramenta existe no PATH)
    tier: int = 1
    #: executável procurado no PATH quando tier == 1
    executable: str | None = None

    def is_available(self) -> bool:
        """
        Detectores nativos estão sempre disponíveis; externos dependem do PATH.

        Para os externos não basta `shutil.which`: um symlink apontando para um
        `.phar` sem permissão de execução é encontrado no PATH mas falha ao
        rodar (exit 126), e o resultado apareceria como "ferramenta ativa, 0
        achados" — uma mentira silenciosa. Confirmamos executando de verdade.
        """
        if self.tier == 0:
            return True
        if self.executable is None or shutil.which(self.executable) is None:
            return False
        code, _, _ = self._exec([self.executable, "--version"], Path.cwd())
        # 126/127 = não executável ou não encontrado. Outros códigos são
        # aceitáveis: várias ferramentas devolvem != 0 até para `--version`.
        return code not in (126, 127)

    @abstractmethod
    def run(self, repo: Path) -> list[RawFinding]:
        """Analisa o repositório e devolve achados brutos."""

    # ------------------------------------------------------------------
    # Utilidades compartilhadas
    # ------------------------------------------------------------------

    def _exec(self, args: list[str], cwd: Path) -> tuple[int, str, str]:
        """
        Executa a ferramenta capturando stdout/stderr.

        Nunca levanta exceção: ferramenta ausente, quebrada ou lenta devolve
        (código != 0, "", motivo). O pipeline degrada em vez de falhar — é
        requisito explícito do README do desafio.
        """
        try:
            proc = subprocess.run(
                args,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=TOOL_TIMEOUT_S,
                check=False,
            )
            return proc.returncode, proc.stdout or "", proc.stderr or ""
        except FileNotFoundError:
            return 127, "", f"{args[0]}: não encontrado"
        except subprocess.TimeoutExpired:
            return 124, "", f"{args[0]}: timeout após {TOOL_TIMEOUT_S}s"
        except OSError as exc:  # permissão, exec format, etc.
            return 126, "", f"{args[0]}: {exc}"


def iter_source_files(repo: Path, suffixes: tuple[str, ...]) -> list[Path]:
    """
    Lista arquivos-fonte do repositório, em ordem determinística.

    A ordenação é imprescindível: a ordem de descoberta afeta a ordem dos
    achados, que afeta a numeração DT-01..DT-NN do relatório.
    """
    found: list[Path] = []
    for path in repo.rglob("*"):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(repo).parts[:-1]):
            continue
        found.append(path)
    return sorted(found, key=lambda p: p.relative_to(repo).as_posix())


def relative(path: str | Path, repo: Path) -> str:
    """
    Converte o caminho reportado por uma ferramenta em relativo ao repo.

    Determinismo: sem isso, o mesmo repositório analisado em /repos/python e
    em C:\\Users\\... produziria relatórios diferentes.

    O detalhe que importa: bandit, radon e pylint rodam com `cwd=repo` e
    devolvem caminhos RELATIVOS (`./app/x.py`). `Path("./app/x.py").resolve()`
    resolve contra a cwd do processo Python — que é de onde o pipeline foi
    invocado, não o repositório analisado. Num container, isso vira
    `/workspace/app/x.py` em vez de `/repos/python/app/x.py`, o `relative_to`
    falha e o caminho sai diferente do que o detector nativo produz.

    A consequência seria silenciosa e cara: o dedupe por (rule_id, arquivo,
    linha) não casaria, o mesmo problema viraria dois achados, e a
    corroboração entre ferramentas — que vale ×1.15 no scoring — nunca
    aconteceria. Por isso caminhos relativos são ancorados em `repo`.
    """
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = repo / candidate
    try:
        return candidate.resolve().relative_to(repo.resolve()).as_posix()
    except (ValueError, OSError):
        return Path(path).as_posix()
