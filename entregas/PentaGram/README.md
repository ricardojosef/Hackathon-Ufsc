# Hackathon AI 2026 — Radar de Débitos Técnicos

Pipeline de análise estática que varre um repositório legado, normaliza os achados de
várias ferramentas em um formato único e prioriza os débitos técnicos **contra o
contexto de negócio** da empresa fictícia do desafio.

Este é o repositório de trabalho do time. O material oficial da hackathon
(briefing, código-alvo, ambiente) foi importado para cá — veja
[`docs/UPSTREAM.md`](docs/UPSTREAM.md) para procedência e como sincronizar.

---

## Leia antes de codar

Nessa ordem:

1. **[`docs/cenario-do-desafio.md`](docs/cenario-do-desafio.md)** — o briefing. Entregas
   obrigatórias, critérios de avaliação e **penalidades**.
2. **[`docs/business-context.md`](docs/business-context.md)** — a situação da HourTrack.
   Isto não é enfeite: são os pesos do `scoring.py`.
3. **[`docs/security-questionnaire.md`](docs/security-questionnaire.md)** — as 7 perguntas
   do cliente enterprise. Cada achado que responde "não" a uma delas vale dinheiro.
4. **[`docs/ferramentas.md`](docs/ferramentas.md)** — schema do JSON de saída de cada
   ferramenta, com exemplos reais. Consulta obrigatória ao escrever os `detectors/`.

---

## Ambiente

**Use o Docker.** É o caminho suportado.

```bash
cp .env.example .env                    # opcional, só para o enriquecimento via Gemini
docker compose build                    # primeira vez, ~3 min
docker compose run --rm analyzer bash   # shell com todas as ferramentas
```

Dentro do container:

| Caminho | Conteúdo |
|---|---|
| `/workspace` | este repositório (leitura/escrita, sincronizado com o host) |
| `/repos/python` | `fixtures/bad-codebase-python` — alvo principal (read-only) |
| `/repos/php` | `fixtures/bad-codebase` — alvo do bônus (read-only) |

Os alvos ficam nos mesmos paths do ambiente oficial da organização, de propósito:
todos os comandos de exemplo do `docs/ferramentas.md` funcionam colando direto.

Edite os arquivos no host com seu editor; rode dentro do container.

**Não rode as ferramentas de análise no host.** A imagem é Python 3.11, que é o que
os pins do `requirements.txt` esperam. No 3.14 do host, `pydantic==2.8.2` nem instala
e `bandit==1.7.9` falha de um jeito silencioso (detalhe em "Pegadinhas" abaixo).
Dentro do container, nada disso acontece.

O `README` anterior pedia `Python 3.14` + venv local. Trocado por container por isso —
se alguém quiser um venv só para autocomplete do editor, beleza, mas qualquer número
que entre no relatório sai do container.

Conclusão: use o container para qualquer número que entre no relatório. Um venv
local serve para autocomplete e `pytest` do scoring — não para rodar as ferramentas.

### Verificação do ambiente (rodar uma vez, antes de codar)

A imagem **não foi buildada ainda** — o ambiente onde o material foi importado não
tinha acesso de rede para os containers. Quem tiver rede, rode:

```bash
docker compose build                    # ~3 min: apt + composer + pip
docker compose run --rm analyzer bash
```

Já dentro do container, o smoke test que importa — as três ferramentas devem
achar coisa, e o bandit **não pode** voltar vazio:

```bash
# 1. as ferramentas existem?
bandit --version && radon --version && pylint --version && semgrep --version
phpstan --version && phpmetrics --version   # bônus

# 2. bandit acha vulnerabilidade? (DEVE ser > 0 — se vier 0, algo está errado)
bandit -r /repos/python/app -f json -q 2>/dev/null \
  | python3 -c "import json,sys; r=json.load(sys.stdin)['results']; print(f'bandit: {len(r)} achados'); assert r, 'BANDIT VAZIO - nao confie neste ambiente'"

# 3. radon reproduz a tabela do docs/ferramentas.md?
#    esperado: handle_date=29, dashboard=16, send=12, monthly=12, calculate_invoice=10
radon cc /repos/python/app -s -n B

# 4. pylint roda?
pylint /repos/python/app --output-format=json --disable=C 2>/dev/null \
  | python3 -c "import json,sys; print(f'pylint: {len(json.load(sys.stdin))} mensagens')"
```

O passo 2 é o que protege contra o modo de falha silenciosa descrito acima.
Se ele passar no container, o ambiente está confiável.

---

## Estrutura

```
.
├── docs/           material oficial importado (não editar — ver UPSTREAM.md)
├── fixtures/       os dois códigos-alvo (não editar, não consertar — ver fixtures/README.md)
├── docker/         Dockerfile do ambiente de análise
├── requirements.txt
└── (o pipeline entra aqui)
```

