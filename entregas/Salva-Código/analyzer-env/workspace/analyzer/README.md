# Radar de Débitos Técnicos — Pipeline

Analisa um repositório, normaliza os achados num formato único e os **prioriza
com um scoring determinístico** derivado do contexto de negócio da HourTrack.

Gera `report.json` (canônico) e `report.md` (derivado do JSON).

---

## Como rodar

Requer **apenas Python 3.11+**. Nenhuma dependência precisa ser instalada.

### No container do desafio (todas as 7 ferramentas disponíveis)

```bash
cd analyzer-env
docker compose run --rm analyzer bash -lc '
  cd /workspace &&
  python -m analyzer /repos/python --out /workspace/out/python &&
  python -m analyzer /repos/php    --out /workspace/out/php'
```

### No host (sem ferramentas externas — o pipeline degrada, não quebra)

```bash
cd analyzer-env/workspace
python -m analyzer ../../bad-codebase-python --out ./out/python
python -m analyzer ../../bad-codebase        --out ./out/php

# força o caminho nativo mesmo com ferramentas instaladas
python -m analyzer ../../bad-codebase-python --no-external

# com IA: enriquece o campo "Impacto" e roda a auditoria IA vs. ferramentas
export GOOGLE_API_KEY="sua-chave"
python -m analyzer ../../bad-codebase-python --enrich --ai-audit
```

Testes (rodam igual no host e no container):

```bash
python -m unittest discover -s analyzer/tests -t .
```

Escritos em `unittest` (stdlib) de propósito — pytest pode não estar instalado
no ambiente de avaliação, e teste que não roda não prova nada.

---

## Resultados medidos

Executado no container oficial do `analyzer-env`, com as sete ferramentas
instaladas:

| Alvo | Ferramentas ativas | Achados brutos | Débitos | Corroborados |
|---|---|---:|---:|---:|
| `bad-codebase-python` | native-ast, bandit, radon, pylint | 149 | 22 | 9 |
| `bad-codebase` (bônus) | php-native, phpstan, phpmetrics, phploc | 52 | 10 | 1 |

### Degradação graciosa — o mesmo pipeline com 0 e com 4 ferramentas

| | Brutos | Débitos | Corroborados | Críticos |
|---|---:|---:|---:|---:|
| `--no-external` | 85 | 21 | 0 | 4 |
| completo | 149 | 22 | 9 | 4 |

**Nenhum tipo de débito é perdido ao desligar as ferramentas externas.** Elas
adicionam uma regra (`DESIGN.SILENT_FAILURE`, via pylint) e, sobretudo,
*confirmam* o que o detector nativo já via — o que eleva os scores pela regra
de corroboração:

```
SEC.SQLI              436 -> 496   (bandit confirma 6 dos 7 pontos)
SEC.HARDCODED_SECRET  269 -> 306
SEC.WEAK_HASH         180 -> 207
```

`MAINT.HIGH_COMPLEXITY` no alvo Python é confirmado por **três** fontes
independentes (`native-ast`, `pylint`, `radon`); no alvo PHP, também por três
(`php-native`, `phpmetrics`, `phploc`).

### Opções

| Flag | Efeito |
|---|---|
| `--out DIR` | diretório de saída (padrão `./out`) |
| `--language python\|php` | força a linguagem em vez de detectar |
| `--no-external` | ignora bandit/radon/pylint/phpstan; só detectores nativos |
| `--with-semgrep` | inclui semgrep (requer rede — ver "Determinismo") |
| `--enrich` | LLM redige o campo Impacto (nunca altera prioridade) |
| `--ai-audit` | compara achados da IA com os do pipeline |
| `--fail-on critica\|alta` | exit code 1 se houver débito nessa prioridade (gate de CI) |

---

## Arquitetura

