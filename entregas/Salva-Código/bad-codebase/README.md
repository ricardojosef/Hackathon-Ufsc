# Big Bad Laravel™

> Um sistema de controle de horas faturáveis construído com Laravel.
> Funciona. Não pergunte como.

---

## Como rodar

```bash
composer install
cp .env.example .env   # ou use o .env já commitado, que tem as credenciais reais
php artisan migrate    # roda migrations E insere dados (sim, junto)
php artisan serve
```

Acesse `http://localhost:8000`.

---

## Arquitetura

A aplicação cresceu organicamente ao longo de 3 anos. Hoje está assim:

```
app/
├── Console/Commands/     — jobs de linha de comando
├── Helpers/              — utilitários compartilhados
├── Http/
│   ├── Controllers/      — lógica HTTP
│   └── Middleware/       — interceptadores de requisição
├── Models/               — entidades de banco
└── Services/             — lógica de negócio (ou seria?)
```

Consulte também o `business-context.md` para entender o contexto da empresa antes de priorizar qualquer coisa.

---

## Sobre os testes

Não há testes. O `phpunit.xml` está configurado. Contribuições são bem-vindas.

```bash
php artisan test  # vai passar porque não há nada para falhar
```

---

## Segurança

Se você encontrar uma vulnerabilidade de segurança, ela provavelmente já está documentada na tabela acima.
