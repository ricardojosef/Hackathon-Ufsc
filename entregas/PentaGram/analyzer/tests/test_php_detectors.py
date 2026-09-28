import unittest

from detectors.php import parse_phpmetrics, parse_phpstan
from models import FindingKind


# Fixtures inline, com a forma real do JSON das ferramentas.
#
# A versao anterior deste teste lia phpstan.json/phpmetrics.json de
# Hackathon-Ufsc-main/analyzer-env/workspace/output/ -- um diretorio de ZIP que
# nao esta versionado (output/ e gitignored) e que foi removido do repo. O teste
# falhava para qualquer pessoa que nao tivesse aquele diretorio local.
#
# Trade-off: as contagens exatas da rodada real (90 findings do phpstan, 12
# classes do phpmetrics, ccn maximo 36) foram perdidas. Para recupera-las como
# regressao, commite a saida real em analyzer/tests/fixtures/ depois de rodar as
# ferramentas no container.
PHPSTAN_JSON = {
    "totals": {"errors": 0, "file_errors": 3},
    "files": {
        "/repos/php/app/Console/Commands/SyncData.php": {
            "errors": 2,
            "messages": [
                {
                    "message": "Class App\\Console\\Commands\\SyncData extends unknown class Illuminate\\Console\\Command.",
                    "line": 9,
                    "identifier": "class.notFound",
                    "ignorable": True,
                },
                {
                    "message": "Call to an undefined method SyncData::info().",
                    "line": 42,
                    "identifier": "method.notFound",
                    "ignorable": True,
                },
            ],
        },
        "/repos/php/app/Services/BillingService.php": {
            "errors": 1,
            "messages": [
                {
                    "message": "Binary operation \"*\" between string and int results in an error.",
                    "line": 58,
                    "identifier": "binaryOp.invalid",
                    "ignorable": True,
                }
            ],
        },
    },
}

PHPMETRICS_JSON = {
    "App\\Helpers\\DateHelper": {
        "_type": "Hal\\Metric\\ClassMetric",
        "name": "App\\Helpers\\DateHelper",
        "ccn": 36,
    },
    "App\\Services\\BillingService": {
        "_type": "Hal\\Metric\\ClassMetric",
        "name": "App\\Services\\BillingService",
        "ccn": 16,
    },
    # Agregados nao tem arquivo/linha concretos: nao viram debito
    "App\\Services": {"_type": "Hal\\Metric\\PackageMetric", "name": "App\\Services", "ccn": 52},
    "project": {"_type": "Hal\\Metric\\ProjectMetric", "ccn": 120},
    # Classe sem ccn numerico e ignorada
    "App\\Models\\User": {"_type": "Hal\\Metric\\ClassMetric", "name": "App\\Models\\User", "ccn": None},
}


class PhpStanTests(unittest.TestCase):
    def test_messages_become_findings_with_file_and_line(self):
        findings = parse_phpstan(PHPSTAN_JSON)
        self.assertEqual(len(findings), 3)
        self.assertEqual({item.source_tool for item in findings}, {"phpstan"})
        primeiro = findings[0]
        self.assertEqual(primeiro.file_path, "/repos/php/app/Console/Commands/SyncData.php")
        self.assertEqual(primeiro.line, 9)
        self.assertEqual(primeiro.rule_id, "class.notFound")

    def test_dependency_errors_are_environmental_not_correctness(self):
        """phpstan sem as deps do Laravel reporta 'classe nao encontrada'.

        Isso e artefato do ambiente de analise, nao debito do codigo -- e o
        docs/ferramentas.md avisa exatamente sobre isso.
        """

        por_regra = {item.rule_id: item.category for item in parse_phpstan(PHPSTAN_JSON)}
        self.assertEqual(por_regra["class.notFound"], "environmental")
        self.assertEqual(por_regra["method.notFound"], "environmental")
        # erro real de tipo continua sendo correctness
        self.assertEqual(por_regra["binaryOp.invalid"], "correctness")

    def test_missing_files_object_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_phpstan({})

    def test_messages_without_identifier_are_rejected(self):
        with self.assertRaises(ValueError):
            parse_phpstan({"files": {"a.php": {"messages": [{"message": "x", "line": 1}]}}})


class PhpMetricsTests(unittest.TestCase):
    def test_only_class_metrics_become_findings(self):
        findings = parse_phpmetrics(PHPMETRICS_JSON)
        self.assertEqual(len(findings), 2)
        self.assertEqual({item.source_tool for item in findings}, {"phpmetrics"})
        self.assertTrue(all(item.kind == FindingKind.METRIC for item in findings))
        self.assertEqual(max(item.metric_value for item in findings), 36)

    def test_aggregates_and_missing_ccn_are_skipped(self):
        nomes = {item.description for item in parse_phpmetrics(PHPMETRICS_JSON)}
        self.assertFalse(any("App\\Services:" in nome for nome in nomes))
        self.assertFalse(any("User" in nome for nome in nomes))

    def test_empty_input_is_not_an_error(self):
        self.assertEqual(parse_phpmetrics({}), [])


if __name__ == "__main__":
    unittest.main()
