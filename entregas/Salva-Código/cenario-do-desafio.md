# 🦨 Big Bad Hackathon — Cenário do Desafio

## Bem-vindos

Vocês foram contratados como consultores de engenharia pela **HourTrack Ltda.** — uma startup de SaaS B2B que construiu, ao longo de 3 anos, um sistema de controle de horas faturáveis para agências de publicidade e consultorias.

O CEO ligou ontem à noite preocupado. A empresa está crescendo, está prestes a fechar um contrato grande, e alguém mencionou pela primeira vez a palavra **"auditoria de segurança"**. Ninguém no time sabe exatamente o que vai encontrar quando alguém olhar o código de verdade.

Vocês têm **1 dia** para fazer esse diagnóstico — e automatizá-lo.

---

## A Empresa

**HourTrack Ltda.** é um SaaS B2B fundado em 2021. Hoje tem:

- 47 agências como clientes ativos
- ~180 usuários (consultores das agências)
- R$ 28.000 de receita mensal recorrente (MRR)
- Um time de 8 pessoas, sendo apenas 2 desenvolvedores full-stack

O sistema processa dados de contratos entre agências e seus clientes. Um vazamento poderia gerar ações judiciais.

---

## A Situação do Time

- Os 2 devs têm capacidade real de **~6 story points por semana** — reuniões, bugs urgentes e suporte consomem ~40% do tempo
- **Não há QA. Não há DevOps dedicado.**
- O desenvolvedor que escreveu **90% do código está saindo da empresa em 6 semanas**

---

## Pressões e Prazos

### 🔴 Urgente — próximos 14 dias
Uma **release v2.1** precisa ser entregue em **14 dias** — já foi prometida a 3 clientes grandes (nova funcionalidade de relatório por projeto). Dois deles ameaçaram cancelar o contrato se não sair no prazo. Não dá para atrasar.

### 🟡 Importante — próximos 30 dias
Um **cliente enterprise** (200+ usuários, contrato de R$ 8.000/mês) está em negociação. Ele pediu um **questionário de segurança** antes de assinar. Se fechar, dobra o MRR atual.

### Riscos conhecidos
- 3 clientes respondem por 60% da receita. Perder qualquer um é crítico.
- O sistema não tem ambiente de staging. Qualquer mudança vai direto para produção.
- O banco de dados é SQLite — o mesmo arquivo que está commitado no repositório.

---

## Os Repositórios

Vocês recebem dois repositórios com o mesmo sistema implementado em linguagens diferentes:

| Repositório | Linguagem | Porta |
|---|---|---|
| `bad-codebase-python` | Python / Flask | `http://localhost:8089` |
| `bad-codebase` | PHP / Laravel | `http://localhost:8088` |

Para rodar qualquer um:

```bash
cd bad-codebase-python  # ou bad-codebase
docker compose up
```

Leia o `README.md` para entender a estrutura. Leia o `business-context.md` antes de priorizar qualquer coisa — o contexto de negócio é parte do desafio.

**Dica:** o sistema funciona. Isso não significa que está correto.

---

## O Desafio

O desafio tem **duas entregas obrigatórias** e **uma bônus**.

---

### Relatório de Débitos Técnicos

Analisem o repositório Python (`bad-codebase-python`) e produzam um relatório identificando e priorizando os problemas encontrados.

Para cada débito técnico identificado, o relatório deve conter:

| Campo | Descrição |
|---|---|
| **ID** | Identificador sequencial (ex: DT-01) |
| **Categoria** | Segurança / Design / Manutenibilidade / Performance / Arquitetura |
| **Nome** | Nome curto e descritivo do débito |
| **Descrição** | O que está errado e onde no código |
| **Impacto** | Consequência real se não for corrigido — para o **negócio**, não só para o código |
| **Risco** | Probabilidade de o problema se manifestar: Alto / Médio / Baixo |
| **Esforço** | Estimativa de correção em story points ou horas |
| **Valor** | O que a empresa ganha ao corrigir: negócio, segurança, qualidade |
| **Prioridade** | Crítica / Alta / Média / Baixa — **justificada pelo contexto de negócio** |

---

### Gerador de Relatório (codificação)

Construam um **pipeline de análise automatizada** em Python que:

1. **Recebe o path de um repositório** como argumento de linha de comando
2. **Detecta a linguagem** do repositório (Python ou PHP)
3. **Executa as ferramentas de análise adequadas** via `subprocess`:
   - Python: `bandit` (segurança), `radon` (complexidade ciclomática), `pylint` (smells gerais)
   - PHP *(bônus)*: `phpstan` (análise estática), `phploc` (métricas)
4. **Normaliza os resultados** em um formato de `Finding` unificado (independente de linguagem)
5. **Aplica o scoring model determinístico** baseado nas pressões do `business-context.md`
6. **Gera o relatório final** em Markdown e JSON