```
repo ──▶ [detectar linguagem] ──▶ [detectores: nativos + externos]
                                            │
                                    List[RawFinding]
                                            │
                                [normalizar + dedupe]  ◀── config/taxonomy.toml
                                            │
                                     List[Finding]        ═══ fronteira
                                            │                 determinística
                              [scoring]  ◀── config/business_profile.toml
                                            │
                                  List[ScoredFinding]
                                       │         │
                         [enriquecer (LLM)]      │  ← só texto, nunca score
                                       │         │
                                   [report] ──▶ report.md + report.json
```

| Arquivo | Responsabilidade |
|---|---|
| `main.py` | CLI e orquestração das 5 etapas |
| `models.py` | `RawFinding`, `Finding`, `ScoredFinding` — o contrato |
| `detectors/python_native.py` | AST puro, sem dependências — **sempre roda** |
| `detectors/python_external.py` | bandit, radon, pylint, semgrep (opcionais) |
| `detectors/php.py` | detector nativo PHP + phpstan/phpmetrics (bônus) |
| `detectors/registry.py` | detecção de linguagem e orquestração |
| `normalize.py` | taxonomia, dedupe e agregação por padrão |
| `scoring.py` | **modelo determinístico** — sem I/O, sem rede, sem relógio |
| `enrich.py` | único módulo que pode chamar LLM |
| `ai_audit.py` | comparação IA × ferramentas |
| `report.py` | renderização JSON + Markdown |
| `config/*.toml` | contexto de negócio e taxonomia, como **dado** |

### Três decisões que definem o resto

**1. Ferramentas externas são opcionais, não dependências.**
O README do desafio avisa que bandit/radon/pylint podem não existir no ambiente
de avaliação — e de fato não existiam no nosso. Por isso cada detector externo
é um adapter que declara `is_available()`, e existe uma camada nativa em `ast`
que cobre as mesmas classes de achado. A política não é "externo *ou* nativo",
é **"nativo sempre, externo enriquece"**: quando as ferramentas estão presentes
elas *corroboram* os achados nativos, e a corroboração entra no scoring como
sinal de confiança contra falso positivo.

O detector nativo chega aos mesmos números do radon: `handle_date` CC 29 (F),
`dashboard` CC 16, `send` CC 12 — conferidos contra os valores medidos em
`analyzer-env/workspace/FERRAMENTAS.md` e travados num teste.

**2. `Finding` não sabe de linguagem.**
É o que o bônus PHP realmente testa. O scoring opera sobre `rule_id`
canônicos (`SEC.SQLI`), nunca sobre `B608` do bandit ou `check_id` do semgrep.
A tradução acontece só no adapter, via `config/taxonomy.toml`. Resultado
verificável: SQL Injection pontua **436 nos dois repositórios**, e `PERF.NPLUS1`
pontua 65 nos dois — o mesmo modelo, sem um `if language ==` em lugar nenhum.

**3. Agregação por padrão, não por linha.**
6 SQL Injections em 4 arquivos viram **um** débito (DT-01) com 6 ocorrências,
não 6 itens. O relatório é para alguém decidir alocação de 6 SP/semana, não
para listar linhas — e "dump bruto de ferramentas sem processamento" é
penalizado explicitamente no briefing.

---

## O scoring model

```
score = base(severidade) × Π(multiplicadores) + Σ(bônus) − penalidade_esforço
```

**Base:** Crítica 100 · Alta 60 · Média 30 · Baixa 10

**Multiplicadores** (cada um rastreável ao `business-context.md`):

| Regra | Fator | Justificativa |
|---|:---:|---|
| `questionario_seguranca` | ×1.8 | Responde a uma das 7 perguntas do cliente enterprise. 30 dias, R$ 8.000/mês, dobra o MRR. |
| `isolamento_multi_tenant` | ×1.6 | Permite ler/apagar dados de outro cliente. 47 clientes na mesma base, risco de processo. |
| `caminho_da_release` | ×1.4 | Arquivo que a v2.1 já vai tocar em 14 dias — custo marginal baixo. |
| `corroboracao` | ×1.15 | 2+ ferramentas independentes confirmaram. |
| `fonte_unica_nao_seguranca` | ×0.9 | Uma só fonte, fora de Segurança — desconto de confiança. |

