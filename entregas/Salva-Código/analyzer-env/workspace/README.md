# Analyzer — Gerador de Relatório de Débitos Técnicos

## Como usar o ambiente

```bash
# na pasta analyzer-env/
docker compose build    # primeira vez (pode demorar ~2 min)
docker compose run --rm analyzer bash
```

Dentro do container você terá disponível:

| Ferramenta | Linguagem | Comando |
|---|---|---|
| `bandit` | Python | `bandit -r /repos/python -f json` |
| `radon` | Python | `radon cc /repos/python -j` |
| `pylint` | Python | `pylint /repos/python --output-format=json` |
| `semgrep` | Python + PHP | `semgrep --config=auto --json /repos/python` |
| `phpstan` | PHP | `phpstan analyse --error-format=json /repos/php` |
| `phploc` | PHP | `phploc --log-json=/tmp/phploc.json /repos/php` |

Os repositórios estão montados em:
- `/repos/python` — bad-codebase-python (Python/Flask)
- `/repos/php` — bad-codebase (PHP/Laravel) *(bônus)*

Seu código fica em `/workspace/` (esta pasta), que é compartilhada com o host — edite com seu editor favorito fora do container e rode dentro.

## Estrutura sugerida do projeto

```
workspace/
├── main.py              # entry point
├── models.py            # dataclass Finding
├── scoring.py           # scoring model determinístico
├── report.py            # gerador de Markdown/JSON
├── detectors/
│   ├── __init__.py
│   ├── python.py        # invoca bandit/radon/pylint
│   └── php.py           # invoca phpstan/phploc (bônus)
└── tests/
    └── test_scoring.py
```

## Exemplo mínimo para começar

```python
# main.py
import subprocess, json, sys

repo_path = sys.argv[1]

# roda bandit e imprime os achados
result = subprocess.run(
    ["bandit", "-r", repo_path, "-f", "json"],
    capture_output=True, text=True
)
data = json.loads(result.stdout)
for issue in data["results"]:
    print(f"[{issue['issue_severity']}] {issue['issue_text']} — {issue['filename']}:{issue['line_number']}")
```

```bash
python main.py /repos/python
```

## Lembre-se

- O scoring model precisa ser **determinístico** — leia o `business-context.md` para entender as pressões que devem influenciar a priorização
- Não use LLM para calcular prioridade — use para enriquecer descrições se quiser
- Inclua testes unitários para o scoring model
