"""
Testes de normalização, taxonomia e detecção.

Usam fixtures congelados dos JSONs das ferramentas externas, de modo que
rodam sem bandit/radon/pylint instalados — que é exatamente a condição do
ambiente de avaliação.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ..config import load_business_profile, load_taxonomy
from ..detectors.php import PhplocDetector, _is_environment_noise, _phploc_max_complexity
from ..detectors.python_external import BanditDetector, RadonDetector, _loads
from ..detectors.python_native import PythonNativeDetector
from ..detectors.base import relative
from ..detectors.registry import detect_language
from ..models import Category, RawFinding, Severity
from ..normalize import normalize
from . import target_repo

TAXONOMY = load_taxonomy()
PROFILE = load_business_profile()


def raw(source: str, native_id: str, file: str = "app/x.py", line: int = 1, **kw) -> RawFinding:
    return RawFinding(
        source=source, native_id=native_id, message="msg", file=file, line=line, **kw
    )


class TestTaxonomia(unittest.TestCase):
    def test_traducao_literal(self):
        self.assertEqual(TAXONOMY.resolve("bandit", "B608"), "SEC.SQLI")
        self.assertEqual(TAXONOMY.resolve("bandit", "B324"), "SEC.WEAK_HASH")
        self.assertEqual(TAXONOMY.resolve("native-ast", "sql-injection"), "SEC.SQLI")

    def test_traducao_por_padrao(self):
        self.assertEqual(
            TAXONOMY.resolve("semgrep", "python.lang.security.audit.formatted-sql-query"),
            "SEC.SQLI",
        )
        self.assertEqual(TAXONOMY.resolve("phpstan", "qualquer-coisa"), "MAINT.TYPE_ERROR")

    def test_id_desconhecido_nao_e_inventado(self):
        """
        Regra de ouro contra falso positivo: o que não está na taxonomia é
        descartado, não recebe categoria genérica.
        """
        self.assertIsNone(TAXONOMY.resolve("bandit", "B999-inexistente"))
        self.assertIsNone(TAXONOMY.resolve("ferramenta-fantasma", "x"))

    def test_python_e_php_compartilham_os_mesmos_rule_ids(self):
        """
        O ponto arquitetural do bônus: um SQLi em PHP vira o MESMO rule_id
        que em Python, e por isso percorre as mesmas regras de scoring.
        """
        self.assertEqual(
            TAXONOMY.resolve("native-ast", "sql-injection"),
            TAXONOMY.resolve("php-native", "sql-injection"),
        )
        self.assertEqual(
            TAXONOMY.resolve("native-ast", "n-plus-one"),
            TAXONOMY.resolve("php-native", "n-plus-one"),
        )

    def test_toda_regra_tem_os_campos_obrigatorios(self):
        for spec in TAXONOMY.all_rules():
            self.assertTrue(spec.nome.strip(), spec.rule_id)
            self.assertTrue(spec.descricao.strip(), spec.rule_id)
            self.assertTrue(spec.remediacao.strip(), spec.rule_id)
            self.assertGreater(spec.esforco_sp, 0, spec.rule_id)
            Category(spec.categoria)          # levanta se a categoria for inválida
            self.assertIn(spec.severidade, {"LOW", "MEDIUM", "HIGH", "CRITICAL"})

    def test_todo_mapeamento_aponta_para_regra_existente(self):
        """Um mapeamento órfão silenciaria achados sem ninguém perceber."""
        for chave, rule_id in TAXONOMY._mapping.items():
            self.assertIsNotNone(
                TAXONOMY.rule(rule_id), f"`{chave}` aponta para regra inexistente `{rule_id}`"
            )


class TestDedupe(unittest.TestCase):
    def test_mesmo_ponto_por_duas_ferramentas_vira_um_achado(self):
        findings, _, _ = normalize(
            [
                raw("native-ast", "weak-hash", "app/a.py", 10),
                raw("bandit", "B324", "app/a.py", 10),
            ],
            TAXONOMY,
            PROFILE,
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].occurrences, 1)
        self.assertEqual(findings[0].sources, ("bandit", "native-ast"))
        self.assertTrue(findings[0].corroborated)

    def test_agregacao_por_padrao(self):
        """6 SQLi em 4 arquivos = 1 débito com 6 ocorrências."""
        entradas = [
            raw("native-ast", "sql-injection", f"app/f{i}.py", 10 + i) for i in range(6)
        ]
        findings, _, _ = normalize(entradas, TAXONOMY, PROFILE)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].occurrences, 6)

    def test_achado_fora_da_taxonomia_vai_para_unmapped(self):
        findings, unmapped, _ = normalize(
            [raw("bandit", "B999"), raw("native-ast", "sql-injection")],
            TAXONOMY,
            PROFILE,
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(len(unmapped), 1)
        self.assertEqual(unmapped[0].native_id, "B999")

    def test_severidade_sobe_mas_nao_desce(self):
        """A base da taxonomia é piso; a ferramenta pode agravar, não abrandar."""
        findings, _, _ = normalize(
            [raw("pylint", "fixme", severity_hint=Severity.CRITICAL)], TAXONOMY, PROFILE
        )
        self.assertEqual(findings[0].severity, Severity.CRITICAL)

        findings, _, _ = normalize(
            [raw("native-ast", "sql-injection", severity_hint=Severity.LOW)],
            TAXONOMY,
            PROFILE,
        )
        self.assertEqual(findings[0].severity, Severity.CRITICAL)

    def test_esforco_cresce_sublinearmente(self):
        """Corrigir 6 ocorrências do mesmo padrão não custa 6× uma."""
        um, _, _ = normalize([raw("native-ast", "sql-injection", "a.py", 1)], TAXONOMY, PROFILE)
        seis, _, _ = normalize(
            [raw("native-ast", "sql-injection", f"f{i}.py", i) for i in range(6)],
            TAXONOMY,
            PROFILE,
        )
        self.assertGreater(seis[0].effort_points, um[0].effort_points)
        self.assertLess(seis[0].effort_points, um[0].effort_points * 6)


class TestTagsDeContexto(unittest.TestCase):
    def test_tag_de_questionario_e_derivada_do_perfil(self):
        findings, _, _ = normalize([raw("native-ast", "weak-hash")], TAXONOMY, PROFILE)
        tags = findings[0].tags
        self.assertTrue(any(t.startswith("questionario:") for t in tags))
        # MD5 responde às perguntas 3 (hash de senha) e 7 (algoritmo inseguro).
        self.assertIn("questionario:q3", tags)
        self.assertIn("questionario:q7", tags)

    def test_tag_release_path_marca_arquivo_da_v21(self):
        findings, _, _ = normalize(
            [raw("native-ast", "sql-injection", "app/routes/report_routes.py", 29)],
            TAXONOMY,
            PROFILE,
        )
        self.assertIn("release-path", findings[0].tags)

    def test_arquivo_fora_da_release_nao_recebe_a_tag(self):
        findings, _, _ = normalize(
            [raw("native-ast", "sql-injection", "app/everything.py", 219)],
            TAXONOMY,
            PROFILE,
        )
        self.assertNotIn("release-path", findings[0].tags)


class TestDeteccaoDeLinguagem(unittest.TestCase):
    def test_detecta_python_por_marcador(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "requirements.txt").write_text("flask\n", encoding="utf-8")
            self.assertEqual(detect_language(repo), "python")

    def test_detecta_php_por_marcador(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "composer.json").write_text("{}", encoding="utf-8")
            self.assertEqual(detect_language(repo), "php")

    def test_marcador_vence_contagem_de_arquivos(self):
        """Projeto Laravel com um script Python solto continua sendo PHP."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "composer.json").write_text("{}", encoding="utf-8")
            (repo / "util.py").write_text("x = 1\n", encoding="utf-8")
            self.assertEqual(detect_language(repo), "php")

    def test_repo_vazio_e_desconhecido(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(detect_language(Path(tmp)), "unknown")


class TestDetectorNativo(unittest.TestCase):
    """O detector que precisa funcionar sem nenhuma ferramenta instalada."""

    def _run(self, code: str) -> list[RawFinding]:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "app.py").write_text(code, encoding="utf-8")
            return PythonNativeDetector().run(repo)

    def _ids(self, code: str) -> set[str]:
        return {f.native_id for f in self._run(code)}

    def test_detecta_sql_injection_por_fstring(self):
        code = "def f(db, mes):\n    return db.execute(f'SELECT * FROM h WHERE m = {mes}')\n"
        self.assertIn("sql-injection", self._ids(code))

    def test_nao_reporta_query_parametrizada(self):
        code = "def f(db, i):\n    return db.execute('SELECT * FROM c WHERE id = ?', (i,))\n"
        self.assertNotIn("sql-injection", self._ids(code))

    def test_nao_reporta_interpolacao_de_mapa_constante(self):
        """
        Falso positivo que a IA sugeriu e nós rejeitamos: o valor interpolado
        vem de um dicionário constante, então não pode ser controlado por
        quem faz a requisição.
        """
        code = (
            "TABLE_MAP = {'customer': 'customers'}\n"
            "def f(db, thing, i):\n"
            "    return db.execute(f'DELETE FROM {TABLE_MAP[thing]} WHERE id = ?', (i,))\n"
        )
        self.assertNotIn("sql-injection", self._ids(code))

    def test_detecta_md5(self):
        code = "import hashlib\ndef f(p):\n    return hashlib.md5(p.encode()).hexdigest()\n"
        self.assertIn("weak-hash", self._ids(code))

    def test_detecta_segredo_hardcoded(self):
        code = "ERP_API_TOKEN = 'ERP_TOKEN_production_abc123xyz789'\n"
        self.assertIn("hardcoded-secret", self._ids(code))

    def test_nao_reporta_segredo_vindo_do_ambiente(self):
        code = "import os\nAPI_KEY = os.environ['API_KEY']\n"
        self.assertNotIn("hardcoded-secret", self._ids(code))

    def test_nao_reporta_placeholder(self):
        code = "API_TOKEN = 'changeme'\nAPI_SECRET = ''\n"
        self.assertNotIn("hardcoded-secret", self._ids(code))

    def test_detecta_n_plus_one(self):
        code = (
            "def f(db, rows):\n"
            "    for r in rows:\n"
            "        db.execute('SELECT * FROM c WHERE id = ?', (r,))\n"
        )
        self.assertIn("n-plus-one", self._ids(code))

    def test_detecta_except_pass(self):
        code = "def f():\n    try:\n        g()\n    except Exception:\n        pass\n"
        self.assertIn("swallowed-exception", self._ids(code))

    def test_detecta_debug_true(self):
        code = "app.run(debug=True, port=8000)\n"
        self.assertIn("debug-true", self._ids(code))

    def test_complexidade_ciclomatica_bate_com_o_radon(self):
        """
        `handle_date` do repositório-alvo tem CC 29 segundo o radon
        (documentado em analyzer-env/workspace/FERRAMENTAS.md). O cálculo
        nativo precisa chegar ao mesmo número, senão as duas fontes não
        poderiam se corroborar.
        """
        alvo = target_repo("bad-codebase-python")
        if alvo is None:
            self.skipTest("repositório-alvo não disponível")
        achados = PythonNativeDetector().run(alvo)
        cc = [
            f for f in achados
            if f.file == "app/helpers/date_helper.py" and f.native_id.startswith("cc-rank")
        ]
        self.assertTrue(cc, "nenhum achado de complexidade em date_helper.py")
        self.assertEqual(cc[0].extra["complexity"], 29)
        self.assertEqual(cc[0].extra["rank"], "F")

    def test_detecta_ausencia_de_testes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
            ids = {f.native_id for f in PythonNativeDetector().run(repo)}
            self.assertIn("no-tests", ids)

    def test_nao_reporta_ausencia_de_testes_quando_existem(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
            (repo / "test_app.py").write_text("def test_x(): pass\n", encoding="utf-8")
            ids = {f.native_id for f in PythonNativeDetector().run(repo)}
            self.assertNotIn("no-tests", ids)

    def test_arquivo_com_sintaxe_invalida_nao_derruba_o_detector(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "ok.py").write_text("import hashlib\nhashlib.md5(b'x')\n", encoding="utf-8")
            (repo / "quebrado.py").write_text("def f(:\n", encoding="utf-8")
            ids = {f.native_id for f in PythonNativeDetector().run(repo)}
            self.assertIn("weak-hash", ids)

    def test_saida_e_deterministica(self):
        alvo = target_repo("bad-codebase-python")
        if alvo is None:
            self.skipTest("repositório-alvo não disponível")
        detector = PythonNativeDetector()
        primeira = [(f.file, f.line, f.native_id) for f in detector.run(alvo)]
        for _ in range(3):
            self.assertEqual(
                [(f.file, f.line, f.native_id) for f in detector.run(alvo)], primeira
            )


class TestParsersExternos(unittest.TestCase):
    """
    Fixtures congelados: garantem que os adapters sabem ler o formato real
    das ferramentas mesmo sem elas instaladas.
    """

    BANDIT_JSON = """
    {"results": [
      {"filename": "/repos/python/app/everything.py", "line_number": 177,
       "issue_severity": "HIGH", "issue_confidence": "HIGH",
       "issue_text": "Use of weak MD5 hash for security.",
       "test_id": "B324", "issue_cwe": {"id": 327}},
      {"filename": "/repos/python/app/everything.py", "line_number": 7,
       "issue_severity": "LOW", "issue_confidence": "MEDIUM",
       "issue_text": "Possible hardcoded password: '123456'",
       "test_id": "B105", "issue_cwe": {"id": 259}}
    ]}
    """

    RADON_JSON = """
    {"app/helpers/date_helper.py": [
      {"name": "handle_date", "type": "F", "complexity": 29, "rank": "F", "lineno": 14}
    ]}
    """

    def test_json_tolerante_a_lixo_antes(self):
        self.assertEqual(_loads('AVISO: algo\n{"a": 1}'), {"a": 1})
        self.assertEqual(_loads("[1, 2]"), [1, 2])
        self.assertIsNone(_loads(""))
        self.assertIsNone(_loads("nada de json aqui"))

    def test_fixture_bandit_normaliza_para_regras_canonicas(self):
        import json

        data = json.loads(self.BANDIT_JSON)
        entradas = [
            RawFinding(
                source="bandit",
                native_id=item["test_id"],
                message=item["issue_text"],
                file="app/everything.py",
                line=item["line_number"],
                severity_hint=Severity.parse(item["issue_severity"]),
            )
            for item in data["results"]
        ]
        findings, unmapped, _ = normalize(entradas, TAXONOMY, PROFILE)
        self.assertEqual(unmapped, [])
        rule_ids = {f.rule_id for f in findings}
        self.assertEqual(rule_ids, {"SEC.WEAK_HASH", "SEC.HARDCODED_SECRET"})

    def test_severidade_das_ferramentas_e_traduzida(self):
        self.assertEqual(Severity.parse("HIGH"), Severity.HIGH)
        self.assertEqual(Severity.parse("error"), Severity.HIGH)
        self.assertEqual(Severity.parse("warning"), Severity.MEDIUM)
        self.assertEqual(Severity.parse("convention"), Severity.LOW)
        self.assertEqual(Severity.parse("desconhecida"), Severity.MEDIUM)

    def test_radon_so_reporta_rank_c_ou_pior(self):
        self.assertEqual(RadonDetector.MIN_RANK, "C")
        self.assertLess("B", RadonDetector.MIN_RANK)

    def test_detectores_externos_ausentes_nao_quebram(self):
        """`is_available()` deve responder False, não levantar exceção."""
        for detector in (BanditDetector(), RadonDetector()):
            self.assertIsInstance(detector.is_available(), bool)


class TestSupressaoDeFalsoPositivo(unittest.TestCase):
    """
    As ferramentas genéricas não fazem análise de fluxo. O bandit marca
    `f'DELETE FROM {TABLE_MAP[thing]}'` como SQLi, mas o valor interpolado só
    pode vir de um dicionário constante. A supressão deixa a análise mais
    precisa prevalecer — sem esconder o descarte.
    """

    def test_falso_positivo_conhecido_e_suprimido(self):
        findings, _, suppressed = normalize(
            [raw("bandit", "B608", "app/everything.py", 205)], TAXONOMY, PROFILE
        )
        self.assertEqual(findings, [])
        self.assertEqual(len(suppressed), 1)

    def test_supressao_exige_justificativa_escrita(self):
        """Supressão sem motivo seria indistinguível de esconder achado."""
        _, _, suppressed = normalize(
            [raw("bandit", "B608", "app/everything.py", 205)], TAXONOMY, PROFILE
        )
        _, motivo = suppressed[0]
        self.assertGreater(len(motivo), 80, "justificativa curta demais")
        self.assertIn("TABLE_MAP", motivo)

    def test_supressao_e_cirurgica(self):
        """Suprime a linha exata, nunca a regra inteira nem o arquivo inteiro."""
        findings, _, suppressed = normalize(
            [
                raw("bandit", "B608", "app/everything.py", 205),   # suprimido
                raw("bandit", "B608", "app/everything.py", 219),   # real
            ],
            TAXONOMY,
            PROFILE,
        )
        self.assertEqual(len(suppressed), 1)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].locations[0].line, 219)

    def test_toda_supressao_aponta_para_regra_existente(self):
        for (rule_id, arquivo, _linha), motivo in TAXONOMY.suppressions().items():
            self.assertIsNotNone(TAXONOMY.rule(rule_id), rule_id)
            self.assertTrue(arquivo.strip())
            self.assertTrue(motivo.strip(), f"supressão de {rule_id} sem justificativa")


