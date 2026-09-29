# OLT — Gestão Operacional de Contentores e Carrinhas

Sistema de gestão operacional de uma pequena empresa de resíduos e demolições em Portugal. Toda a operação acontece por conversa no WhatsApp (WhatsApp Cloud API); a API FastAPI recebe o webhook, guarda o estado de cada conversa e aplica as regras de negócio.

O sistema cobre dois serviços:

- **Contentores:** pedido → entrega (adesivo do contentor, fotos, localização) → recolha → despejo no vazadouro. Prazo de aluguer de 5 dias.
- **Carrinhas:** pedido → chegada ao cliente → partida (prevista para 2 horas depois da chegada) → despejo.

## Funcionalidades

- **Menu V4 no WhatsApp:** 1. Novo Pedido · 2. Confirmar Chegada/Entrega · 3. Confirmar Recolha/Partida · 4. Confirmar Despejo · 5. Painel de Controle.
- **Pedidos com vários equipamentos:** um pedido pode ter vários contentores e/ou carrinhas, cada um com resíduo contratado (Entulho Limpo ou Entulho Misto), data planejada e valor global.
- **Pagamentos:** pago na criação ou pendente; recebimento na entrega regista forma, data e operador.
- **Pendências:** pagamento pendente, avaria (com fotos) e carga divergente no despejo, com revisão e resolução pelo gestor.
- **Painel operacional:** ações de hoje, recolhas do dia, atrasos, carrinhas em atendimento, pendências e resumo financeiro.
- **Perfis:** GESTOR (tudo) e FUNCIONARIO (operação de campo), a partir da tabela `operadores`.
- **Webhook robusto:** assinatura da Meta (`X-Hub-Signature-256`), deduplicação por `message_id` e fila por telefone para mensagens concorrentes.
- **Testes automatizados:** domínio, fluxos conversacionais, webhook, migrações e cenários de sistema de ponta a ponta.

## Arquitetura

```text
WhatsApp Cloud API
       │  POST /webhook/whatsapp (assinado)
Webhook FastAPI ── dedup (mensagens_webhook) ── fila por telefone
       │
WhatsappRouterAgent ── PedidoV24OperationalRouter ── agentes de fluxo (app/agents/pedido_v24/)
       │                                              └─ backend legado PedidoV24Agent
Serviços de domínio (PedidoService, ContentorService, OperadorService…)
       │
SQLite + SQLAlchemy
```

| Camada | Responsabilidade |
|---|---|
| `app/routes/` | Webhook WhatsApp, health check e endpoints de painel |
| `app/agents/` | Roteador de conversa e fluxos (cadastro, entrega, recolha, despejo, pendências) |
| `app/services/` | Regras de pedido, frota, operadores, deduplicação, fila e outbox |
| `app/models/` | Entidades persistidas e estados operacionais |
| `app/integrations/whatsapp/` | Parser de payloads e cliente da Cloud API (botões e listas interativas) |
| `tests/` | Testes unitários, de fluxo e `tests/system/` (ponta a ponta via webhook) |

Notas para quem for mexer no código estão em [`AGENTS.md`](AGENTS.md); pendências conhecidas em [`PENDENCIAS.md`](PENDENCIAS.md).

## Stack

- Python 3.11+
- FastAPI e Uvicorn
- SQLite e SQLAlchemy 2
- WhatsApp Cloud API
- Pydantic Settings
- Pytest e HTTPX

## Operação local

```bash
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate         # Windows
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

A API fica disponível em `http://127.0.0.1:8000`.

Endpoints principais:

- `GET /health`
- `GET /webhook/whatsapp` — verificação do webhook pela Meta
- `POST /webhook/whatsapp` — recebimento de mensagens
- `GET /dashboard/contentores`
- `GET /dashboard/alugueres/vencendo-amanha`
- `GET /dashboard/lembretes`

Os endpoints `/dashboard/*` devolvem dados de clientes e exigem o cabeçalho `X-Dashboard-Token` igual a `DASHBOARD_TOKEN`; sem `DASHBOARD_TOKEN` configurado respondem 404.

## Configuração

Crie um `.env` a partir de `.env.example`. Variáveis principais:

| Variável | Uso |
|---|---|
| `DATABASE_URL` | Banco SQLite |
| `WHATSAPP_VERIFY_TOKEN` | Token de verificação do webhook (GET da Meta) |
| `WHATSAPP_APP_SECRET` | App Secret da Meta. Com ele preenchido o webhook exige assinatura válida. **Preencha em produção.** |
| `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` | Credenciais de envio da Cloud API |
| `DASHBOARD_TOKEN` | Token dos endpoints `/dashboard/*` (vazio = desligados) |
| `AUTHORIZED_OPERATOR_PHONES` | Telefones com acesso de gestor quando a tabela `operadores` está vazia (fallback) |
| `FLUXO_TIMEOUT_MINUTOS` | Minutos até um fluxo abandonado expirar (padrão 120) |
| `FEATURE_CONTENTORES_ENABLED`, `FEATURE_CARRINHAS_ENABLED`, `FEATURE_AVARIAS_ENABLED` | Liga/desliga serviços |
| `ENV` | `test` força o envio em modo simulado |

Quando as credenciais da Cloud API não estão configuradas, ou quando `ENV=test`, o cliente de envio trabalha em modo simulado. Nunca use números, tokens ou IDs reais em fixtures, exemplos ou commits.

Para cadastrar gestores iniciais:

```bash
python scripts/cadastrar_gestores_lucas_secretario.py 351900000001:Lucas 351900000002:Secretario
# ou OLT_GESTORES="351900000001:Lucas;351900000002:Secretario"
```

## Testes

```bash
python -m pytest -q                 # suíte completa
python -m pytest -q tests/system    # cenários de ponta a ponta via webhook
```

## Segurança e privacidade

O repositório não deve conter `.env`, tokens, chaves privadas, bancos locais, uploads, fotografias ou dados pessoais reais (RGPD). Antes de publicar alterações, revise os arquivos staged e execute a suíte de testes.

## Deploy

A aplicação é uma API ASGI e pode ser executada com Uvicorn atrás de um proxy reverso. Em produção, configure `WHATSAPP_APP_SECRET` para que só a Meta consiga chamar o webhook. Configurações de infraestrutura, credenciais e dados operacionais ficam fora do repositório.
