# Pendências da revisão (Claude Code)

## Feito neste branch
- 10 commits de correção (webhook com assinatura da Meta, painel com carrinha em atendimento, loop do despejo, "Recolher Hoje", validação de valor, colisão de IDs em `resolver`, auditoria do pagamento na entrega, comandos "entrega"/"recolha", payload malformado, acentuação).
- Merges: `feature/recolha-contentores-paulo`, `feature/cadastro-gestores-lucas-secretario` (telefones reais removidos do código; usar `OLT_GESTORES`) e `feature/meta-outbox-whatsapp` (fila por telefone portada para o webhook atual; dedup antigo removido por ser superado pelo módulo 3; outbox mantida sem ligação ao envio, como no branch original).

## Falta fazer
1. Rodar a suíte completa (`python -m pytest -q`) após o merge da outbox; só os arquivos afetados foram validados.
2. Merge de `origin/feature/testes-sistema-olt` (commit bd960d7, `tests/system/`), adaptando autorização e dedup ao módulo 3.
3. Merge de `origin/main` e novo README que descreva o sistema atual (Menu V4, carrinhas, `WHATSAPP_APP_SECRET`).
4. `feature/menu-cadastro-unitario` não deve ser integrado (superado pelo Menu V4).
5. Após aceitar: preencher `WHATSAPP_APP_SECRET` no `.env` do servidor.
6. Apagar os branches antigos depois do merge e avaliar tornar o repositório privado (há telefones, IDs da Meta e verify token no histórico).

## Decisões de negócio em aberto
1. A tabela de contentores (1–20) é a verdade da frota? Hoje a entrega aceita número inexistente e não atualiza o estado.
2. O cadastro legado ("novo") ainda é usado?
3. Divergência de resíduo: por contentor ou por pedido? Gravar o resíduo real mesmo sem cota (e-GAR/LER)?
4. Financeiro do mês pela data de recebimento?
5. Tempo de expiração dos fluxos v24 abandonados.
6. "voltar"/"0" cancelam o fluxo inteiro; devem voltar um passo?
