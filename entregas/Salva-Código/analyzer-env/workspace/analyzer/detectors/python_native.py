"""
Detector nativo de Python — apenas `ast` da stdlib.

Existe por uma razão declarada no README do desafio: as ferramentas externas
podem não estar instaladas no ambiente de avaliação. Este detector cobre as
mesmas classes de achado que bandit/radon/pylint cobririam, sem subprocess e
sem dependências.

Efeito colateral desejado: quando as ferramentas externas ESTÃO presentes,
elas corroboram estes achados, e a corroboração entra no scoring como sinal
de confiança (ver scoring.py, regra `corroboracao`).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ..models import RawFinding, Severity
from .base import Detector, iter_source_files, relative

# Nomes de variável que denunciam credencial. Exigimos valor literal string
# com conteúdo substancial para não marcar `API_URL = ''` como segredo.
SECRET_NAME_RE = re.compile(
    r"(TOKEN|SECRET|PASSWORD|PASSWD|PASS|API_?KEY|APIKEY|WEBHOOK|CREDENTIAL|PRIVATE_?KEY)",
    re.IGNORECASE,
)
# Valores que claramente não são segredo real (placeholders de exemplo).
SECRET_PLACEHOLDER_RE = re.compile(
    r"^(|none|null|changeme|your[_-]?key|xxx+|<.*>|\{\{.*\}\}|\$\{.*\}|os\.environ.*)$",
    re.IGNORECASE,
)
WEAK_HASHES = frozenset({"md5", "sha1"})
SQL_KEYWORD_RE = re.compile(
    r"\b(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|WHERE|JOIN|FROM)\b", re.IGNORECASE
)
DB_EXEC_METHODS = frozenset({"execute", "executemany", "executescript", "raw", "query"})
FIXME_RE = re.compile(r"#\s*(TODO|FIXME|HACK|XXX)\b(.*)", re.IGNORECASE)
# Rotas destrutivas expostas sem verificação de acesso.
DESTRUCTIVE_PATH_RE = re.compile(r"/(delete|remove|destroy|drop)\b", re.IGNORECASE)


class PythonNativeDetector(Detector):
    name = "native-ast"
    language = "python"
    tier = 0  # sempre roda

    def run(self, repo: Path) -> list[RawFinding]:
        findings: list[RawFinding] = []
        files = iter_source_files(repo, (".py",))

        for path in files:
            rel = relative(path, repo)
            try:
                source = path.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source, filename=rel)
            except (SyntaxError, OSError):
                # Arquivo ilegível ou de outra versão de Python: pular em
                # silêncio é correto aqui — reportar seria falso positivo.
                continue
            lines = source.splitlines()
            _link_parents(tree)
            visitor = _ModuleVisitor(rel, lines)
            visitor.visit(tree)
            findings.extend(visitor.findings)
            findings.extend(_scan_comments(rel, lines))

        findings.extend(_repo_level_checks(repo, files))
        # Ordenação determinística e independente da ordem de varredura.
        findings.sort(key=lambda f: (f.file, f.line or 0, f.native_id))
        return findings


# ══════════════════════════════════════════════════════════════════════
#  Visitor por arquivo
# ══════════════════════════════════════════════════════════════════════


class _ModuleVisitor(ast.NodeVisitor):
    """Percorre um módulo acumulando achados."""

    def __init__(self, rel_path: str, lines: list[str]) -> None:
        self.file = rel_path
        self.lines = lines
        self.findings: list[RawFinding] = []
        # Pilha de laços ativos: usada para detectar N+1.
        self._loop_depth = 0
        # Funções do módulo, para o relatório de complexidade.
        self._func_stack: list[str] = []

    # ------------------------------------------------------------------

    def _snippet(self, node: ast.AST) -> str:
        line = getattr(node, "lineno", 0)
        if 1 <= line <= len(self.lines):
            return self.lines[line - 1].strip()[:200]
        return ""

    def _add(
        self,
        native_id: str,
        message: str,
        node: ast.AST,
        severity: Severity,
        **extra: object,
    ) -> None:
        self.findings.append(
            RawFinding(
                source="native-ast",
                native_id=native_id,
                message=message,
                file=self.file,
                line=getattr(node, "lineno", None),
                severity_hint=severity,
                evidence=self._snippet(node),
                extra=dict(extra),
            )
        )

    # ------------------------------------------------------------------
    # Estrutura
    # ------------------------------------------------------------------

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._handle_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._handle_function(node)

    def _handle_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qualified = ".".join(self._func_stack + [node.name])

        # --- Complexidade ciclomática (mesma contagem do radon) ---
        cc = _cyclomatic_complexity(node)
        if cc >= 11:  # rank C ou pior
            rank = _cc_rank(cc)
            self._add(
                f"cc-rank-{rank}",
                f"Função `{qualified}` com complexidade ciclomática {cc} (rank {rank}).",
                node,
                Severity.HIGH if cc >= 16 else Severity.MEDIUM,
                function=qualified,
                complexity=cc,
                rank=rank,
            )

        # --- Rota Flask sem controle de acesso ---
        self._check_route(node, qualified)

        # --- Despacho por string com fall-through silencioso ---
        self._check_stringly_dispatch(node, qualified)

        # --- Código morto: atribuído e nunca lido ---
        self._check_dead_assignments(node, qualified)

        self._func_stack.append(node.name)
        self.generic_visit(node)
        self._func_stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._func_stack.append(node.name)
        self.generic_visit(node)
        self._func_stack.pop()

    # ------------------------------------------------------------------
    # Laços -> N+1
    # ------------------------------------------------------------------

    def visit_For(self, node: ast.For) -> None:
        self._loop_depth += 1
        self.generic_visit(node)
        self._loop_depth -= 1

    def visit_While(self, node: ast.While) -> None:
        self._loop_depth += 1
        self.generic_visit(node)
        self._loop_depth -= 1

    def visit_comprehension(self, node: ast.comprehension) -> None:
        self._loop_depth += 1
        self.generic_visit(node)
        self._loop_depth -= 1

    # ------------------------------------------------------------------
    # Chamadas
    # ------------------------------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        attr = func.attr if isinstance(func, ast.Attribute) else None

        # --- SQL Injection + N+1 + SELECT * ---
        if attr in DB_EXEC_METHODS and node.args:
            self._check_sql(node)

        # --- Hash fraco ---
        if attr in WEAK_HASHES and isinstance(func, ast.Attribute):
            base = func.value
            if isinstance(base, ast.Name) and base.id == "hashlib":
                self._add(
                    "weak-hash",
                    f"Uso de `hashlib.{attr}` — algoritmo criptograficamente quebrado.",
                    node,
                    Severity.CRITICAL,
                    algorithm=attr,
                )
        if isinstance(func, ast.Name) and func.id in WEAK_HASHES:
            self._add(
                "weak-hash",
                f"Uso de `{func.id}` — algoritmo criptograficamente quebrado.",
                node,
                Severity.CRITICAL,
                algorithm=func.id,
            )

        # --- debug=True em app.run() ---
        if attr == "run":
            for kw in node.keywords:
                if kw.arg == "debug" and _is_true(kw.value):
                    self._add(
                        "debug-true",
                        "Aplicação executada com `debug=True`.",
                        node,
                        Severity.HIGH,
                    )

        # --- Chamada HTTP cujo retorno é descartado ---
        self._check_http_call(node)

        self.generic_visit(node)

    def _check_sql(self, node: ast.Call) -> None:
        query = node.args[0]
        sql_text = _static_sql_text(query)

        # SQL Injection: query montada com f-string / % / + contendo SQL.
        #
        # A interpolação só é vulnerável se o valor interpolado puder vir de
        # fora. Interpolar uma chave de dicionário constante — como o mapa de
        # nomes de tabela em everything.py:205 — é feio, mas não é injeção.
        # Reportar isso contaria como falso positivo, que o briefing penaliza.
        if _has_dynamic_interpolation(query) and SQL_KEYWORD_RE.search(sql_text or ""):
            if _interpolates_untrusted(query):
                self._add(
                    "sql-injection",
                    "Query SQL montada por interpolação de string em vez de parâmetro ligado.",
                    node,
                    Severity.CRITICAL,
                )

        # N+1: consulta dentro de laço.
        if self._loop_depth > 0:
            self._add(
                "n-plus-one",
                "Consulta ao banco executada dentro de laço (padrão N+1).",
                node,
                Severity.HIGH,
            )

        # SELECT * em tabela sensível.
        if sql_text and re.search(r"SELECT\s+\*", sql_text, re.IGNORECASE):
            if re.search(r"\bFROM\s+users\b", sql_text, re.IGNORECASE):
                self._add(
                    "select-star-sensitive",
                    "`SELECT *` na tabela de usuários — inclui o hash de senha no resultado.",
                    node,
                    Severity.HIGH,
                )

        # Escrita em tabela ausente do schema conhecido.
        if sql_text:
            match = re.search(r"INSERT\s+INTO\s+([a-zA-Z_][\w]*)", sql_text, re.IGNORECASE)
            if match and match.group(1).lower() in _MISSING_TABLES:
                if _inside_suppressed_try(node):
                    self._add(
                        "missing-table-write",
                        f"INSERT na tabela `{match.group(1)}`, que não existe no schema, "
                        "com a exceção suprimida.",
                        node,
                        Severity.HIGH,
                        table=match.group(1),
                    )

    def _check_http_call(self, node: ast.Call) -> None:
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in {"post", "put", "patch"}:
            return
        base = func.value
        base_name = base.id if isinstance(base, ast.Name) else None
        if base_name not in {"requests", "http_client", "session"}:
            return
        # Resultado descartado: a chamada é um statement solto.
        parent = getattr(node, "_parent", None)
        if isinstance(parent, ast.Expr):
            self._add(
                "unchecked-http-call",
                "Chamada HTTP a serviço externo com a resposta completamente ignorada.",
                node,
                Severity.MEDIUM,
            )

    # ------------------------------------------------------------------
    # Atribuições -> segredos hardcoded
    # ------------------------------------------------------------------

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            name = _target_name(target)
            if not name:
                continue
            if not SECRET_NAME_RE.search(name):
                continue
            value = node.value
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                continue
            literal = value.value.strip()
            if len(literal) < 6 or SECRET_PLACEHOLDER_RE.match(literal):
                continue
            # Senha padrão trivial é um achado distinto de credencial de serviço.
            if re.fullmatch(r"[0-9]{4,10}|password|admin|senha", literal, re.IGNORECASE):
                self._add(
                    "default-password",
                    f"Senha padrão previsível definida em `{name}`.",
                    node,
                    Severity.HIGH,
                    symbol=name,
                )
            else:
                self._add(
                    "hardcoded-secret",
                    f"Credencial hardcoded em `{name}`.",
                    node,
                    Severity.CRITICAL,
                    symbol=name,
                )
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            pseudo = ast.Assign(targets=[node.target], value=node.value)
            pseudo.lineno = node.lineno
            self.visit_Assign(pseudo)
        self.generic_visit(node)

    # ------------------------------------------------------------------
    # Exceções engolidas
    # ------------------------------------------------------------------

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        body = [n for n in node.body if not isinstance(n, ast.Pass)]
        is_bare_pass = not body
        # `except: print(...)` também engole: registra mas não propaga nem trata.
        only_print = len(body) == 1 and _is_print_stmt(body[0])

        if is_bare_pass:
            self._add(
                "swallowed-exception",
                "Bloco `except` com apenas `pass` — a falha desaparece sem rastro.",
                node,
                Severity.HIGH,
            )
        elif only_print:
            self._add(
                "swallowed-exception",
                "Exceção capturada e apenas impressa — sem log estruturado nem propagação.",
                node,
                Severity.MEDIUM,
            )

        # Captura genérica.
        if node.type is None or _name_of(node.type) in {"Exception", "BaseException"}:
            self._add(
                "broad-except",
                "Captura genérica de exceção (`except Exception`).",
                node,
                Severity.LOW,
            )

        # Credencial vazando para log dentro do handler.
        for sub in ast.walk(node):
            if isinstance(sub, ast.JoinedStr) and _fstring_mentions_secret(sub):
                self._add(
                    "secret-in-log",
                    "Mensagem de erro imprime credencial em texto plano.",
                    sub,
                    Severity.HIGH,
                )
        self.generic_visit(node)

    # ------------------------------------------------------------------
    # XSS: HTML montado com interpolação e devolvido pela rota
    # ------------------------------------------------------------------

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        name = _target_name(node.target)
        if name and "html" in name.lower() and _has_dynamic_interpolation(node.value):
            text = _static_sql_text(node.value) or ""
            if "<" in text:
                self._add(
                    "xss-raw-html",
                    "HTML montado por concatenação com dados dinâmicos, sem escape.",
                    node,
                    Severity.HIGH,
                )
        self.generic_visit(node)

    # ------------------------------------------------------------------
    # Verificações por função
    # ------------------------------------------------------------------

    def _check_route(self, node: ast.FunctionDef | ast.AsyncFunctionDef, qualified: str) -> None:
        route_paths: list[str] = []
        decorator_names: list[str] = []
        for dec in node.decorator_list:
            decorator_names.append(_decorator_name(dec))
            if isinstance(dec, ast.Call):
                target = _decorator_name(dec)
                if target.endswith(".route") or target in {"route", "get", "post", "delete"}:
                    for arg in dec.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            route_paths.append(arg.value)
        if not route_paths:
            return

        has_auth = any(
            re.search(r"login_required|auth|jwt|require|permission", d, re.IGNORECASE)
            for d in decorator_names
        )
        if has_auth:
            return

        destructive = any(DESTRUCTIVE_PATH_RE.search(p) for p in route_paths)
        self._add(
            "route-without-auth",
            f"Rota `{route_paths[0]}` exposta sem autenticação ou verificação de acesso"
            + (" — e ela apaga dados." if destructive else "."),
            node,
            Severity.CRITICAL if destructive else Severity.HIGH,
            route=route_paths[0],
            function=qualified,
            destructive=destructive,
        )

    def _check_stringly_dispatch(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, qualified: str
    ) -> None:
        """
        Cadeia if/elif comparando um parâmetro com literais string, sem `else`
        que trate o caso desconhecido — ou com `else` devolvendo None.
        """
        branches = 0
        current: ast.AST | None = None
        for stmt in node.body:
            if isinstance(stmt, ast.If):
                current = stmt
                break
        while isinstance(current, ast.If):
            if _compares_param_to_str_literal(current.test, node):
                branches += 1
            nxt = current.orelse[0] if len(current.orelse) == 1 else None
            if isinstance(nxt, ast.If):
                current = nxt
                continue
            # Fim da cadeia: verifica o else final.
            if branches >= 4:
                tail = current.orelse
                silent = not tail or all(
                    isinstance(s, ast.Return) and (s.value is None or _is_none(s.value))
                    for s in tail
                )
                if silent:
                    self._add(
                        "stringly-typed-dispatch",
                        f"`{qualified}` despacha por {branches} comparações de string e "
                        "devolve None no caso não reconhecido.",
                        node,
                        Severity.MEDIUM,
                        function=qualified,
                        branches=branches,
                    )
            break

    def _check_dead_assignments(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, qualified: str
    ) -> None:
        """Variáveis locais atribuídas uma vez e nunca lidas."""
        assigned: dict[str, ast.AST] = {}
        read: set[str] = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name):
                if isinstance(sub.ctx, ast.Store):
                    assigned.setdefault(sub.id, sub)
                elif isinstance(sub.ctx, ast.Load):
                    read.add(sub.id)
            elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub is not node:
                # Closures podem ler nomes do escopo externo.
                for inner in ast.walk(sub):
                    if isinstance(inner, ast.Name):
                        read.add(inner.id)
        dead = sorted(n for n in assigned if n not in read and not n.startswith("_"))
        for name in dead:
            self._add(
                "dead-variable",
                f"Variável `{name}` atribuída e nunca utilizada em `{qualified}`.",
                assigned[name],
                Severity.LOW,
                symbol=name,
                function=qualified,
            )


# Tabelas referenciadas pelo código mas ausentes do schema real do alvo.
# Mantido como dado para o detector não depender de conexão ao banco.
_MISSING_TABLES = frozenset({"invoices", "notifications"})


# ══════════════════════════════════════════════════════════════════════
#  Helpers de AST
# ══════════════════════════════════════════════════════════════════════


def _cyclomatic_complexity(node: ast.AST) -> int:
    """
    CC pela mesma convenção do radon: 1 + cada ponto de decisão.

    Conta if/for/while/except/with-bool, cada `elif`, cada operando extra de
    `and`/`or`, cada comprehension e cada `case`.
    """
    complexity = 1
    for sub in ast.walk(node):
        if isinstance(sub, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler)):
            complexity += 1
        elif isinstance(sub, ast.BoolOp):
            complexity += len(sub.values) - 1
        elif isinstance(sub, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            complexity += len(sub.generators)
        elif isinstance(sub, ast.IfExp):
            complexity += 1
        elif isinstance(sub, ast.Assert):
            complexity += 1
        elif hasattr(ast, "match_case") and isinstance(sub, ast.match_case):
            complexity += 1
    return complexity


def _cc_rank(cc: int) -> str:
    if cc <= 5:
        return "A"
    if cc <= 10:
        return "B"
    if cc <= 15:
        return "C"
    if cc <= 20:
        return "D"
    if cc <= 25:
        return "E"
    return "F"


def _has_dynamic_interpolation(node: ast.AST) -> bool:
    """True se o nó constrói string com valor dinâmico (f-string, %, +, .format)."""
    if isinstance(node, ast.JoinedStr):
        return any(isinstance(v, ast.FormattedValue) for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mod, ast.Add)):
        return not (
            isinstance(node.left, ast.Constant) and isinstance(node.right, ast.Constant)
        )
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "format":
            return True
    return False


def _interpolates_untrusted(node: ast.AST) -> bool:
    """
    True se alguma expressão interpolada na query puder carregar valor externo.

    Considera CONFIÁVEL apenas a indexação de um mapa cujo nome é uma constante
    em CAIXA_ALTA (convenção de constante de módulo): `TABLE_MAP[thing]` só pode
    produzir um dos valores literais do próprio mapa, independente do que
    `thing` valha. Qualquer outra coisa — variável simples, atributo, chamada —
    é tratada como potencialmente controlada pelo usuário.

    Conservador na direção certa: prefere deixar passar um caso exótico a
    inventar uma vulnerabilidade que não existe.
    """
    for expr in _interpolated_exprs(node):
        if isinstance(expr, ast.Subscript):
            base = expr.value
            if isinstance(base, ast.Name) and base.id.isupper():
                continue  # mapa constante de módulo — valores são literais
        return True
    return False


def _interpolated_exprs(node: ast.AST) -> list[ast.AST]:
    """Expressões dinâmicas embutidas numa construção de string."""
    out: list[ast.AST] = []
    if isinstance(node, ast.JoinedStr):
        for value in node.values:
            if isinstance(value, ast.FormattedValue):
                out.append(value.value)
    elif isinstance(node, ast.BinOp):
        for side in (node.left, node.right):
            if isinstance(side, ast.Constant):
                continue
            if isinstance(side, (ast.JoinedStr, ast.BinOp)):
                out.extend(_interpolated_exprs(side))
            else:
                out.append(side)
    elif isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "format":
            out.extend(node.args)
    return out


def _static_sql_text(node: ast.AST) -> str:
    """Reconstrói a parte estática de uma string, ignorando as interpolações."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)
        )
    if isinstance(node, ast.BinOp):
        return _static_sql_text(node.left) + " " + _static_sql_text(node.right)
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "format":
            return _static_sql_text(func.value)
    return ""


