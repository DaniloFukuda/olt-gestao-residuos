# AGENTS.md — guia para agentes de código (Codex, Claude e afins)

Leia isto antes de mexer no código. Resume a arquitetura, as armadilhas, as
regras de negócio já decididas e o histórico da consolidação de setembro de
2026. Pendências abertas estão em [`PENDENCIAS.md`](PENDENCIAS.md).

## 1. O sistema

Gestão operacional de uma pequena empresa de resíduos e demolições em
Portugal, **100% conversacional pelo WhatsApp** (Cloud API da Meta).

- **Contentor:** pedido → entrega (adesivo/número da frota, fotos, GPS) →
  recolha (fotos, avaria?) → despejo no vazadouro (resíduo, fotos). Prazo de 5
  dias a contar da entrega.
- **Carrinha:** pedido → chegada (frota, fotos, GPS) → partida (prevista para
  chegada + 2 h) → despejo.
- **Perfis:** `GESTOR` (tudo) e `FUNCIONARIO` (motorista: operação de campo,
  sem cadastro nem financeiro). Tabela `operadores`; sem operadores
  cadastrados, `AUTHORIZED_OPERATOR_PHONES` concede gestor (fallback).
- Menu V4: `1` Novo Pedido · `2` Chegada/Entrega · `3` Recolha/Partida ·
  `4` Despejo · `5` Painel.

## 2. Rodar e testar

```bash
python -m pip install -r requirements.txt
python -m pytest -q                 # ~1620 testes, ~2-3 min
python -m pytest -q tests/system    # webhook de ponta a ponta
```

- `tests/system/test_ponta_a_ponta.py` opera 22 pedidos (12 de contentor, 10
  de carrinha) do cadastro ao despejo pelo `POST /webhook/whatsapp`, com
  gestor e motorista. **Rode-o depois de qualquer mudança de fluxo.** Os
  helpers (`cadastrar`, `entregar_contentores`, `recolher`, `despejar`...)
  documentam a sequência exata de mensagens de cada fluxo.
- `tests/characterization/` fixa comportamento existente. Se uma mudança
  intencional quebra um teste de caracterização, atualize o teste e explique
  o porquê no commit (vários foram atualizados assim; ver seção 5).
- `ENV=test` ou credenciais vazias: o envio à Meta é simulado.

## 3. Arquitetura e armadilhas

```
POST /webhook/whatsapp (app/routes/webhook.py)
  ├─ assinatura X-Hub-Signature-256 (se WHATSAPP_APP_SECRET)
  ├─ deduplicação por message_id (WebhookDedupService, tabela mensagens_webhook)
  ├─ fila por telefone (WhatsAppPhoneQueueService) — serializa mensagens do mesmo número
  └─ WhatsappRouterAgent.handle (app/agents/whatsapp_router_agent.py)
        ├─ autorização, menu, cancelar (com confirmação), expiração de 2 h
        ├─ comandos: resumo/5, alugados, vencendo, atrasados, resolver carga|avaria N,
        │           registrar pagamento, cadastrar contentor N ...
        └─ estados "v24_*" → PedidoV24OperationalRouter (app/agents/pedido_v24/router.py)
              ├─ agentes modulares: contentor.py, carrinha.py, *_cadastro.py (decidem, não gravam)
              └─ backend PedidoV24Agent (app/agents/pedido_v24_agent.py) (grava, prompts)
                    └─ PedidoService (app/services/pedido_service.py) — regras e persistência
```

**Armadilhas conhecidas**

1. **A mesma etapa existe em até três lugares.** Ex.: a decisão do resíduo no
   despejo está em `pedido_v24/contentor.py`, `pedido_v24/carrinha.py` e no
   backend `PedidoV24Agent` (caminho legado/hidratação). O roteador escolhe
   qual usar conforme o tipo do equipamento e o formato do contexto. Ao mudar
   uma regra, mude as três — ou, melhor, extraia para um módulo compartilhado
   como foi feito em `app/agents/pedido_v24/despejo.py`.
2. **Datas:** o SQLite devolve `datetime` sem fuso; tudo é gravado em UTC. Use
   `_as_utc()` (pedido_service) antes de comparar com `utcnow()`.
   `data_planejada` é gravada como hora local sem fuso.
3. **Contexto da conversa** (`conversas_whatsapp.contexto_json`) é o estado do
   fluxo. `despejo_context_is_modern()` decide entre agente modular e backend
   pelas chaves presentes; chaves novas não atrapalham, chaves removidas sim.
4. **Duas gerações de dados:** `Pedido`/`PedidoContentor` (V24, atual) e
   `AluguerContentor` (cadastro unitário legado). O legado só atende conversas
   que já estavam nele; relatórios e painel somam os dois.
5. **Cliente WhatsApp** (`app/integrations/whatsapp/client.py`) transforma
   opções numeradas do texto em botões (≤3, título ≤20) ou lista (≤10 linhas,
   título ≤24, descrição ≤72). Acima disso vai texto. O parser devolve o id do
   botão/linha; `option_N` vira `N`. Alguns prompts têm ids próprios
   (`despejo_residuo:limpo`, `despejo_conformidade:sim`, `entrega_pedido:ID`,
   `corrigir_pedido:campo`) reconhecidos pelos agentes.
