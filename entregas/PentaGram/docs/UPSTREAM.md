# Procedência do material importado

Tudo em `docs/` e `fixtures/` foi copiado do repositório oficial da hackathon.
Não editamos nada disso — se precisar mudar, mude no nosso código, não no material.

| | |
|---|---|
| Repositório | `git@github.com:soluevo/Hackathon-Ufsc.git` |
| Commit | `55609f6bc901a56c3b381ed768b1979c57c13c38` (`55609f6`) |
| Data do commit | 2026-09-12 |
| Importado em | 2026-09-12 |

## O que veio, e de onde

| Aqui | Origem no upstream |
|---|---|
| `docs/cenario-do-desafio.md` | `cenario-do-desafio.md` |
| `docs/business-context.md` | `bad-codebase-python/business-context.md` |
| `docs/security-questionnaire.md` | `bad-codebase-python/security-questionnaire.md` |
| `docs/ferramentas.md` | `analyzer-env/workspace/FERRAMENTAS.md` |
| `docs/briefing-analyzer-env.md` | `analyzer-env/workspace/README.md` |
| `fixtures/bad-codebase-python/` | `bad-codebase-python/` (idêntico) |
| `fixtures/bad-codebase/` | `bad-codebase/` (idêntico) |
| `docker/Dockerfile` | `analyzer-env/Dockerfile` (**adaptado** — veja cabeçalho do arquivo) |
| `docker-compose.yml` | `analyzer-env/docker-compose.yml` (**adaptado** — paths e mounts) |

Ficou de fora: `slides.html` (51 KB, duplica o conteúdo do `cenario-do-desafio.md`).
Ainda está disponível no clone do repositório oficial, se alguém quiser consultar.

## Se a organização atualizar o material

Já aconteceu uma vez antes do evento começar (PR #1 adicionou os slides), então
vale conferir. Os fixtures foram extraídos com `git archive` no SHA acima, então a
comparação é exata:

```bash
# 1. atualizar o clone oficial
git -C ../Hackathon-Ufsc pull

# 2. o que mudou desde o que importamos?
git -C ../Hackathon-Ufsc log --oneline 55609f6..HEAD
git -C ../Hackathon-Ufsc diff --stat 55609f6..HEAD
```

Se houver mudança relevante, reimporte **em um PR separado** — nunca misturado com
mudança de pipeline, para que o diff mostre com clareza o que veio de fora:

```bash
git checkout -b chore/sync-upstream
rm -rf fixtures/bad-codebase fixtures/bad-codebase-python
git -C ../Hackathon-Ufsc archive HEAD bad-codebase bad-codebase-python | tar -x -C fixtures/
cp ../Hackathon-Ufsc/cenario-do-desafio.md docs/
cp ../Hackathon-Ufsc/bad-codebase-python/business-context.md docs/
cp ../Hackathon-Ufsc/bad-codebase-python/security-questionnaire.md docs/
cp ../Hackathon-Ufsc/analyzer-env/workspace/FERRAMENTAS.md docs/ferramentas.md
cp ../Hackathon-Ufsc/analyzer-env/workspace/README.md docs/briefing-analyzer-env.md
# depois: atualizar o SHA na tabela deste arquivo
```

⚠️ **Reimportar fixture muda o output do pipeline.** Se o alvo mudar, rode a suíte de
novo e confira se o relatório mudou por causa do alvo — não por causa de um bug nosso.