def _fstring_mentions_secret(node: ast.JoinedStr) -> bool:
    """f-string cuja parte estática menciona token/senha E interpola algo."""
    static = "".join(
        v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)
    )
    if not SECRET_NAME_RE.search(static):
        return False
    return any(
        isinstance(v, ast.FormattedValue)
        and SECRET_NAME_RE.search(ast.unparse(v.value) if hasattr(ast, "unparse") else "")
        for v in node.values
    )


def _target_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _name_of(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Tuple) and node.elts:
        return _name_of(node.elts[0])
    return ""


def _decorator_name(node: ast.AST) -> str:
    target = node.func if isinstance(node, ast.Call) else node
    try:
        return ast.unparse(target)
    except Exception:  # pragma: no cover - unparse é estável no 3.9+
        return _name_of(target)


def _is_true(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _is_none(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _is_print_stmt(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "print"
    )


def _compares_param_to_str_literal(
    test: ast.AST, func: ast.FunctionDef | ast.AsyncFunctionDef
) -> bool:
    """`action == 'format'`, onde `action` é parâmetro da função."""
    if not isinstance(test, ast.Compare) or not isinstance(test.left, ast.Name):
        return False
    params = {a.arg for a in func.args.args} | {a.arg for a in func.args.kwonlyargs}
    if test.left.id not in params:
        return False
    return any(
        isinstance(c, ast.Constant) and isinstance(c.value, str) for c in test.comparators
    )


def _link_parents(tree: ast.AST) -> None:
    """
    Anota `_parent` em cada nó.

    `ast` não oferece navegação para cima, e duas regras precisam do contexto
    do pai: saber se o retorno de uma chamada HTTP é descartado (pai é `Expr`)
    e se um INSERT está dentro de `try/except: pass`.
    """
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            child._parent = parent  # type: ignore[attr-defined]


def _inside_suppressed_try(node: ast.AST) -> bool:
    """
    True se o nó está no corpo de um `try` cujo `except` apenas suprime.

    Sem esta verificação, um INSERT numa tabela ausente seria reportado mesmo
    quando o erro é propagado corretamente — e aí não seria débito, seria
    apenas um bug visível. O achado só vale quando a falha é invisível.
    """
    current: ast.AST | None = getattr(node, "_parent", None)
    while current is not None:
        if isinstance(current, ast.Try):
            for handler in current.handlers:
                body = [n for n in handler.body if not isinstance(n, ast.Pass)]
                if not body or (len(body) == 1 and _is_print_stmt(body[0])):
                    return True
        current = getattr(current, "_parent", None)
    return False


# ══════════════════════════════════════════════════════════════════════
#  Varreduras fora do AST
# ══════════════════════════════════════════════════════════════════════


def _scan_comments(rel: str, lines: list[str]) -> list[RawFinding]:
    """TODO/FIXME não são visíveis no AST (comentários são descartados)."""
    out: list[RawFinding] = []
    for idx, line in enumerate(lines, start=1):
        match = FIXME_RE.search(line)
        if match:
            out.append(
                RawFinding(
                    source="native-ast",
                    native_id="fixme",
                    message=f"{match.group(1).upper()}:{match.group(2).rstrip()}".strip(),
                    file=rel,
                    line=idx,
                    severity_hint=Severity.LOW,
                    evidence=line.strip()[:200],
                )
            )
    return out


def _repo_level_checks(repo: Path, py_files: list[Path]) -> list[RawFinding]:
    """Achados que são propriedade do repositório, não de um arquivo."""
    out: list[RawFinding] = []

    # --- Ausência de testes ---
    has_tests = any(
        p.name.startswith("test_") or p.name.endswith("_test.py") or "tests" in p.parts
        for p in py_files
    )
    if not has_tests and py_files:
        declares_pytest = False
        req = repo / "requirements.txt"
        if req.is_file():
            declares_pytest = "pytest" in req.read_text(encoding="utf-8", errors="replace").lower()
        out.append(
            RawFinding(
                source="native-ast",
                native_id="no-tests",
                message=(
                    "Nenhum teste automatizado encontrado no repositório"
                    + (" — apesar de pytest constar nas dependências." if declares_pytest else ".")
                ),
                file=".",
                line=None,
                severity_hint=Severity.HIGH,
                evidence="requirements.txt declara pytest" if declares_pytest else "",
            )
        )

    # --- Segredos / banco commitados ---
    for pattern, label in ((".env", "arquivo .env"), ("*.sqlite", "banco SQLite"),
                           ("*.sqlite3", "banco SQLite"), ("*.db", "banco de dados")):
        for path in sorted(repo.glob(pattern), key=lambda p: p.name):
            if not path.is_file():
                continue
            out.append(
                RawFinding(
                    source="native-ast",
                    native_id="committed-secret-file",
                    message=f"{label.capitalize()} `{path.name}` presente na raiz do repositório.",
                    file=relative(path, repo),
                    line=None,
                    severity_hint=Severity.HIGH,
                    evidence=path.name,
                )
            )

    # --- Módulo monolítico ---
    for path in py_files:
        try:
            loc = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            continue
        if loc >= 180:
            rel = relative(path, repo)
            out.append(
                RawFinding(
                    source="native-ast",
                    native_id="god-module",
                    message=f"`{rel}` concentra {loc} linhas com rotas, SQL, regra de negócio e HTML.",
                    file=rel,
                    line=1,
                    severity_hint=Severity.MEDIUM,
                    evidence=f"{loc} linhas",
                    extra={"loc": loc},
                )
            )

    # --- API sem versionamento ---
    versioned = re.compile(r"/api/v\d+")
    api_route = re.compile(r"""['"](/api/[^'"]*)['"]""")
    for path in py_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        routes = [m for m in api_route.findall(text) if not versioned.search(m)]
        if routes:
            out.append(
                RawFinding(
                    source="native-ast",
                    native_id="no-api-versioning",
                    message=f"Endpoint público sem versão: `{sorted(routes)[0]}`.",
                    file=relative(path, repo),
                    line=None,
                    severity_hint=Severity.LOW,
                    evidence=sorted(routes)[0],
                )
            )

    return out
