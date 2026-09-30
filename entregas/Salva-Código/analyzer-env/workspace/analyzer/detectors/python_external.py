"""
Adapters das ferramentas externas de Python: bandit, radon, pylint, semgrep.

Cada uma é OPCIONAL. Ausente do PATH, `is_available()` devolve False e o
pipeline segue com o detector nativo — requisito explícito do README do
desafio ("assuma que as ferramentas podem não estar instaladas").

Quando presentes, o valor que agregam não é só volume: elas CORROBORAM os
achados do detector nativo, e a corroboração entra no scoring como sinal de
confiança contra falso positivo.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ..models import RawFinding, Severity
from .base import SKIP_DIRS, Detector, relative


def _exclude_arg() -> str:
    """
    Diretórios a ignorar, como caminhos — formato do `--exclude` do bandit.

    As ferramentas externas não conhecem o `SKIP_DIRS` do pipeline e
    analisariam `vendor/`, `node_modules/` e afins. Achado em dependência de
    terceiro não é débito do time — é falso positivo, penalizado no desafio.
    Deriva da MESMA constante que os detectores nativos usam, para não existir
    duas listas divergentes.
    """
    return ",".join(f"./{name}" for name in sorted(SKIP_DIRS))


def _ignore_names_arg() -> str:
    """
    Os mesmos diretórios, como NOMES BASE — formato do `--ignore` do pylint.

    pylint casa `--ignore` contra o nome do arquivo/diretório, não contra o
    caminho; passar `./vendor` nunca casaria com nada.
    """
    return ",".join(sorted(SKIP_DIRS))

# O `-m` garante que usamos a ferramenta do MESMO interpretador que roda o
# pipeline, e não uma versão solta no PATH do sistema.
PY = sys.executable or "python"


def _loads(text: str) -> Any:
    """
    JSON tolerante: ferramentas às vezes imprimem aviso antes do JSON.

    Tenta o texto inteiro; falhando, recorta do primeiro '{' ou '[' até o fim.
    """
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        for opener in "{[":
            idx = text.find(opener)
            if idx >= 0:
                try:
                    return json.loads(text[idx:])
                except json.JSONDecodeError:
                    continue
    return None


class _PythonModuleDetector(Detector):
    """Base para ferramentas instaladas como módulo Python."""

    language = "python"
    tier = 1
    module: str = ""

    def is_available(self) -> bool:
        code, _, _ = self._exec([PY, "-c", f"import {self.module}"], Path.cwd())
        return code == 0

    def _no_output(self, code: int, out: str, err: str) -> list[RawFinding]:
        """
        Registra por que a ferramenta não produziu saída aproveitável.

        Chamado quando o JSON não veio no formato esperado. Preenche
        `last_error`, que o registry promove para o relatório — assim "0
        achados por falha" deixa de se parecer com "0 achados porque está
        tudo bem".
        """
        motivo = (err or out or "").strip().splitlines()
        detalhe = motivo[0][:200] if motivo else "sem saída"
        self.last_error = f"saída não reconhecida (exit {code}): {detalhe}"
        return []


class BanditDetector(_PythonModuleDetector):
    """Scanner de segurança. Corrobora SQLi, MD5, segredos e debug=True."""

    name = "bandit"
    module = "bandit"

    def run(self, repo: Path) -> list[RawFinding]:
        code, out, err = self._exec(
            [PY, "-m", "bandit", "-r", ".", "-f", "json", "-q",
             "--exclude", _exclude_arg()],
            repo,
        )
        data = _loads(out)
        if not isinstance(data, dict):
            return self._no_output(code, out, err)
        findings: list[RawFinding] = []
        for item in data.get("results", []):
            findings.append(
                RawFinding(
                    source=self.name,
                    native_id=str(item.get("test_id", "")),
                    message=str(item.get("issue_text", "")).strip(),
                    file=relative(item.get("filename", ""), repo),
                    line=item.get("line_number"),
                    severity_hint=Severity.parse(str(item.get("issue_severity", ""))),
                    evidence=str(item.get("code", "")).strip()[:200],
                    extra={
                        "confidence": item.get("issue_confidence"),
                        "cwe": (item.get("issue_cwe") or {}).get("id"),
                    },
                )
            )
        return findings


class RadonDetector(_PythonModuleDetector):
    """Complexidade ciclomática. Corrobora o CC calculado pelo detector nativo."""

    name = "radon"
    module = "radon"
    #: Rank C (CC ≥ 11) é o piso — abaixo disso não é débito, é código normal.
    MIN_RANK = "C"

    def run(self, repo: Path) -> list[RawFinding]:
        code, out, err = self._exec([PY, "-m", "radon", "cc", ".", "-j"], repo)
        data = _loads(out)
        if not isinstance(data, dict):
            return self._no_output(code, out, err)
        findings: list[RawFinding] = []
        for filename in sorted(data):
            blocks = data[filename]
            if not isinstance(blocks, list):
                continue  # radon reporta erro de parse como dict
            for block in blocks:
                rank = str(block.get("rank", "A"))
                if rank < self.MIN_RANK:
                    continue
                cc = block.get("complexity", 0)
                findings.append(
                    RawFinding(
                        source=self.name,
                        native_id=f"cc-rank-{rank}",
                        message=(
                            f"Função `{block.get('name')}` com complexidade "
                            f"ciclomática {cc} (rank {rank})."
                        ),
                        file=relative(filename, repo),
                        line=block.get("lineno"),
                        severity_hint=Severity.HIGH if cc >= 16 else Severity.MEDIUM,
                        evidence=f"CC={cc} rank={rank}",
                        extra={"complexity": cc, "rank": rank, "function": block.get("name")},
                    )
                )
        return findings


class PylintDetector(_PythonModuleDetector):
    """
    Linter geral. Só os símbolos presentes na taxonomia são aproveitados.

    Os demais viram `unmapped` e não entram no relatório: despejar centenas de
    avisos de convenção seria exatamente o "dump bruto" que o briefing pune.
    """

    name = "pylint"
    module = "pylint"

    def run(self, repo: Path) -> list[RawFinding]:
        code, out, err = self._exec(
            [
                PY, "-m", "pylint", ".",
                "--output-format=json",
                "--disable=C",          # convenções: ruído puro para este fim
                "--score=n",
                "--persistent=n",       # sem cache => execuções reprodutíveis
                "--jobs=1",             # paralelismo alteraria a ordem de saída
                "--recursive=y",        # alvo pode não ser um pacote importável
                f"--ignore={_ignore_names_arg()}",
            ],
            repo,
        )
        data = _loads(out)
        if not isinstance(data, list):
            return self._no_output(code, out, err)
        findings: list[RawFinding] = []
        for item in data:
            findings.append(
                RawFinding(
                    source=self.name,
                    native_id=str(item.get("symbol", "")),
                    message=str(item.get("message", "")).strip(),
                    file=relative(item.get("path", ""), repo),
                    line=item.get("line"),
                    severity_hint=Severity.parse(str(item.get("type", ""))),
                    evidence="",
                    extra={"module": item.get("module")},
                )
            )
        return findings


class SemgrepDetector(Detector):
    """
    Análise semântica multi-linguagem.

    Desligado por padrão (`--with-semgrep` no CLI): `--config=auto` baixa
    regras da internet, o que torna a execução dependente de rede e, portanto,
    NÃO determinística. Quando ligado, usa um ruleset fixo e versionado.
    """

    name = "semgrep"
    language = "any"
    tier = 1
    executable = "semgrep"
    RULESET = "p/owasp-top-ten"

    def run(self, repo: Path) -> list[RawFinding]:
        code, out, _ = self._exec(
            ["semgrep", "--config", self.RULESET, "--json", "--quiet", "--no-git-ignore", "."],
            repo,
        )
        data = _loads(out)
        if not isinstance(data, dict):
            return []
        findings: list[RawFinding] = []
        for item in data.get("results", []):
            extra = item.get("extra") or {}
            findings.append(
                RawFinding(
                    source=self.name,
                    native_id=str(item.get("check_id", "")),
                    message=str(extra.get("message", "")).strip(),
                    file=relative(item.get("path", ""), repo),
                    line=(item.get("start") or {}).get("line"),
                    severity_hint=Severity.parse(str(extra.get("severity", ""))),
                    evidence=str(extra.get("lines", "")).strip()[:200],
                )
            )
        return findings