O pipeline ainda não existe — o repositório está com o material pronto e o
ambiente funcionando. A estrutura que o **briefing pede** (`cenario-do-desafio.md`,
seção "Estrutura esperada do gerador") é:

```
analyzer/
├── main.py              # entry point: recebe path do repo, orquestra o pipeline
├── detectors/
│   ├── python.py        # invoca bandit/radon/pylint → lista de Finding
│   └── php.py           # invoca phpstan/phploc (bônus)
├── models.py            # dataclass Finding com campos normalizados
├── scoring.py           # scoring model determinístico
├── report.py            # renderiza Markdown e JSON
└── tests/
    └── test_scoring.py  # testes unitários do scoring model
```

Fica a critério do time seguir isso à risca ou não — mas divergir do que o
briefing descreve é uma escolha que vale explicar no README final.

---

## Restrições do desafio que afetam o design

Extraídas do briefing — vale reler antes de abrir PR:

- **Scoring determinístico.** Duas execuções no mesmo alvo, mesmo resultado.
  Pipeline não determinístico é *desclassificado como entrega técnica*.
- **LLM não decide prioridade.** IA pode redigir descrição e impacto; detecção e
  priorização são computadas pelo pipeline.
- **As ferramentas podem não estar instaladas no ambiente de avaliação.** O pipeline
  precisa de um caminho que funcione sem `bandit`/`radon`/`pylint` — degradar com
  elegância, não estourar exceção. **E "saiu com código 0" não prova que a ferramenta
  rodou:** o bandit consegue falhar em todos os arquivos, sair 0 e devolver
  `"results": []` (vimos acontecer — ver "Pegadinhas"). Zero achado de segurança é um
  resultado extraordinário num código propositalmente ruim; o pipeline devia
  desconfiar dele, não reportá-lo. Cheque também os arquivos que a ferramenta pulou.
- **Falso positivo desconta ponto.** Reportar como débito algo que não é problema
  real custa nota. Menos achados bem justificados > muitos achados.
- **As regras de priorização vão no código**, comentadas ou em arquivo de config —
  não só no relatório.

---

## Pegadinhas

Encontradas validando o material importado. Ambas afetam o scoring.

### 1. O `rank` do radon não bate com a tabela do briefing

Verificado rodando radon no fixture. A escala real do radon é `A:1-5, B:6-10,
C:11-20, D:21-30, E:31-40, F:41+` — diferente da tabela do `docs/ferramentas.md`
(`C:11-15, D:16-20, E:21-25, F:26+`). E o próprio doc é inconsistente: lista
`dashboard` (CC=16) como `C` em uma tabela e `D` em outra.

Exemplo concreto: `handle_date` tem CC=29. O radon devolve `"rank": "D"`; a tabela
do briefing diria `F`.

Se o `scoring.py` consumir o campo `rank` do JSON do radon direto, a severidade não
vai corresponder ao que o briefing descreve. Decidam qual escala usar, **derivem o
rank do `complexity` numérico** em vez de confiar no campo, e documentem a escolha —
é exatamente o tipo de decisão explícita que os 25% de "regras justificadas" premiam.

### 2. O bandit sabe falhar sem falhar

Rodando no host (Python 3.14, fora do container): o `bandit==1.7.9` estoura
`AttributeError: 'Constant' object has no attribute 's'` em **todos** os arquivos
(usa `ast.Constant.s`, removido no 3.12+) e ainda assim sai com código 0, imprime
`High: 0, Medium: 0, Low: 0` e devolve `"results": []` no JSON. Só aparece um
`(exception while scanning file)` no fim do output de *texto* — que o pipeline não lê.

Dentro do container (3.11) isso não acontece, então **é um problema de ambiente, não
de código nosso**. Está aqui por dois motivos:

- é o motivo concreto de o container ser o caminho canônico, e de o smoke test acima
  exigir `bandit != 0 achados`;
- generaliza para a restrição do briefing sobre ferramenta ausente na avaliação — não
  controlamos o ambiente do avaliador, e falha silenciosa é pior que falha ruidosa.

Também verificado no host: `radon` funciona normalmente em 3.14 e reproduz a tabela
de CC do `docs/ferramentas.md`; `pydantic==2.8.2` não instala (sem wheel cp314 para
`pydantic-core`, build Rust falha); `semgrep` e `pylint` instalam, mas não testamos a
execução. Nada disso importa se você usar o container — e você deveria.

---

## Entregas

1. **Relatório** de débitos priorizados (campos obrigatórios no briefing), incluindo
   uma seção *"O que a IA sugeriu que estava errado, e por quê"*.
2. **Pipeline** que recebe o path de um repositório e gera relatório em Markdown e JSON.
3. **README do pipeline** explicando como rodar e como o scoring model funciona.

Bônus (10%): suportar também o alvo PHP com o mesmo scoring model e o mesmo formato.