6. **Outbox** (`whatsapp_outbox_service.py`/`worker.py`) existe mas **não está
   ligada**: o webhook envia a resposta diretamente. Ver PENDENCIAS.
7. **Frota:** tabela `contentores`, semeada com 1–20 no arranque
   (`SeedService`). Com a tabela vazia a validação da frota não se aplica
   (testes antigos sem seed).

## 4. Regras de negócio decididas (29/09/2026, Paulo, sócio)

| Tema | Regra | Onde |
|---|---|---|
| Frota | Entrega só aceita contentor cadastrado e disponível; entrega → `alugado`; despejo → `disponível` ou `manutenção` se a recolha registou avaria pendente; resolver avaria → `disponível`. Número novo (1–99): gestor envia `cadastrar contentor N`. | `PedidoService.erro_frota_entrega`, `_ocupar_frota`, `_liberar_frota`, `cadastrar_contentor_frota` |
| Resíduo real | O motorista informa o resíduo que caiu de fato; grava-se esse resíduo (mesmo sem cota) e abre pendência de carga com relato. | `pedido_v24/despejo.py`, `PedidoService._validar_cota_despejo` |
| Divergência | Vale **o total do pedido**: contentores trocados dentro do pedido não são divergência. Só há divergência quando o motorista responde "Não" à conformidade. (Substitui a regra por contentor do hotfix `25d4762`.) | `pedido_v24/despejo.py`, `cotas_residuos` |
| Cadastro | `novo`/`cadastrar`/`iniciar`/`começar` abrem o Novo Pedido (opção 1). `alugados`/`vencendo`/`atrasados` incluem pedidos V24. | `whatsapp_router_agent.py` |
| Expiração | Fluxo V24 sem avanço há mais de 2 h (`FLUXO_TIMEOUT_MINUTOS`) é encerrado na próxima mensagem; etapas já confirmadas continuam salvas. | `_fluxo_v24_expirado` |
| Financeiro | "Pago"/caixa = recebido **neste mês** (data do recebimento); "Pendente"/a receber = **todas** as dívidas em aberto. Pedidos mistos entram numa linha própria. | `_painel_v4_financeiro`, `_financeiro_mes` |
| Cancelar | `cancelar`/`sair`/`parar`/`voltar`/`0` no meio de uma operação pedem confirmação (1 Sim / 2 Não, continuar). | estado `confirmar_cancelamento` |
| Dados públicos | Nada de telefones, IDs da Meta, tokens ou nomes reais no repositório. | scripts e testes |
| Dashboard | `/dashboard/*` exige `X-Dashboard-Token` = `DASHBOARD_TOKEN`; sem token configurado, 404. | `app/routes/dashboard.py` |

Antes destas: pagamento na entrega regista data e operador; divergências de
carga e pagamentos pendentes só aparecem ao gestor no painel.

**Decisões de negócio novas devem ser perguntadas aos sócios** (Danilo e
Paulo), não inferidas pelo agente.

## 5. Histórico: consolidação de setembro de 2026

Havia 28 branches no GitHub, com o sistema em produção a partir de um deles.
O PR `claude/repository-comprehensive-review-5a0cpr` (aberto a partir do fork
`paulofelipeassis/olt-gestao-residuos-revisao-claude`) consolidou tudo:

- **Base:** `refactor/modularizacao-contentor-carrinha` (commit `56aa38e`), o
  branch mais avançado; 20 branches já estavam contidos nele.
- **Integrados por merge:** `feature/recolha-contentores-paulo`,
  `feature/cadastro-gestores-lucas-secretario` (telefones reais removidos;
  usar `OLT_GESTORES`), `feature/meta-outbox-whatsapp` (+ estabilização e
  rate-limit; a fila por telefone foi portada para o webhook atual e o dedup
  antigo `whatsapp_processed_messages` removido por ser superado pelo módulo
  3), `feature/testes-sistema-olt` (adaptado ao módulo 3) e `main` (README).
- **Não integrado:** `feature/menu-cadastro-unitario` (superado pelo Menu V4).
- Verificação: `git branch -r --no-merged HEAD` deve listar só esse branch.

Commits de correção e decisões, por tema (ver `git log` para detalhes):
validação de valor monetário; painel com carrinha em atendimento; "Recolher
Hoje"; assinatura da Meta e aviso de falha; acentuação; auditoria do
pagamento; colisão de IDs em `resolver`; payload malformado; comandos
"entrega"/"recolha"; divergência pelo total do pedido; frota; "novo" → Novo
Pedido; expiração; financeiro; confirmação de cancelamento; "Próximo passo"
nas fotos; limites da Cloud API; dados fictícios; token do dashboard; cargas
no painel; teste de ponta a ponta.

## 6. Convenções

- Mensagens ao utilizador em português de Portugal, com acentos.
- Um commit por tema, com o porquê no corpo; testes junto da mudança.
- Mudou fluxo? Rode `tests/system` e a suíte inteira antes de enviar.
- Nunca use telefones, IDs da Meta, tokens ou nomes reais em testes, scripts
  ou documentação (use `3519000000xx`, `1000000000000xx`).
