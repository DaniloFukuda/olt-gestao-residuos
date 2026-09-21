# OLT — Gestão Operacional de Contentores

Sistema de gestão operacional para contentores e alugueres, com automação conversacional via WhatsApp Cloud API e uma API FastAPI para consulta de estado operacional.

O projeto organiza o ciclo de aluguer de contentores: disponibilidade, entrega, localização, dados de contacto, valor, pagamento, vencimento, recolha e lembretes. As regras de domínio permanecem independentes da integração de mensageria para permitir validação local e testes automatizados.

## Funcionalidades

- **Operação via WhatsApp:** webhook de verificação e recebimento compatível com WhatsApp Cloud API.
- **Registo de aluguer:** início de aluguer, foto de entrega, localização GPS, contacto do cliente, valor, estado de pagamento e forma de pagamento.
- **Gestão de contentores:** catálogo inicial, disponibilidade, alugados, manutenção e aguardando recolha.
- **Entrega e recolha:** eventos persistidos de entrega e marcação de recolha.
- **GPS/localização:** o fluxo exige coordenadas de localização antes da confirmação do aluguer.
- **Autorização de operadores:** números autorizados podem ser configurados por variável de ambiente; entradas não autorizadas são bloqueadas quando a política está ativa.
- **Resumos operacionais:** comandos para totais, disponibilidade, alugueres ativos, vencimentos e atrasos.
- **Pagamentos:** registo de pago/pendente e forma de pagamento no aluguer.
- **Painel API:** endpoints para contentores, vencimentos de amanhã e lembretes.
- **Testes automatizados:** cobertura de domínio, fluxo WhatsApp, webhook, autorização, migrações e API.

## Arquitetura

```text
WhatsApp Cloud API
       │
Webhook FastAPI ── Parser ── Router de conversa
       │                         │
       │                    Agentes de fluxo
       │                         │
       └────────── Serviços de domínio ──────────┐
                                                   │
                                      SQLite + SQLAlchemy
```

### Componentes

| Camada | Responsabilidade |
|---|---|
| `app/routes/` | Webhook WhatsApp, health check e endpoints de painel |
| `app/agents/` | Fluxos de aluguer, localização, recolha, renovação e lembretes |
| `app/services/` | Regras de contentor, aluguer, notificações, seeds e lembretes |
| `app/models/` | Entidades persistidas e estados operacionais |
| `app/integrations/whatsapp/` | Parser de payloads e cliente da WhatsApp Cloud API |
| `tests/` | Testes automatizados de regras, integração e regressões |

## Stack

- Python
- FastAPI e Uvicorn
- SQLite e SQLAlchemy
- WhatsApp Cloud API
- Pydantic Settings
- Pytest e HTTPX

## API e operação local

```bash
python -m venv .venv
source .venv/Scripts/activate  # Git Bash no Windows
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

A API fica disponível em `http://127.0.0.1:8000`.

Endpoints principais:

- `GET /health`
- `GET /webhook/whatsapp` — verificação do webhook
- `POST /webhook/whatsapp` — recebimento de eventos
- `GET /dashboard/contentores`
- `GET /dashboard/alugueres/vencendo-amanha`
- `GET /dashboard/lembretes`

## Configuração segura

Crie um `.env` local a partir de `.env.example`. Use apenas valores de demonstração na documentação e mantenha credenciais reais fora do Git.

Principais grupos de configuração:

- URL do banco SQLite;
- token de verificação e credenciais da WhatsApp Cloud API;
- identificador do número da Cloud API;
- política de operadores autorizados;
- ambiente de execução.

Quando as credenciais da Cloud API não estão configuradas, ou quando `ENV=test`, o cliente de envio trabalha em modo seguro de simulação. Nunca use números, tokens ou IDs reais em fixtures, exemplos ou commits.

## Fluxo operacional resumido

1. Um operador autorizado inicia o registo de um aluguer.
2. O sistema coleta foto de entrega e localização GPS.
3. São registados os dados de contacto, valor, situação e forma de pagamento.
4. O contentor passa ao estado de alugado e recebe vencimento calculado.
5. A operação pode ser acompanhada por resumo, listas, vencimentos, atrasos e marcação de recolha.

## Testes

```bash
python -m pytest -q
```

## Segurança e privacidade

O repositório não deve conter `.env`, tokens, chaves privadas, bancos locais, uploads, fotografias, documentos ou dados pessoais reais. Antes de publicar alterações, revise os arquivos staged e execute a suíte de testes.

## Deploy

A aplicação é uma API ASGI e pode ser executada com Uvicorn atrás de um proxy reverso no ambiente controlado. Configurações de infraestrutura, credenciais e dados operacionais devem permanecer fora do repositório público.