**Bônus:** `bus_factor` +25 (o dev sai em 6 semanas) · `padrao_sistemico` +20
(3+ ocorrências) · `risco_perda_de_dados` +20 (sem backup, sem staging).

**Penalidade de esforço** — a única regra que reduz prioridade:

```
penalidade = 0                      se SP ≤ 3
penalidade = (SP − 3) × 4,  teto 35
```

A capacidade real é 6 SP/semana; até a release v2.1 há ~12 SP, e ela não pode
atrasar. Item caro compete com uma entrega já prometida.

**Cortes:** ≥140 Crítica · ≥90 Alta · ≥50 Média · <50 Baixa

### Os dois eixos

Prioridade responde *quão importante*; **janela** responde *quando cabe*. São
independentes de propósito — "Crítico mas não cabe antes da release" é
informação, não contradição. As três ondas do plano saem daí, calculadas:

| Janela | Critério |
|---|---|
| `pre-release` | score ≥ 90 **e** ≤ 3 SP — cabe nos ~12 SP até a v2.1 |
| `sprint-seguranca-30d` | responde ao questionário; ou é Crítico e caro; ou é Segurança barata |
| `pos-v2.1` | o resto — adiado de forma consciente e registrada |

### A regra mais contestável

O **teto de 35** na penalidade de esforço é deliberado e discutível. Sem ele,
um item de 13 SP perderia para trivialidades e o modelo recomendaria remover
variável não usada antes de corrigir SQL Injection. Com ele, esforço **nunca
zera** um achado crítico — SQL Injection continua Crítica mesmo custando 21 SP
(há um teste para isso).

O que o esforço muda de fato é a **janela**, não a prioridade. Um avaliador
pode argumentar que penalizar esforço enviesa contra correções estruturais;
a defesa é o teto somado ao segundo eixo, e está registrada aqui de propósito.

---

## Determinismo

Rodado duas vezes no mesmo repositório, produz **bytes idênticos** —
verificado por hash SHA-256 de `report.json` e `report.md`.

Como isso é garantido:

- **Sem relógio.** Os prazos vêm do `business_profile.toml` como *dias
  restantes* fixos, nunca de `datetime.now()`. Um teste varre a AST de
  `scoring.py` e falha se aparecer qualquer chamada a relógio — é o erro mais
  fácil de cometer neste desafio ("faltam 14 dias" calculado pelo calendário
  muda o score amanhã).
- **Sem float acumulado.** `Decimal` com quantização explícita; o score é `int`.
- **Ordenação por chave total** — `(-score, rule_id, arquivo, linha)`. Empate
  nunca cai na ordem de descoberta do sistema de arquivos.
- **Paths relativos** ao repo, com separador POSIX.
- **Sem timestamp no relatório**, justamente para não quebrar a comparação.
- `pylint` roda com `--persistent=n --jobs=1` (cache e paralelismo alterariam
  a saída entre execuções).
- `semgrep` fica atrás de um flag: `--config=auto` baixa regras da internet e
  tornaria o resultado dependente de rede.

**A IA não participa do cálculo.** `enrich.py` roda *depois* do scoring e sua
função recebe um `ScoredFinding` e devolve `str` — é incapaz de alterar score,
prioridade ou ordem. Sem `--enrich`, o pipeline nunca importa nada de rede: o
campo Impacto vem de templates determinísticos e o relatório sai completo.
Todo texto de LLM é marcado com `impact_source: "llm"` no JSON, e fica em cache
em disco para que duas execuções com `--enrich` também produzam o mesmo arquivo.

---

## Contra falso positivo

Falso positivo desconta pontos no desafio, então o pipeline é conservador:

