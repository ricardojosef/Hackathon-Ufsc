"""
Detectores de PHP — a entrega bônus.

O ponto arquitetural do bônus não é "suportar mais uma linguagem": é provar
que o scoring model opera sem saber de onde o achado veio. Nada neste módulo
conhece o modelo de scoring, e `scoring.py` não importa nada daqui. A ponte é
só o `Finding` canônico, com os mesmos `rule_id` do Python — um `SEC.SQLI`
encontrado em PHP percorre exatamente as mesmas regras de priorização.

Como no Python, há um detector NATIVO (regex sobre o fonte, sem dependência)
e adapters externos opcionais (phpstan, phpmetrics).
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from ..models import RawFinding, Severity
from .base import Detector, iter_source_files, relative
from .python_external import _loads

PHP_SUFFIXES = (".php",)

# ── Padrões de detecção nativa ──────────────────────────────────────────
# Interpolação de variável dentro de string SQL: "... WHERE id = $id" ou
# concatenação com '.'. Este é o mesmo débito do lado Python.
SQL_INTERP_RE = re.compile(
    r"""(?ix)
    (?:DB::(?:select|statement|raw|insert|update|delete)|->query|->execute)
    \s*\(\s*
    (?P<q>["'])
    (?P<body>(?:(?!(?P=q)).)*)
    (?P=q)
    """,
    re.DOTALL,
)
SQL_KEYWORD_RE = re.compile(r"\b(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|WHERE|JOIN)\b", re.I)
PHP_VAR_IN_STR_RE = re.compile(r"\$\{?\w+")
SQL_CONCAT_RE = re.compile(
    r"""(?ix)(?:DB::(?:select|statement|raw)|->query)\s*\(\s*['"][^'"]*\b(?:WHERE|SELECT|FROM)\b[^'"]*['"]\s*\.""",
)
WEAK_HASH_RE = re.compile(r"\b(md5|sha1)\s*\(", re.IGNORECASE)
SECRET_ASSIGN_RE = re.compile(
    r"""(?ix)
    (?:(?:const|public|private|protected|static|var)\s+)*
    \$?(?P<name>[A-Z_][A-Z0-9_]*(?:TOKEN|SECRET|KEY|PASSWORD|PASS|WEBHOOK))
    \s*=\s*
    (?P<q>["'])(?P<value>[^"']{6,})(?P=q)
    """,
)
DEBUG_RE = re.compile(r"""(?ix)\bAPP_DEBUG\s*=\s*true|'debug'\s*=>\s*true""")
ECHO_RAW_RE = re.compile(r"\{!!\s*\$|echo\s+\$_(?:GET|POST|REQUEST)")
EMPTY_CATCH_RE = re.compile(r"catch\s*\([^)]*\)\s*\{\s*\}", re.MULTILINE)
# `catch` que apenas registra em log/echo e segue: a falha some do mesmo jeito.
LOGGING_CATCH_RE = re.compile(
    r"""catch\s*\([^)]*\)\s*\{\s*
    (?:(?://[^\n]*\n\s*)*)
    (?:Log::\w+|echo|print|error_log|\$this->(?:error|warn|info|line))[^;]*;\s*
    \}""",
    re.VERBOSE | re.MULTILINE,
)
# SELECT * na tabela de usuários: traz a coluna de senha junto.
SELECT_STAR_USERS_RE = re.compile(r"""SELECT\s+\*\s+FROM\s+users\b""", re.IGNORECASE)
# Consulta ao banco dentro de foreach/for/while => N+1.
LOOP_HEAD_RE = re.compile(r"\b(foreach|for|while)\s*\(")
DB_CALL_RE = re.compile(r"DB::(?:select|table|statement|raw)|->(?:query|get|first|find)\s*\(")
TODO_RE = re.compile(r"//\s*(TODO|FIXME|HACK|XXX)\b(.*)", re.IGNORECASE)
ROUTE_RE = re.compile(r"""Route::(get|post|put|patch|delete)\s*\(\s*['"]([^'"]+)['"]""")
DESTRUCTIVE_RE = re.compile(r"/(delete|remove|destroy)", re.IGNORECASE)


class PhpNativeDetector(Detector):
    """
    Detector nativo de PHP: regex, sem dependência externa.

    Regex é um analisador mais fraco que AST — assumido conscientemente. A
    contrapartida é que o bônus PHP funciona mesmo sem PHP instalado no
    ambiente de avaliação, e os padrões buscados são exatamente os mesmos
    débitos intencionais já catalogados na taxonomia.
    """

    name = "php-native"
    language = "php"
    tier = 0

    def run(self, repo: Path) -> list[RawFinding]:
        findings: list[RawFinding] = []
        files = iter_source_files(repo, PHP_SUFFIXES)

        for path in files:
            rel = relative(path, repo)
            try:
                source = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            lines = source.splitlines()
            findings.extend(self._scan_file(rel, source, lines))

        findings.extend(self._repo_checks(repo, files))
        findings.sort(key=lambda f: (f.file, f.line or 0, f.native_id))
        return findings

    # ------------------------------------------------------------------

    def _scan_file(self, rel: str, source: str, lines: list[str]) -> list[RawFinding]:
        out: list[RawFinding] = []

        def add(native_id: str, message: str, offset: int, severity: Severity) -> None:
            line = source.count("\n", 0, offset) + 1
            out.append(
                RawFinding(
                    source=self.name,
                    native_id=native_id,
                    message=message,
                    file=rel,
                    line=line,
                    severity_hint=severity,
                    evidence=lines[line - 1].strip()[:200] if line <= len(lines) else "",
                )
            )

        # SQL Injection: variável PHP interpolada dentro de string SQL.
        for match in SQL_INTERP_RE.finditer(source):
            body = match.group("body")
            if SQL_KEYWORD_RE.search(body) and PHP_VAR_IN_STR_RE.search(body):
                add(
                    "sql-injection",
                    "Query SQL com variável interpolada diretamente na string.",
                    match.start(),
                    Severity.CRITICAL,
                )
        for match in SQL_CONCAT_RE.finditer(source):
            add(
                "sql-injection",
                "Query SQL montada por concatenação de string.",
                match.start(),
                Severity.CRITICAL,
            )

        for match in WEAK_HASH_RE.finditer(source):
            add(
                "weak-hash",
                f"Uso de `{match.group(1)}` — algoritmo criptograficamente quebrado.",
                match.start(),
                Severity.CRITICAL,
            )

        for match in SECRET_ASSIGN_RE.finditer(source):
            value = match.group("value")
            if value.startswith(("env(", "$", "config(")):
                continue  # já vem de configuração — correto
            add(
                "hardcoded-secret",
                f"Credencial hardcoded em `{match.group('name')}`.",
                match.start(),
                Severity.CRITICAL,
            )

        for match in DEBUG_RE.finditer(source):
            add("debug-true", "Modo debug habilitado.", match.start(), Severity.HIGH)

        for match in ECHO_RAW_RE.finditer(source):
            add(
                "xss-raw-html",
                "Saída de dado dinâmico sem escape.",
                match.start(),
                Severity.HIGH,
            )

        for match in EMPTY_CATCH_RE.finditer(source):
            add(
                "swallowed-exception",
                "Bloco `catch` vazio — a falha desaparece sem rastro.",
                match.start(),
                Severity.HIGH,
            )

        for match in LOGGING_CATCH_RE.finditer(source):
            add(
                "swallowed-exception",
                "Exceção capturada e apenas registrada — sem propagação nem tratamento; "
                "o chamador não sabe que a operação falhou.",
                match.start(),
                Severity.MEDIUM,
            )

        for match in SELECT_STAR_USERS_RE.finditer(source):
            add(
                "select-star-sensitive",
                "`SELECT *` na tabela de usuários — inclui o hash de senha no resultado.",
                match.start(),
                Severity.HIGH,
            )

        out.extend(self._loop_queries(rel, source, lines))

        for match in TODO_RE.finditer(source):
            add(
                "fixme",
                f"{match.group(1).upper()}:{match.group(2).rstrip()}".strip(),
                match.start(),
                Severity.LOW,
            )

        # Rotas sem middleware de autenticação.
        for match in ROUTE_RE.finditer(source):
            verb, route = match.group(1), match.group(2)
            tail = source[match.end(): match.end() + 200]
            if "middleware" in tail and re.search(r"auth|can:", tail):
                continue
            destructive = bool(DESTRUCTIVE_RE.search(route)) or verb in {"delete"}
            add(
                "route-without-auth",
                f"Rota `{route}` sem middleware de autenticação"
                + (" — e ela apaga dados." if destructive else "."),
                match.start(),
                Severity.CRITICAL if destructive else Severity.HIGH,
            )

        # Complexidade: aproximação por contagem de pontos de decisão no método.
        out.extend(self._method_complexity(rel, source, lines))
        return out

    def _loop_queries(self, rel: str, source: str, lines: list[str]) -> list[RawFinding]:
        """
        Consulta ao banco dentro de laço — o mesmo N+1 detectado no lado Python.

        O corpo do laço é delimitado por contagem de chaves a partir do `{` que
        abre o bloco, o que evita reportar uma consulta que apenas aparece
        depois do laço no arquivo.
        """
        out: list[RawFinding] = []
        for match in LOOP_HEAD_RE.finditer(source):
            brace = source.find("{", match.end())
            if brace < 0:
                continue
            depth, idx = 0, brace
            while idx < len(source):
                if source[idx] == "{":
                    depth += 1
                elif source[idx] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                idx += 1
            body = source[brace: idx + 1]
            for call in DB_CALL_RE.finditer(body):
                line = source.count("\n", 0, brace + call.start()) + 1
                out.append(
                    RawFinding(
                        source=self.name,
                        native_id="n-plus-one",
                        message="Consulta ao banco executada dentro de laço (padrão N+1).",
                        file=rel,
                        line=line,
                        severity_hint=Severity.HIGH,
                        evidence=lines[line - 1].strip()[:200] if line <= len(lines) else "",
                    )
                )
        return out

    def _method_complexity(self, rel: str, source: str, lines: list[str]) -> list[RawFinding]:
        """
        CC aproximada por método, contando os mesmos pontos de decisão que o
        radon conta no Python (if/elseif/for/while/case/catch/&&/||/?:).

        O corpo do método é delimitado por contagem de chaves — suficiente para
        código PHP convencional e sem exigir um parser completo.
        """
        out: list[RawFinding] = []
        method_re = re.compile(
            r"(?:public|private|protected|static|\s)*function\s+(\w+)\s*\(", re.IGNORECASE
        )
        decision_re = re.compile(
            r"\b(if|elseif|else\s+if|for|foreach|while|case|catch)\b|&&|\|\||\?\s*[^:]"
        )
        for match in method_re.finditer(source):
            name = match.group(1)
            start = source.find("{", match.end())
            if start < 0:
                continue
            depth, idx = 0, start
            while idx < len(source):
                if source[idx] == "{":
                    depth += 1
                elif source[idx] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                idx += 1
            body = source[start: idx + 1]
            cc = 1 + len(decision_re.findall(body))
            if cc >= 11:
                rank = "F" if cc > 25 else "E" if cc > 20 else "D" if cc > 15 else "C"
                line = source.count("\n", 0, match.start()) + 1
                out.append(
                    RawFinding(
                        source=self.name,
                        native_id=f"cc-rank-{rank}",
                        message=f"Método `{name}` com complexidade ciclomática {cc} (rank {rank}).",
                        file=rel,
                        line=line,
                        severity_hint=Severity.HIGH if cc >= 16 else Severity.MEDIUM,
                        evidence=f"CC={cc} rank={rank}",
                        extra={"complexity": cc, "rank": rank, "function": name},
                    )
                )
        return out

    def _repo_checks(self, repo: Path, files: list[Path]) -> list[RawFinding]:
        out: list[RawFinding] = []

        has_tests = any(
            "tests" in p.parts or p.name.endswith("Test.php") for p in files
        )
        if not has_tests and files:
            out.append(
                RawFinding(
                    source=self.name,
                    native_id="no-tests",
                    message="Nenhum teste automatizado encontrado no repositório.",
                    file=".",
                    line=None,
                    severity_hint=Severity.HIGH,
                )
            )

        # .env com valores reais e banco commitado.
        for name in (".env", "database.sqlite", "database.sqlite3"):
            candidate = repo / name
            if candidate.is_file():
                out.append(
                    RawFinding(
                        source=self.name,
                        native_id="committed-secret-file",
                        message=f"`{name}` presente no repositório.",
                        file=relative(candidate, repo),
                        line=None,
                        severity_hint=Severity.HIGH,
                        evidence=name,
                    )
                )
        for candidate in sorted(repo.glob("database/*.sqlite"), key=lambda p: p.name):
            out.append(
                RawFinding(
                    source=self.name,
                    native_id="committed-secret-file",
                    message=f"Banco SQLite `{candidate.name}` versionado no repositório.",
                    file=relative(candidate, repo),
                    line=None,
                    severity_hint=Severity.HIGH,
                    evidence=candidate.name,
                )
            )

        # Módulo monolítico.
        for path in files:
            try:
                loc = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
            except OSError:
                continue
            if loc >= 180:
                out.append(
                    RawFinding(
                        source=self.name,
                        native_id="god-module",
                        message=f"`{relative(path, repo)}` concentra {loc} linhas.",
                        file=relative(path, repo),
                        line=1,
                        severity_hint=Severity.MEDIUM,
                        evidence=f"{loc} linhas",
                        extra={"loc": loc},
                    )
                )
        return out


# ─────────────────────────────────────────────────────────────────────────
#  Filtro de ruído de ambiente do phpstan
#
#  O alvo PHP é analisado SEM `composer install` (o mount é read-only), então
#  o Laravel inteiro "some" aos olhos do phpstan. Os textos abaixo vieram da
#  execução real no container — não de suposição — e todos descrevem o mesmo
#  fato: a dependência não está instalada. Reportá-los seria falso positivo de
#  ambiente, que o desafio penaliza.
# ─────────────────────────────────────────────────────────────────────────

#: Namespaces de terceiros.
_VENDOR_NAMESPACES = (
    "Illuminate", "Laravel", "Symfony", "Psr", "Carbon", "Monolog",
    "PHPUnit", "Doctrine", "Ramsey", "Faker", "GuzzleHttp",
)

#: Facades do Laravel usadas sem namespace (alias global no framework).
_LARAVEL_FACADES = ("DB", "Log", "Cache", "Auth", "Route", "Schema", "Mail", "Hash")

#: Helpers globais do Laravel — funções que só existem com o framework carregado.
_LARAVEL_HELPERS = frozenset({
    "now", "response", "redirect", "view", "bcrypt", "config", "env", "app",
    "route", "url", "asset", "collect", "abort", "session", "request", "old",
    "dd", "dump", "str", "trans", "__", "csrf_token", "storage_path",
    "base_path", "public_path", "resource_path", "database_path", "optional",
    "data_get", "value", "with", "head", "last", "tap", "throw_if",
})

_NOT_FOUND_RE = re.compile(
    r"(not found|unknown class|does not exist|has invalid type|invalid typehint)",
    re.IGNORECASE,
)
_MISSING_FUNCTION_RE = re.compile(r"Function ([\w\\]+) not found", re.IGNORECASE)
#: Métodos herdados de classes-base do framework que o phpstan não enxerga.
_UNDEFINED_MEMBER_RE = re.compile(
    r"Call to an undefined method|Access to an undefined property", re.IGNORECASE
)
#: Classes do próprio projeto — herdam de bases do framework ou usam Eloquent.
_PROJECT_NAMESPACE = "App\\"


def _is_environment_noise(message: str) -> bool:
    """
    True se a mensagem do phpstan decorre de dependência ausente.

    Quatro formas de ruído, todas observadas na execução real:

      1. namespace de terceiro + "não encontrei"  → `Illuminate\\...DB not found`
      2. facade sem namespace                     → `unknown class DB`
      3. helper global do Laravel                 → `Function now not found`
      4. membro herdado/dinâmico numa classe App\\ → `SyncData::info()`,
         `Customer::$id` (métodos de Illuminate\\Console\\Command e atributos
         do Eloquent, invisíveis sem o framework)

    O caso 4 é o mais delicado: em tese poderia esconder um erro real de
    digitação num método do projeto. Aceitamos o risco conscientemente —
    sem as dependências instaladas é IMPOSSÍVEL distinguir os dois casos, e
    reportar 30 falsos positivos para talvez pegar um real é o pior negócio
    num desafio que penaliza falso positivo.
    """
    # 3. Helper global do Laravel.
    helper = _MISSING_FUNCTION_RE.search(message)
    if helper and helper.group(1).lstrip("\\") in _LARAVEL_HELPERS:
        return True

    # 4. Membro não definido numa classe do próprio projeto que herda do framework.
    if _UNDEFINED_MEMBER_RE.search(message) and _PROJECT_NAMESPACE in message:
        return True

    if not _NOT_FOUND_RE.search(message):
        return False

    # 1. Namespace de terceiro.
    if any(ns in message for ns in _VENDOR_NAMESPACES):
        return True

    # 2. Facade do Laravel referenciada sem namespace.
    return any(
        re.search(rf"unknown class {facade}\b", message) for facade in _LARAVEL_FACADES
    )


class PhpstanDetector(Detector):
    """Análise estática de PHP (opcional)."""

    name = "phpstan"
    language = "php"
    tier = 1
    executable = "phpstan"

    def run(self, repo: Path) -> list[RawFinding]:
        target = "app" if (repo / "app").is_dir() else "."
        code, out, err = self._exec(
            [
                "phpstan", "analyse",
                "--error-format=json",
                "--no-progress",
                # Nível 1 de propósito: o alvo é analisado SEM as dependências
                # do Laravel instaladas (mount read-only, sem `composer
                # install`). Níveis altos transformariam cada classe de
                # framework ausente num "erro", e o mapping catch-all
                # `phpstan:*` promoveria tudo a débito — dezenas de falsos
                # positivos de ambiente. Nível 1 fica nos símbolos indiscutíveis.
                "--level=1",
                "--memory-limit=512M",
                target,
            ],
            repo,
        )
        data = _loads(out)
        if not isinstance(data, dict):
            motivo = (err or out or "").strip().splitlines()
            self.last_error = (
                f"saída não reconhecida (exit {code}): "
                f"{motivo[0][:200] if motivo else 'sem saída'}"
            )
            return []
        findings: list[RawFinding] = []
        for filename in sorted(data.get("files", {})):
            entry = data["files"][filename]
            for msg in entry.get("messages", []):
                text = str(msg.get("message", ""))
                if _is_environment_noise(text):
                    continue
                findings.append(
                    RawFinding(
                        source=self.name,
                        native_id="phpstan-error",
                        message=text.strip(),
                        file=relative(filename, repo),
                        line=msg.get("line"),
                        severity_hint=Severity.MEDIUM,
                    )
                )
        return findings


class PhpmetricsDetector(Detector):
    """Complexidade por classe em PHP (opcional)."""

    name = "phpmetrics"
    language = "php"
    tier = 1
    executable = "phpmetrics"

    def run(self, repo: Path) -> list[RawFinding]:
        # O relatório vai para um temporário, nunca para dentro do repo.
        # Os alvos são montados read-only no docker-compose do analyzer-env, e
        # escrever ali falharia — em silêncio, porque o adapter devolveria
        # lista vazia como se a ferramenta não tivesse achado nada.
        # A regra vale para todo o pipeline: nunca escrever no que se analisa.
        with tempfile.TemporaryDirectory(prefix="radar-phpmetrics-") as tmp:
            report = Path(tmp) / "phpmetrics.json"
            self._exec(["phpmetrics", f"--report-json={report}", "app"], repo)
            if not report.is_file():
                return []
            data = _loads(report.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(data, dict):
            return []
        findings: list[RawFinding] = []
        for name in sorted(data):
            info = data[name]
            if not isinstance(info, dict) or "ccn" not in info:
                continue
            cc = int(info.get("ccn") or 0)
            if cc < 11:
                continue
            rank = "F" if cc > 25 else "E" if cc > 20 else "D" if cc > 15 else "C"
            findings.append(
                RawFinding(
                    source=self.name,
                    native_id="cc-high",
                    message=f"Classe `{name}` com complexidade ciclomática {cc} (rank {rank}).",
                    file=_class_to_path(name, info.get("filename"), repo),
                    line=None,
                    severity_hint=Severity.HIGH if cc >= 16 else Severity.MEDIUM,
                    evidence=f"CC={cc}",
                    extra={"complexity": cc, "rank": rank, "class": name},
                )
            )
        return findings


def _class_to_path(class_name: str, filename: str | None, repo: Path) -> str:
    """
    Converte `App\\Helpers\\DateHelper` no caminho `app/Helpers/DateHelper.php`.

    O phpmetrics identifica a unidade pelo NOME DA CLASSE e não traz o arquivo
    (verificado na saída real do 2.11). Usar o nome cru como `file` deixaria
    o relatório com "locais" que não são caminhos — e, pior, impediria o dedupe
    contra os achados do detector nativo, que usam caminho de verdade.

    A convenção PSR-4 do Laravel mapeia o namespace `App\\` para `app/`, então
    a derivação é direta e verificável: só devolvemos o caminho se o arquivo
    existir de fato no repositório.
    """
    if filename:
        return relative(filename, repo)

    parts = class_name.replace("\\", "/").split("/")
    if parts and parts[0] == "App":
        candidate = Path("app", *parts[1:]).with_suffix(".php")
        if (repo / candidate).is_file():
            return candidate.as_posix()

    # Não foi possível resolver: devolve o nome da classe, que ao menos
    # identifica a unidade para quem lê o relatório.
    return class_name


class PhplocDetector(Detector):
    """
    Métricas de tamanho e complexidade do projeto PHP (bônus).

    ─────────────────────────────────────────────────────────────────────
     O PROBLEMA DE MODELAGEM
    ─────────────────────────────────────────────────────────────────────
    phploc é diferente de todas as outras ferramentas do pipeline: não
    reporta achados em `(arquivo, linha)`, e sim MÉTRICAS AGREGADAS do
    projeto inteiro. O `Finding` é ancorado em `Location`. Espalhar uma
    média do projeto por arquivos seria inventar localização — ou seja,
    fabricar falso positivo, que o desafio penaliza explicitamente.

    ─────────────────────────────────────────────────────────────────────
     A DECISÃO: um único achado, ancorado em "."
    ─────────────────────────────────────────────────────────────────────
    Emitimos EXATAMENTE UM achado, com `file="."`, e só quando a
    complexidade ciclomática MÁXIMA cruza o limiar.

    Por que só `maximum`, e não as outras métricas:

      • `cyclomaticComplexity.maximum` — SIM. É um fato exato sobre um
        método que existe de verdade: "há um método com CC 18 neste
        projeto". Não há inferência estatística, logo não há como ser
        falso positivo se a ferramenta estiver correta.
      • `cyclomaticComplexity.average` — NÃO. Média esconde a
        distribuição: 50 métodos triviais e 2 monstros dão média baixa.
        Métrica errada para esta decisão.
      • `linesOfCode` / `logicalLinesOfCode` — NÃO. Tamanho não é débito;
        um projeto grande não é um projeto ruim.
      • `classes.average.length` — NÃO. Duplicaria, de forma pior, o
        `ARCH.GOD_MODULE`, que o detector nativo já emite POR ARQUIVO,
        com localização real.

    A âncora `"."` já é o idioma do pipeline para achados que são
    propriedade do repositório e não de uma linha — ver `no-tests` em
    `PhpNativeDetector._repo_checks`.

    O limiar 11 não é inventado: é o mesmo piso usado em
    `RadonDetector.MIN_RANK` ("C"), em `PhpNativeDetector._method_complexity`
    e em `PhpmetricsDetector`. phploc não traz critério novo — confirma,
    com uma quarta fonte, o critério que as outras três já aplicam.

    Efeito prático: o achado não colapsa na mesma `Location` dos demais,
    mas entra no MESMO `Finding`, porque `normalize()` agrega por
    `rule_id`. Resultado: `MAINT.HIGH_COMPLEXITY` ganha "phploc" em
    `sources` e passa a ser corroborado. Ganha-se confiança, não uma
    linha a mais no relatório.
    """

    name = "phploc"
    language = "php"
    tier = 1
    executable = "phploc"
    #: Mesmo piso do rank C do radon, usado em todo o pipeline.
    MIN_COMPLEXITY = 11

    def run(self, repo: Path) -> list[RawFinding]:
        target = "app" if (repo / "app").is_dir() else "."
        with tempfile.TemporaryDirectory(prefix="radar-phploc-") as tmp:
            report = Path(tmp) / "phploc.json"
            self._exec(["phploc", f"--log-json={report}", target], repo)
            if not report.is_file():
                return []
            data = _loads(report.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(data, dict):
            return []

        cc_max = _phploc_max_complexity(data)
        if cc_max is None or cc_max < self.MIN_COMPLEXITY:
            return []

        rank = "F" if cc_max > 25 else "E" if cc_max > 20 else "D" if cc_max > 15 else "C"
        return [
            RawFinding(
                source=self.name,
                native_id="cc-high",
                message=(
                    f"Complexidade ciclomática máxima do projeto: {cc_max} (rank {rank}) — "
                    "existe pelo menos um método acima do limite recomendado."
                ),
                file=".",
                line=None,
                severity_hint=Severity.HIGH if cc_max >= 16 else Severity.MEDIUM,
                evidence=f"phploc: complexidade ciclomática máxima = {cc_max}",
                extra={"complexity": cc_max, "rank": rank, "scope": "project"},
            )
        ]


def _phploc_max_complexity(data: dict) -> int | None:
    """
    Extrai a CC máxima do JSON do phploc, tolerando os formatos conhecidos.

    O phploc 7.x (o do container) usa chaves PLANAS — `methodCcnMax` e
    `classCcnMax` — e não o objeto `cyclomaticComplexity.maximum` que o
    FERRAMENTAS.md documenta. Aceitamos ambos: a documentação do desafio não
    bate com a versão instalada, e um adapter que só entende uma das formas
    falharia em silêncio, devolvendo "0 achados" como se estivesse tudo bem.

    Preferimos `methodCcnMax` (CC do método mais complexo) a `classCcnMax`
    (soma dos métodos da classe), porque é a métrica comparável com o
    `radon cc` do lado Python, que também mede por função.

    A ordem de tentativa é fixa — sem varrer o dicionário, o que tornaria o
    resultado dependente da ordem das chaves.
    """
    nested = data.get("cyclomaticComplexity")
    if isinstance(nested, dict):
        value = nested.get("maximum", nested.get("max"))
        if isinstance(value, (int, float)):
            return int(value)

    for key in (
        "methodCcnMax",                  # phploc 7.x — por método (preferido)
        "classCcnMax",                   # phploc 7.x — por classe
        "maximumCyclomaticComplexity",
        "cyclomaticComplexityMaximum",
        "maxCyclomaticComplexity",
    ):
        value = data.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return None
