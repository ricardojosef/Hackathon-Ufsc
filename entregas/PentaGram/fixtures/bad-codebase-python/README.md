# Big Bad Flask™

> Um sistema de controle de horas faturáveis construído com Flask.
> Funciona. Não pergunte como.

---

## Como rodar

```bash
pip install -r requirements.txt
python run.py
```

Acesse `http://localhost:8000`.

---

## Arquitetura

A aplicação cresceu organicamente ao longo de 3 anos. Hoje está assim:

```
app/
├── helpers/          — utilitários compartilhados
├── services/         — lógica de negócio (ou seria?)
├── models/           — entidades de banco
├── routes/           — blueprints de rotas
└── everything.py     — faz tudo
```

Consulte também o `business-context.md` para entender o contexto da empresa antes de priorizar qualquer coisa.

---

## Sobre os testes

Não há testes. O `pytest` está listado. Contribuições são bem-vindas.

```bash
pytest  # vai passar porque não há nada para falhar
```

---

## Segurança

Se você encontrar uma vulnerabilidade de segurança, ela provavelmente já está no código.
