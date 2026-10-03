# Pendências após a consolidação (setembro de 2026)

Contexto, arquitetura e regras já decididas: ver [`AGENTS.md`](AGENTS.md).
Estado do branch: 28 branches consolidados (só `feature/menu-cadastro-unitario`
ficou de fora, por estar superado), 8 decisões de negócio implementadas,
suíte completa verde (1621 testes) e teste de ponta a ponta com 22 pedidos.

## 1. Ao aceitar o PR (servidor de produção)

1. **Preencher `WHATSAPP_APP_SECRET` e validar uma assinatura Meta** no `.env`
   (Meta → App → Configurações → Básico → Chave secreta). Com `ENV=production`,
   a aplicação agora recusa iniciar sem o segredo; o webhook também rejeita a
   configuração inválida antes de processar mensagens.
2. **Trocar o verify token do webhook** (`WHATSAPP_VERIFY_TOKEN`) no `.env` e
   no painel da Meta: o valor antigo esteve público no repositório. Rotacione
   também qualquer credencial que possa ter coexistido no histórico, sem
   reproduzir os valores em tickets, logs ou commits.
3. Se alguém usa `GET /dashboard/*`, definir `DASHBOARD_TOKEN` e enviar o
   cabeçalho `X-Dashboard-Token`. Sem isso os endpoints respondem 404.
4. Conferir a frota: a tabela `contentores` é semeada com 1–20. Números em uso
   que não estejam lá precisam de `cadastrar contentor N` pelo gestor antes da
   próxima entrega (a entrega passou a recusar número fora da frota).
   Contentores entregues antes deste PR continuam `disponivel` na tabela até
   serem despejados; se necessário, ajuste com `alterar contentor`.
5. Rodar `scripts/setup_local_olt_entulhos.ps1` uma vez numa máquina Windows
   para validar a alteração (agora mantém os valores já preenchidos no `.env`);
   não havia PowerShell no ambiente da revisão.

## 2. Depois do merge

1. Apagar os branches antigos (todos estão contidos no `main` após o merge).
2. Avaliar tornar o repositório privado ou produzir um mirror saneado: o
   histórico do git ainda contém telefones, IDs da Meta e o verify token
   removidos do código. Não reescreva histórico sem um plano aprovado, backup
   verificável e rotação prévia das credenciais.

## 3. Decisões de negócio em aberto (perguntar aos sócios)

1. **Pagamento da carrinha no local:** a entrega de contentor pergunta se o
   cliente pagou; a chegada/partida da carrinha não pergunta ("O pagamento não
   foi alterado"). Deve perguntar?
2. **Divergência de carga resolvida:** hoje "resolver carga N" só marca como
   resolvida. Deve registar cobrança adicional ou ajuste de valor?
3. **e-GAR / códigos LER:** o sistema grava "Entulho Limpo"/"Entulho Misto",
   sem código LER nem guia e-GAR. Em Portugal o transporte de resíduos exige
   e-GAR no SILiAmb (Portaria n.º 145/2017); os RCD costumam usar LER
   17 01 07 (misturas de betão, tijolos, ladrilhos) e 17 09 04 (mistura de
   RCD). Confirmar com a empresa se isto é feito fora do sistema ou se o
   sistema deve guardar o código LER e o número da e-GAR por despejo.
4. **Menu principal em texto:** por decisão do Danilo (julho/2026) o menu
   1–5 é texto numerado; tudo o resto virou botões/listas em 03/10/2026. Se a
   equipa preferir, basta tirar `_is_main_menu` de `send_whatsapp_message`
   para o menu virar lista (2 toques em vez de 1 algarismo).
5. **Horários da carrinha:** a lista oferece 08:00–16:00 de hora em hora
   (`HORARIOS` em `app/agents/pedido_v24/opcoes.py`); ajustar se o horário de
   trabalho mudar.

## 4. Dívida técnica

1. **Outbox não ligada:** `whatsapp_outbox_service.py`/`worker.py` (retry,
   backoff, limite por destinatário da Meta) existem e têm testes, mas o
   webhook ainda envia a resposta diretamente. Ligar exige um worker a correr
   no servidor; decidir antes como o serviço é executado em produção.
2. **Mesma etapa em três lugares** (agente de contentor, de carrinha e backend
   `PedidoV24Agent`). Extrair as regras para módulos partilhados, como
   `app/agents/pedido_v24/despejo.py`, etapa a etapa.
3. **Cadastro legado (`AluguerContentor`)**: já não é aberto pelo menu; planear
   migração dos registos ativos e remoção do código.
4. **`/dashboard/alugueres/vencendo-amanha` e `/dashboard/lembretes`** só leem
   o legado (`AluguerContentor`); não incluem pedidos V24.
