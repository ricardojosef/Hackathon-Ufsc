# Radar de Débitos Técnicos — Hackathon Soluevo × UFSC

Bem-vindo(a) ao desafio! O objetivo é construir um **radar de débitos técnicos**: uma
ferramenta que analisa um código legado, identifica problemas de segurança, arquitetura,
complexidade e manutenibilidade, e produz um relatório priorizado.

---

## Por onde começar

1. Leia o **[`cenario-do-desafio.md`](cenario-do-desafio.md)** — é o briefing completo do desafio.
2. Entenda o contexto da empresa fictícia em **[`bad-codebase-python/business-context.md`](bad-codebase-python/business-context.md)**.
3. Explore o código que você vai analisar (veja abaixo).

---

## Estrutura do repositório

| Pasta / Arquivo | O que é |
|---|---|
| `cenario-do-desafio.md` | Briefing do desafio, entregas obrigatórias e regras |
| `bad-codebase-python/` | **Código-alvo principal** (Python/Flask) — é isso que seu radar deve analisar |
| `bad-codebase/` | Código-alvo equivalente em PHP/Laravel — **análise é bônus** |
| `analyzer-env/` | Ambiente e ferramentas sugeridas para construir o pipeline de análise |
| `bad-codebase-python/security-questionnaire.md` | Questionário de segurança que o cliente enterprise enviou |

---

## As entregas

Você deve produzir **duas** coisas (detalhes no `cenario-do-desafio.md`):

1. **Um pipeline/ferramenta** que analisa o código e gera achados de forma automática.
2. **Um relatório** que prioriza os débitos encontrados considerando o contexto de negócio.

Analisar a versão PHP (`bad-codebase/`) é **bônus**, não obrigatório.

---

## Como rodar o código-alvo (opcional, para entender o sistema)

**Python:**
```bash
cd bad-codebase-python
pip install -r requirements.txt
python run.py
```

**PHP (bônus):**
```bash
cd bad-codebase
composer install
php artisan serve
```

---

## Regras importantes

- O código-alvo é **propositalmente ruim**. Não o "conserte" — **analise-o**.
- Seu diferencial está em **priorizar bem** contra o contexto de negócio, não em achar o maior número de problemas.
- Assuma que ferramentas externas (bandit, radon, pylint) **podem não estar instaladas** no ambiente de avaliação — seu pipeline deve ter um caminho que funcione mesmo sem elas.

Boa sorte! 🚀
