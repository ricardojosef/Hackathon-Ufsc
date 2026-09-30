"""
Testes do pipeline.

Este módulo expõe `target_repo()`, que localiza os repositórios-alvo sem
depender da profundidade do pacote nem do diretório de onde os testes são
invocados.

Por que isso importa: os testes rodam em pelo menos três contextos diferentes
— da raiz do projeto, de `analyzer-env/workspace/`, e de dentro do container,
onde os alvos estão montados em `/repos/python` e `/repos/php` (irmãos de
`/workspace`, não ancestrais). Contar níveis com `parents[N]` funciona em um
contexto e quebra nos outros.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Onde o docker-compose do analyzer-env monta cada alvo.
CONTAINER_MOUNTS = {
    "bad-codebase-python": Path("/repos/python"),
    "bad-codebase": Path("/repos/php"),
}


def target_repo(name: str) -> Path | None:
    """
    Localiza um repositório-alvo pelo nome, ou devolve None.

    Resolve por prioridade, não por contagem de níveis:

      1. variável de ambiente `RADAR_TARGET_<NOME>` — escape hatch para CI;
      2. o mount conhecido do container (`/repos/python`, `/repos/php`);
      3. busca ancestral: sobe a árvore a partir deste arquivo até achar um
         diretório com esse nome.

    O passo 3 é o que sobrevive a mudanças de layout: funcionava quando o
    pacote estava na raiz (2 níveis acima) e continua funcionando agora, em
    `analyzer-env/workspace/analyzer/` (4 níveis acima).
    """
    env_key = f"RADAR_TARGET_{name.upper().replace('-', '_')}"
    from_env = os.environ.get(env_key, "").strip()
    if from_env and Path(from_env).is_dir():
        return Path(from_env)

    mount = CONTAINER_MOUNTS.get(name)
    if mount is not None and mount.is_dir():
        return mount

    for parent in Path(__file__).resolve().parents:
        candidate = parent / name
        if candidate.is_dir():
            return candidate

    return None
