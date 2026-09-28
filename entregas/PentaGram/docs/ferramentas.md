# Guia Técnico — Ambiente de Análise Estática

> Referência para os participantes da hackathon.
> Todas as ferramentas já estão instaladas no container — não é necessário instalar nada além do Docker.

---

## Pré-requisitos

- [Docker](https://docs.docker.com/get-docker/) (versão 20+)
- [Docker Compose](https://docs.docker.com/compose/install/) (incluso no Docker Desktop)

Verifique:
```bash
docker --version      # Docker version 24.x.x
docker compose version  # Docker Compose version 2.x.x
```

---

## Subindo o ambiente

### 1. Build da imagem (primeira vez, ~3 minutos)

```bash
cd hackathon/analyzer-env
docker compose build
```

A imagem instala automaticamente: PHP 8.4, Composer, `phpstan`, `phploc`, `bandit`, `radon`, `pylint`, `semgrep` e `pydantic`.

### 2. Entrando no container

```bash
docker compose run --rm analyzer bash
```

Você estará em `/workspace/` com acesso a:

| Caminho | Conteúdo |
|---|---|
| `/repos/python/` | Repositório `bad-codebase-python` (read-only) |
| `/repos/php/` | Repositório `bad-codebase` PHP/Laravel (read-only, bônus) |
| `/workspace/` | Seu código — sincronizado com `analyzer-env/workspace/` no host |

> **Dica:** edite os arquivos fora do container com seu editor favorito. Eles aparecem automaticamente dentro do container via volume.

### 3. Encerrando

```bash
exit          # sai do bash, container é removido automaticamente (--rm)
```

---

## Ferramentas disponíveis

### bandit — Scanner de segurança Python

**Documentação:** [bandit.readthedocs.io](https://bandit.readthedocs.io/en/latest/)

Detecta vulnerabilidades de segurança comuns: SQL injection, senhas hardcoded, uso de algoritmos criptográficos fracos (MD5, SHA1), `eval()`, `subprocess` sem validação, `debug=True`, entre outros.

**Uso básico:**
```bash
bandit -r /repos/python
```

**Com output JSON (recomendado para o pipeline):**
```bash
bandit -r /repos/python/app -f json -o /workspace/bandit-output.json
```

**Filtrar por severidade (só HIGH e MEDIUM):**
```bash
bandit -r /repos/python/app -f json -l   # -l = low+, -ll = medium+, -lll = high+
```

**Exemplo de output JSON:**
```json
{
  "results": [
    {
      "filename": "/repos/python/app/everything.py",
      "line_number": 177,
      "issue_severity": "HIGH",
      "issue_confidence": "HIGH",
      "issue_text": "Use of weak MD5 hash for security.",
      "test_id": "B324",
      "issue_cwe": { "id": 327 }
    },
    {
      "filename": "/repos/python/app/everything.py",
      "line_number": 7,
      "issue_severity": "LOW",
      "issue_confidence": "MEDIUM",
      "issue_text": "Possible hardcoded password: '123456'",
      "test_id": "B105",
      "issue_cwe": { "id": 259 }
    }
  ]
}
```

**Campos úteis para o pipeline:** `filename`, `line_number`, `issue_severity`, `issue_text`, `test_id`, `issue_cwe.id`

---

### radon — Métricas de complexidade Python

**Documentação:** [radon.readthedocs.io](https://radon.readthedocs.io/en/latest/)

Calcula métricas de qualidade de código. A principal para este desafio é a **Complexidade Ciclomática (CC)**, que mede o número de caminhos independentes em uma função. Cada `if`, `elif`, `for`, `while`, `except`, `and`, `or` adiciona +1.

| CC | Rank | Interpretação |
|---|---|---|
| 1–5 | A | Simples |
| 6–10 | B | Moderada |
| 11–15 | C | Complexa |
| 16–20 | D | Alta — refatorar |
| 21–25 | E | Muito alta |
| 26+ | F | Inalterável sem reescrita |

**Uso básico:**
```bash
radon cc /repos/python/app
```

**Com output JSON:**
```bash
radon cc /repos/python/app -j -o /workspace/radon-cc.json
```

**Maintainability Index (MI):**
```bash
radon mi /repos/python/app -j -o /workspace/radon-mi.json
```

**Exemplo de output JSON (cc):**
```json
{
  "/repos/python/app/helpers/date_helper.py": [
    {
      "name": "handle_date",
      "type": "F",
      "complexity": 29,
      "rank": "F",
      "lineno": 14
    }
  ]
}
```

**Funções com maior CC no repositório (medido):**

| Função | CC | Rank |
|---|---|---|
| `handle_date` | 29 | F |
| `dashboard` | 16 | C |
| `send` (NotificationService) | 12 | C |
| `monthly` (ReportController) | 12 | C |
| `calculate_invoice` | 10 | B |

---

### pylint — Linter geral Python

**Documentação:** [pylint.readthedocs.io](https://pylint.readthedocs.io/en/stable/)

Detecta erros, code smells, variáveis não utilizadas, imports desnecessários, violações de convenção, duplicação e muito mais.

**Uso básico:**
```bash
pylint /repos/python/app
```

**Com output JSON:**
```bash
pylint /repos/python/app --output-format=json 2>/dev/null > /workspace/pylint-output.json
```

**Apenas warnings e erros (sem convenção):**
```bash
pylint /repos/python/app --output-format=json --disable=C,R 2>/dev/null > /workspace/pylint-output.json
```

**Exemplo de output JSON:**
```json
[
  {
    "type": "warning",
    "module": "app.everything",
    "path": "/repos/python/app/everything.py",
    "line": 79,
    "symbol": "unused-variable",
    "message": "Unused variable 'total_hours'"
  },
  {
    "type": "warning",
    "path": "/repos/python/app/everything.py",
    "line": 87,
    "symbol": "fixme",
    "message": "TODO: adicionar paginação aqui"
  }
]
```

**Campos úteis:** `type`, `path`, `line`, `symbol`, `message`

---

### semgrep — Análise semântica multi-linguagem

**Documentação:** [semgrep.dev/docs](https://semgrep.dev/docs/)

Detecta padrões de código usando regras escritas em YAML. Suporta Python e PHP com as mesmas regras quando usadas via `--config=auto`. Ideal para detectar padrões específicos como SQL injection via f-string ou credenciais hardcoded.

**Uso básico (regras automáticas):**
```bash
semgrep --config=auto /repos/python/app
```

**Com output JSON:**
```bash
semgrep --config=auto --json /repos/python/app > /workspace/semgrep-output.json
```

**Regras específicas de segurança OWASP:**
```bash
semgrep --config=p/owasp-top-ten --json /repos/python/app > /workspace/semgrep-owasp.json
```

**Analisar PHP também (bônus):**
```bash
semgrep --config=auto --json /repos/php/app > /workspace/semgrep-php.json
```

**Exemplo de output JSON:**
```json
{
  "results": [
    {
      "check_id": "python.lang.security.audit.formatted-sql-query",
      "path": "/repos/python/app/everything.py",
      "start": { "line": 113 },
      "extra": {
        "message": "Detected SQL statement formatted with user input.",
        "severity": "ERROR"
      }
    }
  ]
}
```

> **Nota:** semgrep pode demorar alguns minutos na primeira execução pois baixa regras da internet. Conexão necessária.

---

### phpstan — Análise estática PHP (bônus)

**Documentação:** [phpstan.org/user-guide](https://phpstan.org/user-guide/getting-started)

Detecta erros de tipo, chamadas a métodos/classes inexistentes, variáveis não definidas e outros problemas em código PHP sem executá-lo. Funciona em 10 níveis de rigor (0 = permissivo, 9 = máximo).

**Uso básico (nível padrão):**
```bash
phpstan analyse /repos/php/app
```

**Com output JSON:**
```bash
phpstan analyse --error-format=json --no-progress /repos/php/app > /workspace/phpstan-output.json
```

**Com nível específico:**
```bash
phpstan analyse --level=5 --error-format=json --no-progress /repos/php/app > /workspace/phpstan-output.json
```

**Exemplo de output JSON:**
```json
{
  "totals": { "errors": 0, "file_errors": 12 },
  "files": {
    "/repos/php/app/Console/Commands/SyncData.php": {
      "errors": 3,
      "messages": [
        {
          "message": "Class App\\Console\\Commands\\SyncData extends unknown class Illuminate\\Console\\Command.",
          "line": 10,
          "ignorable": true
        }
      ]
    }
  }
}
```

> **Nota:** o repositório PHP não tem as dependências do Laravel instaladas no container, então phpstan reportará erros de "classe não encontrada" para classes do framework. Filtre pelo path `/repos/php/app` e ignore erros de `extends unknown class Illuminate\*`.

---

### phpmetrics — Complexidade ciclomática por classe PHP (bônus)

**Documentação:** [phpmetrics.org](https://phpmetrics.org/)

Gera CC por classe (equivalente ao `radon cc` do Python), além de métricas de acoplamento, coesão e estimativa de bugs. É a ferramenta que permite comparar complexidade entre os dois repositórios com granularidade equivalente.

**Uso básico:**
```bash
phpmetrics /repos/php/app
```

**Com output JSON:**
```bash
phpmetrics --report-json=/workspace/output/phpmetrics.json /repos/php/app
```

**Lendo CC por classe em Python:**
```python
import json
from pathlib import Path

data = json.loads(Path("/workspace/output/phpmetrics.json").read_text())

classes = [
    (name, info["ccn"])
    for name, info in data.items()
    if isinstance(info, dict) and "ccn" in info
]
classes.sort(key=lambda x: -x[1])

print("CC por classe (PHP):")
for name, cc in classes:
    rank = "F" if cc > 25 else "D" if cc > 15 else "C" if cc > 10 else "B" if cc > 5 else "A"
    print(f"  CC={cc} ({rank})  {name}")
```

**Output real (medido):**

| Classe PHP | CC |
|---|---|
| `App\Helpers\DateHelper` | 36 |
| `App\Console\Commands\SyncData` | 20 |
| `App\Services\BillingService` | 16 |
| `App\Services\NotificationService` | 15 |
| `App\Http\Controllers\ReportController` | 15 |
| `App\Http\Controllers\EverythingController` | 13 |

---

### phploc — Métricas de tamanho e complexidade PHP (bônus)

**Documentação:** [github.com/sebastianbergmann/phploc](https://github.com/sebastianbergmann/phploc)

Gera métricas estáticas de um projeto PHP: linhas de código, número de classes/métodos, complexidade ciclomática média, acoplamento entre objetos.

**Uso básico:**
```bash
phploc /repos/php/app
```

**Com output JSON:**
```bash
phploc --log-json=/workspace/phploc-output.json /repos/php/app
```

**Exemplo de output JSON (campos principais):**
```json
{
  "linesOfCode": 1840,
  "logicalLinesOfCode": 620,
  "cyclomaticComplexity": {
    "average": 4.5,
    "maximum": 18
  },
  "methods": { "nonStaticMethods": 12 },
  "classes": { "average": { "length": 45 } }
}
```

---

## Rodando tudo de uma vez

Script de exemplo para coletar output de todas as ferramentas de uma vez:

```bash
# dentro do container
mkdir -p /workspace/output

bandit -r /repos/python/app -f json -q 2>/dev/null > /workspace/output/bandit.json
radon cc /repos/python/app -j 2>/dev/null > /workspace/output/radon-cc.json
radon mi /repos/python/app -j 2>/dev/null > /workspace/output/radon-mi.json
pylint /repos/python/app --output-format=json --disable=C 2>/dev/null > /workspace/output/pylint.json

echo "Ferramentas Python concluídas."
echo "Resultados em /workspace/output/"
ls -lh /workspace/output/
```

---

## Leitura dos JSONs em Python

```python
import json
from pathlib import Path

# bandit
bandit = json.loads(Path("/workspace/output/bandit.json").read_text())
for issue in bandit["results"]:
    print(f"[{issue['issue_severity']}] {issue['test_id']}: {issue['issue_text']}")
    print(f"  → {issue['filename']}:{issue['line_number']}")

# radon
radon = json.loads(Path("/workspace/output/radon-cc.json").read_text())
for filepath, funcs in radon.items():
    for f in funcs:
        if f["complexity"] > 10:
            print(f"CC={f['complexity']} ({f['rank']}) — {f['name']} em {filepath}:{f['lineno']}")

# pylint
pylint_data = json.loads(Path("/workspace/output/pylint.json").read_text())
for msg in pylint_data:
    if msg["type"] in ("warning", "error"):
        print(f"[{msg['symbol']}] {msg['path']}:{msg['line']} — {msg['message']}")
```

---

## IA no pipeline — Google Gemini (grátis)

**Por que Gemini?** É a única API de LLM com camada gratuita real: 15 req/min, 1 milhão de tokens/dia, sem cartão de crédito obrigatório.

### Setup (2 minutos, feito uma vez)

1. Acesse [aistudio.google.com](https://aistudio.google.com) com sua conta Google
2. Clique em **"Get API key"** → **"Create API key"**
3. Copie a chave gerada

```bash
# dentro do container, configure a variável de ambiente
export GOOGLE_API_KEY="sua-chave-aqui"

# ou adicione ao .env do workspace (não commite no repo)
echo 'GOOGLE_API_KEY=sua-chave-aqui' >> /workspace/.env
```

### Usando no pipeline

```python
import google.generativeai as genai
import os

genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
model = genai.GenerativeModel("gemini-1.5-flash")  # modelo grátis, rápido

def enrich_impact(finding: dict, business_context: str) -> str:
    """Usa Gemini para redigir o campo 'Impacto' em linguagem de negócio."""
    prompt = f"""
    Contexto da empresa: {business_context}
    
    Achado técnico: {finding['description']} (severidade: {finding['severity']})
    
    Escreva em 1-2 frases o impacto de negócio desse problema para o CEO da empresa.
    Seja direto e específico. Não use jargão técnico.
    """
    response = model.generate_content(prompt)
    return response.text.strip()
```

**Regra importante:** a IA enriquece **descrições** — não calcula prioridade. O scoring model deve ser determinístico (veja `scoring.py`).

### Validando que funciona

```bash
python3 -c "
import google.generativeai as genai, os
genai.configure(api_key=os.environ['GOOGLE_API_KEY'])
m = genai.GenerativeModel('gemini-1.5-flash')
print(m.generate_content('Responda: ok').text)
"
# deve imprimir: ok
```

---

## Comparação entre os repositórios

Os dois repositórios implementam o mesmo sistema com os mesmos débitos intencionais. A tabela abaixo mostra a equivalência de classes/funções e a CC medida em cada linguagem.

### Complexidade Ciclomática — Python (`radon`) vs PHP (`phpmetrics`)

| Componente | Função/Classe Python | CC Python | Classe PHP | CC PHP |
|---|---|---|---|---|
| Helper de datas | `handle_date()` | **29 (F)** | `DateHelper` | **36 (F)** |
| Dashboard principal | `dashboard()` | **16 (D)** | `EverythingController` | **13 (C)** |
| Relatório | `monthly()` | **12 (C)** | `ReportController` | **15 (D)** |
| Faturamento | `calculate_invoice()` | **10 (B)** | `BillingService` | **16 (D)** |
| Notificações | `send()` | **12 (C)** | `NotificationService` | **15 (D)** |
| Sync/integração | `sync_from_erp()` | — (arquivo) | `SyncData` | **20 (D)** |

> **Nota:** PHP usa CC por classe (soma de todos os métodos), Python usa CC por função. Para comparações rigorosas, use semgrep que tem o mesmo schema nas duas linguagens.

### Vulnerabilidades de segurança — `semgrep` (Python e PHP)

```bash
# Python
semgrep --config=p/owasp-top-ten --json /repos/python/app > /workspace/output/semgrep-python.json

# PHP (bônus)
semgrep --config=p/owasp-top-ten --json /repos/php/app > /workspace/output/semgrep-php.json

# comparar contagem
python3 -c "
import json
py = json.load(open('/workspace/output/semgrep-python.json'))
php = json.load(open('/workspace/output/semgrep-php.json'))
print(f'Python: {len(py[\"results\"])} achados')
print(f'PHP:    {len(php[\"results\"])} achados')
"
```

---

## Links de referência

| Ferramenta | Documentação oficial | Regras / Checks |
|---|---|---|
| bandit | [bandit.readthedocs.io](https://bandit.readthedocs.io/en/latest/) | [Lista de checks](https://bandit.readthedocs.io/en/latest/plugins/index.html) |
| radon | [radon.readthedocs.io](https://radon.readthedocs.io/en/latest/) | [Métricas explicadas](https://radon.readthedocs.io/en/latest/intro.html) |
| pylint | [pylint.readthedocs.io](https://pylint.readthedocs.io/en/stable/) | [Mensagens disponíveis](https://pylint.readthedocs.io/en/stable/user_guide/messages/messages_overview.html) |
| semgrep | [semgrep.dev/docs](https://semgrep.dev/docs/) | [Registry de regras](https://semgrep.dev/r) |
| phpstan | [phpstan.org](https://phpstan.org/user-guide/getting-started) | [Níveis explicados](https://phpstan.org/user-guide/rule-levels) |
| phpmetrics | [phpmetrics.org](https://phpmetrics.org/) | [Métricas disponíveis](https://phpmetrics.org/page/documentation/) |
| phploc | [github.com/sebastianbergmann/phploc](https://github.com/sebastianbergmann/phploc) | — |
| CWE (vulnerabilidades) | [cwe.mitre.org](https://cwe.mitre.org/) | [Top 25 CWEs](https://cwe.mitre.org/top25/) |
| OWASP Top 10 | [owasp.org/Top10](https://owasp.org/www-project-top-ten/) | — |
