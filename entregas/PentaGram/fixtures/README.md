# Fixtures — alvos de análise

⚠️ **Nada aqui é código nosso. Nada aqui deve ser corrigido.**

Estes são os dois repositórios-alvo da hackathon, copiados do repositório oficial
da organização. São o *input* do nosso pipeline — o equivalente a dados de teste.

| Pasta | Linguagem | Papel |
|---|---|---|
| `bad-codebase-python/` | Python / Flask | **alvo principal** — 920 LOC, é o que o radar precisa analisar |
| `bad-codebase/` | PHP / Laravel | alvo do **bônus** (10% da nota) — mesmo sistema, mesmos débitos intencionais |

## Por que estão versionados aqui

O scoring model precisa ser **determinístico** (requisito do desafio, 25% da nota).
Determinismo não é verificável se cada pessoa do time analisa uma cópia diferente do
alvo. Com os fixtures no repositório, `main.py fixtures/bad-codebase-python` produz
o mesmo relatório na máquina de todo mundo e no CI.

## Regras

1. **Não edite estes arquivos.** O código é propositalmente ruim — a entrega é
   analisá-lo, não consertá-lo. Um commit que "melhora" um fixture invalida a
   comparação de output entre execuções.
2. **Mantenha byte-idêntico ao upstream.** Inclusive os `business-context.md` e
   `security-questionnaire.md` que existem aqui dentro: as cópias de leitura ficam
   em `docs/`, mas as originais permanecem na árvore do fixture para que o pipeline
   veja exatamente os mesmos arquivos que os avaliadores veem.
3. **Read-only no container.** `docker-compose.yml` monta as duas pastas com `:ro`
   justamente para que um bug no pipeline não consiga escrever no alvo.

Procedência e como sincronizar se a organização atualizar o material:
veja [`../docs/UPSTREAM.md`](../docs/UPSTREAM.md).
