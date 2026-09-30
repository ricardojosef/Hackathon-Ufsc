# Questionário de Segurança — Cliente Enterprise

> **Contexto:** A GlobalConsult S/A (cliente enterprise, 200+ usuários, contrato de R$ 8.000/mês) enviou este questionário como pré-requisito para assinatura do contrato. As respostas são necessárias em **30 dias**. Qualquer "Não" ou "Parcialmente" exige um plano de remediação.

---

## Perguntas

| # | Pergunta | Resposta esperada |
|---|---|---|
| 1 | O sistema é protegido contra SQL Injection? (queries parametrizadas ou ORM sem interpolação direta) | Sim |
| 2 | O sistema é protegido contra Cross-Site Scripting (XSS)? (output de dados do usuário sempre com escape) | Sim |
| 3 | As senhas são armazenadas com hash seguro (bcrypt, PBKDF2 ou Argon2)? | Sim |
| 4 | Credenciais e API keys estão fora do código-fonte e do repositório Git? | Sim |
| 5 | O repositório não contém arquivos `.env` com valores reais commitados? | Sim |
| 6 | O modo debug/desenvolvimento está desativado em produção? | Sim |
| 7 | O código não utiliza algoritmos de hash reconhecidamente inseguros (MD5, SHA-1) para dados sensíveis? | Sim |

---

> **Nota:** Este questionário foi preenchido pelo time comercial da HourTrack com base no que *acreditam* ser verdade sobre o produto. A área técnica ainda não revisou as respostas.