- **Achado fora da taxonomia é descartado**, não recebe categoria genérica.
  Fica visível em `unmapped_findings` no JSON: o pipeline **viu** tudo e
  **escolheu** o que reportar. No alvo Python são 18 achados (avisos de estilo
  do pylint) conscientemente não promovidos a débito.
- **SQLi exige valor interpolado não confiável.** `f'DELETE FROM {TABLE_MAP[thing]}'`
  em `everything.py:205` **não** é reportado: o valor vem de um dicionário
  constante, cujos valores são literais. Um `thing` malicioso causa `KeyError`,
  não injeção.
- **Supressões auditadas.** O bandit reporta aquele mesmo ponto como B608 —
  ele não faz análise de fluxo de dados. A lista `[[suppressions]]` em
  `config/taxonomy.toml` deixa a análise mais precisa prevalecer, **com
  justificativa escrita**, e os achados suprimidos vão para
  `suppressed_findings` no JSON. Suprimir em silêncio seria indistinguível de
  não detectar — e permitiria esconder achado inconveniente.
- **Ruído de ambiente do phpstan é filtrado.** O alvo PHP é analisado sem
  `composer install` (mount read-only), então o phpstan não enxerga o Laravel:
  `Function now not found`, `unknown class DB`, `SyncData::info()`. São 4
  formas de ruído, todas observadas na execução real, que somavam 46
  ocorrências e viravam um débito fantasma. Filtradas, resta 1 achado legítimo.
- **Segredo exige valor literal substancial.** `API_KEY = os.environ[...]` e
  placeholders (`changeme`, string vazia) não contam.
- **Dependências de terceiros são excluídas** (`vendor/`, `node_modules/`), com
  a lista derivada do mesmo `SKIP_DIRS` que os detectores nativos usam.
- **Corroboração entra no score**, e a falta dela desconta — exceto em achados
  que nenhuma ferramenta poderia confirmar (ausência de testes, banco
  commitado), onde descontar seria punir por evidência impossível.

### O pipeline nunca escreve no repositório que analisa

phpmetrics e phploc gravam relatório em arquivo; ambos os adapters usam
`tempfile`, nunca o diretório do alvo. Verificado no container: após analisar
os dois repositórios montados read-only, nada foi modificado neles.

---

## Limitações conhecidas

- O detector PHP usa **regex**, não AST — mais fraco que o lado Python. A
  contrapartida é que o bônus funciona sem PHP instalado. Ele não detecta hoje
  os `catch` que capturam e apenas registram em log com múltiplas instruções
  no corpo.
- **O `FERRAMENTAS.md` documenta um formato de saída do phploc que não
  corresponde à versão instalada** (7.0.2). O real usa chaves planas
  (`methodCcnMax`, `classCcnMax`), não `cyclomaticComplexity.maximum`. O
  adapter aceita ambos; sem isso ele devolveria "0 achados" silenciosamente.
- O `phpmetrics` identifica a unidade pelo nome da classe e **não devolve o
  caminho do arquivo**. O caminho é derivado do namespace pela convenção PSR-4
  (`App\Helpers\DateHelper` → `app/Helpers/DateHelper.php`) e só é usado se o
  arquivo existir de fato.
- O filtro de ruído do phpstan descarta `Call to an undefined method` em
  classes `App\` — em tese isso poderia esconder um erro real de digitação.
  Sem as dependências instaladas é **impossível** distinguir os dois casos, e
  reportar ~30 falsos positivos para talvez pegar um real é o pior negócio num
  desafio que penaliza falso positivo. Rodar `composer install` no alvo
  resolveria — mas o mount é read-only, por design.
- A estimativa de esforço é por padrão, com crescimento sublinear no número de
  ocorrências. É uma heurística explícita (`normalize._scaled_effort`), não uma
  medição.
- `semgrep` está instalado no container mas fica **desligado por padrão**:
  `--config=auto` baixa regras da internet, tornando o resultado dependente de
  rede e, portanto, não reprodutível. Disponível via `--with-semgrep`.