#### Requisitos do scoring model

O scoring **deve ser determinístico** — rodado duas vezes no mesmo repositório, gera o mesmo resultado. Não pode depender de LLM para calcular a prioridade.

As regras de priorização devem ser explícitas e justificáveis. Exemplo de critérios a considerar:
- Severidade base do achado (crítica, alta, média, baixa)
- Proximidade do questionário de segurança (30 dias) eleva achados de segurança
- Proximidade da release (14 dias) penaliza itens de alto esforço
- Risco de perder o cliente enterprise amplifica vulnerabilidades de acesso a dados

As regras devem estar documentadas no próprio código (comentários ou arquivo de configuração), não apenas no relatório.

#### Estrutura esperada do gerador

```
analyzer/
├── main.py              # entry point: recebe path do repo, orquestra o pipeline
├── detectors/
│   ├── python.py        # invoca bandit/radon/pylint, retorna lista de Finding
│   └── php.py           # invoca phpstan/phploc (bônus)
├── models.py            # dataclass Finding com campos normalizados
├── scoring.py           # scoring model determinístico
├── report.py            # renderiza Markdown e JSON
└── tests/
    └── test_scoring.py  # testes unitários do scoring model
```

#### O que não é aceitável como entrega

- Um script que só chama a API da OpenAI e repassa o código — isso não é análise, é delegação.
- Um relatório gerado por LLM sem nenhum processamento determinístico.
- Um dump bruto do output das ferramentas sem normalização ou priorização.

A IA pode (e deve) ser usada para enriquecer as **descrições** dos achados em linguagem natural. Mas a **detecção** e a **priorização** devem ser computadas pelo pipeline.

---

### Bônus — Suporte a PHP

Estenda o pipeline para suportar também o repositório PHP (`bad-codebase`). O mesmo scoring model e o mesmo formato de relatório devem funcionar para ambas as linguagens.

O desafio arquitetural é exatamente esse: projetar a camada de abstração (`Finding` como estrutura comum, adaptadores por linguagem) de forma que o scoring model opere sem saber de onde o achado veio.

---

## Como usar IA no desafio

O uso de ferramentas de IA (GitHub Copilot, ChatGPT, Cursor, Kiro, etc.) é **encorajado**. Faz parte do desafio usá-las de forma inteligente.

Abordagens que valem pontos extras:

1. **IA para enriquecer descrições** — use LLM para redigir o campo "Impacto" em linguagem de negócio, a partir do achado técnico bruto
2. **IA como pair reviewer** — peça para a IA revisar seu scoring model e questionar os critérios
3. **IA vs. ferramentas** — compare o que o bandit/radon encontrou com o que a IA encontrou manualmente; as diferenças são o ponto mais interessante
4. **Auditoria do output da IA** — documente o que a IA sugeriu que estava errado e por quê você discordou

> ⚠️ **Atenção:** a IA erra. Ela inventa problemas que não existem e deixa passar problemas reais. Validar o output da IA é uma habilidade — e será avaliada.

---

## Critérios de Avaliação

| Critério | Peso |
|---|---|
| Qualidade e completude do Relatório (Entrega 1) | 30% |
| Funcionamento do pipeline — detecta achados reais e gera output válido | 25% |
| Scoring model — regras explícitas, determinísticas e justificadas pelo contexto de negócio | 25% |
| Qualidade do código — estrutura, testes, clareza | 10% |
| Bônus: suporte a PHP | 10% |

**Atenção:** priorizar SQL Injection como "Baixa" porque "o sistema já funciona há 3 anos sem incidente" é uma resposta — mas será avaliada. Priorizar testes como "Crítica" ignorando o questionário de segurança do cliente enterprise em 30 dias também é uma resposta. O que conta é a **argumentação**.

---

## Penalidades

- **Falso positivo no relatório:** reportar algo como débito técnico que não é um problema real desconta pontos.
- **Pipeline não determinístico:** scoring que muda entre execuções sem mudança no código é desclassificado como entrega técnica.
- **Dump bruto de ferramentas sem processamento:** não conta como pipeline.

---

## Entrega

Até o horário definido pela organização:

1. **Relatório** (PDF, Markdown ou Google Docs) com os débitos identificados
2. **Repositório do pipeline** (GitHub, GitLab ou ZIP) com o código do gerador
3. **README** do pipeline com instruções de como rodar e como o scoring model funciona

**Inclua obrigatoriamente no relatório:** uma seção *"O que a IA sugeriu que estava errado, e por quê"* — mesmo que sejam 3 linhas.

---

## A pergunta central

> **Se você fosse o CTO da HourTrack por um dia, o que faria primeiro — e o que deixaria para depois?**

Não existe resposta certa. Existe resposta **bem justificada**.

---

*Boa sorte. O código não vai se refatorar sozinho. 👻*
