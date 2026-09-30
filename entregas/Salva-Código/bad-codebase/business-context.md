# Contexto de Negócio — Big Bad Laravel™

> Este documento descreve a situação real da empresa e do produto.
> Use estas informações para **priorizar** os débitos técnicos encontrados.
> Um débito técnico que seria crítico em outro contexto pode não ser urgente aqui — e vice-versa.

---

## A Empresa

**Nome:** HourTrack Ltda.
**Segmento:** SaaS B2B para agências de publicidade e consultorias
**Fundação:** 2021
**Tamanho:** 8 pessoas (2 devs, 1 designer, 1 CS, 2 vendedores, 1 financeiro, 1 CEO)

---

## O Produto

O **Big Bad Laravel™** é o sistema principal da empresa — controla as horas faturáveis de consultores, gera relatórios mensais para clientes e calcula o faturamento.

Não há outro sistema. Não há backup do negócio.

---

## Situação Atual

| Item | Situação |
|------|----------|
| Clientes ativos | 47 agências |
| Usuários no sistema | ~180 (consultores das agências) |
| Receita mensal recorrente | R$ 28.000 MRR |
| Uptime nos últimos 6 meses | 99,1% |
| Infraestrutura | 1 VPS na DigitalOcean, sem staging |
| Deploy | Manual: `git pull` + `php artisan migrate` em produção |
| Monitoramento | Nenhum. Clientes avisam quando cai. |

---

## O Time de Desenvolvimento

- **2 desenvolvedores** — ambos full-stack, nível pleno
- Capacidade real: ~**6 story points por semana** (reuniões, suporte, bugs urgentes consomem ~40% do tempo)
- Não há QA. Não há DevOps dedicado.
- O desenvolvedor mais antigo (que escreveu 90% do código) **sai da empresa em 6 semanas**

---

## Roadmap e Pressões

### Próximos 30 dias
- **Release v2.1** em **14 dias** — nova funcionalidade de relatório por projeto (já comprometida com 3 clientes grandes)
- Não é possível atrasar: dois clientes ameaçaram cancelar se não entregar

### Próximos 90 dias
- Negociação em andamento com um **cliente enterprise** (200+ usuários, contrato de R$ 8.000/mês)
- O cliente enterprise pediu um **questionário de segurança** antes de assinar — respostas necessárias em 30 dias
- Se fechar, dobra o MRR

### Riscos de negócio conhecidos
- 3 dos 47 clientes respondem por 60% da receita — perder qualquer um é crítico
- O sistema processa dados de contratos entre agências e seus clientes — vazamento poderia gerar processo

---

## Restrições Técnicas

- **Sem ambiente de staging** — qualquer mudança vai direto para produção
- **Zero cobertura de testes** — refatorações são cirurgia sem anestesia
- **Banco de dados SQLite em produção** — sim, o mesmo arquivo commitado no repo
- **1 VPS com 2GB RAM** — sem auto-scaling, sem load balancer
- O `composer.lock` e `vendor/` estão no repositório — deploy é literalmente `git pull`

---

## O que os Clientes Sabem (e o que não sabem)

Os clientes **não sabem** que:
- O sistema não tem autenticação real
- Os dados de todos os clientes estão no mesmo banco sem isolamento
- Qualquer usuário pode ver (e deletar) dados de qualquer outro cliente

Os clientes **acham** que:
- Os dados deles estão seguros
- O sistema tem backup
- Existe um processo de desenvolvimento com testes

---

## Pergunta que o relatório deve responder

> **Dado esse contexto, se você fosse o CTO dessa empresa por um dia, o que faria primeiro — e o que deixaria para depois?**

Não existe resposta certa única. Existe resposta **bem justificada** e resposta **sem embasamento**.

---

*Documento interno — não compartilhar com clientes.*