class TestCaminhosRelativos(unittest.TestCase):
    """
    bandit e radon rodam com cwd=repo e devolvem `./app/x.py`.

    Se esses caminhos forem resolvidos contra a cwd do PROCESSO (que pode ser
    /workspace num container) em vez de contra o repo, o dedupe com o detector
    nativo não casa e a corroboração — ×1.15 no scoring — nunca acontece.
    """

    def test_caminho_relativo_e_ancorado_no_repo_e_nao_na_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "alvo"
            (repo / "app").mkdir(parents=True)
            (repo / "app" / "x.py").write_text("x = 1\n", encoding="utf-8")
            for entrada in ("./app/x.py", "app/x.py"):
                self.assertEqual(relative(entrada, repo), "app/x.py")

    def test_caminho_absoluto_continua_funcionando(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "alvo"
            (repo / "app").mkdir(parents=True)
            alvo = repo / "app" / "x.py"
            alvo.write_text("x = 1\n", encoding="utf-8")
            self.assertEqual(relative(alvo, repo), "app/x.py")

    def test_caminhos_equivalentes_dedupam(self):
        """A prova do impacto: mesmo ponto por duas fontes = um achado."""
        findings, _, _ = normalize(
            [
                raw("native-ast", "weak-hash", "app/x.py", 10),
                raw("bandit", "B324", "app/x.py", 10),
            ],
            TAXONOMY,
            PROFILE,
        )
        self.assertEqual(len(findings), 1)
        self.assertTrue(findings[0].corroborated)


class TestFiltroDeRuidoPhpstan(unittest.TestCase):
    """
    O alvo PHP é analisado sem `composer install` (mount read-only), então o
    phpstan não enxerga o framework. Esses erros são de AMBIENTE, não débito.
    """

    def test_descarta_classe_de_terceiro_ausente(self):
        for msg in (
            r"Class Illuminate\Support\Facades\DB not found.",
            r"Call to method get() on an unknown class Illuminate\Http\Request.",
            r"Class Symfony\Component\Console\Command not found.",
        ):
            self.assertTrue(_is_environment_noise(msg), msg)

    def test_descarta_facade_sem_namespace(self):
        """`DB::select()` sem o framework carregado vira 'unknown class DB'."""
        self.assertTrue(
            _is_environment_noise("Call to static method select() on an unknown class DB.")
        )

    def test_descarta_helper_global_do_laravel(self):
        """Textos reais observados na execução no container."""
        for helper in ("now", "response", "redirect", "view", "bcrypt"):
            self.assertTrue(
                _is_environment_noise(f"Function {helper} not found."), helper
            )

    def test_descarta_membro_herdado_do_framework(self):
        """
        `SyncData::info()` vem de Illuminate\\Console\\Command; `Customer::$id`
        é atributo dinâmico do Eloquent. Sem as dependências, o phpstan não
        enxerga nenhum dos dois.
        """
        for msg in (
            "Call to an undefined method App\\Console\\Commands\\SyncData::info().",
            "Access to an undefined property App\\Models\\Customer::$id.",
        ):
            self.assertTrue(_is_environment_noise(msg), msg)

    def test_mantem_erro_real_do_projeto(self):
        """Erro sobre símbolo do próprio código não pode ser descartado."""
        for msg in (
            "Class App\\Services\\BillingService not found.",
            "Undefined variable: $total",
            "Function minha_funcao_inexistente not found.",
        ):
            self.assertFalse(_is_environment_noise(msg), msg)

    def test_mencionar_framework_sozinho_nao_basta(self):
        """
        Um erro legítimo em código que USA o framework deve passar. O filtro
        exige as duas condições: 'não encontrei' E namespace de terceiro.
        """
        self.assertFalse(
            _is_environment_noise(
                r"Parameter #1 $id of method Illuminate\Database\Query::find() "
                "expects int, string given."
            )
        )


class TestPhploc(unittest.TestCase):
    """
    phploc produz métricas de PROJETO, não achados por linha.

    Estes testes travam a decisão de modelagem: só `cyclomaticComplexity.maximum`
    vira achado, só acima do limiar, e ancorado em ".".
    """

    def test_extrai_complexidade_maxima_do_formato_aninhado(self):
        data = {
            "linesOfCode": 1840,
            "cyclomaticComplexity": {"average": 4.5, "maximum": 18},
        }
        self.assertEqual(_phploc_max_complexity(data), 18)

    def test_extrai_complexidade_maxima_do_formato_real_do_phploc_7(self):
        """
        Formato REAL medido no container (phploc 7.0.2), que não bate com o
        documentado no FERRAMENTAS.md. Prefere `methodCcnMax` a `classCcnMax`:
        é a métrica por função, comparável com o `radon cc` do lado Python.
        """
        data = {
            "ccn": 107,
            "classCcnAvg": 9.91,
            "classCcnMax": 36,
            "methodCcnAvg": 4.37,
            "methodCcnMax": 35,
        }
        self.assertEqual(_phploc_max_complexity(data), 35)

    def test_extrai_complexidade_maxima_de_outros_formatos_planos(self):
        self.assertEqual(
            _phploc_max_complexity({"maximumCyclomaticComplexity": 22}), 22
        )

    def test_ignora_metricas_que_nao_sao_debito(self):
        """
        Tamanho do projeto e média de complexidade NÃO devem virar achado:
        média esconde a distribuição e tamanho não é débito.
        """
        data = {"linesOfCode": 99999, "cyclomaticComplexity": {"average": 4.5}}
        self.assertIsNone(_phploc_max_complexity(data))

    def test_limiar_e_o_mesmo_do_resto_do_pipeline(self):
        """
        11 = piso do rank C do radon, já usado em três outros pontos. O phploc
        não introduz critério novo; corrobora o que já existe.
        """
        self.assertEqual(PhplocDetector.MIN_COMPLEXITY, 11)
        self.assertEqual(RadonDetector.MIN_RANK, "C")

    def test_achado_do_phploc_casa_com_a_taxonomia(self):
        """
        O `native_id` precisa casar com a entrada que JÁ existia em
        taxonomy.toml antes de o adapter ser escrito.
        """
        self.assertEqual(
            TAXONOMY.resolve("phploc", "cc-high"), "MAINT.HIGH_COMPLEXITY"
        )

    def test_achado_e_ancorado_no_repositorio_e_corrobora(self):
        """
        Ancorado em "." (propriedade do projeto), o achado entra no MESMO
        Finding dos detectores por arquivo — porque normalize() agrega por
        rule_id — e o resultado é corroboração, não um débito a mais.
        """
        entradas = [
            raw("php-native", "cc-rank-D", "app/Services/BillingService.php", 20),
            raw("phploc", "cc-high", ".", 0),
        ]
        findings, unmapped, _ = normalize(entradas, TAXONOMY, PROFILE)
        self.assertEqual(unmapped, [])
        self.assertEqual(len(findings), 1, "deveria ser UM débito, não dois")
        self.assertEqual(findings[0].rule_id, "MAINT.HIGH_COMPLEXITY")
        self.assertEqual(findings[0].sources, ("php-native", "phploc"))
        self.assertTrue(findings[0].corroborated)


if __name__ == "__main__":
    unittest.main()
