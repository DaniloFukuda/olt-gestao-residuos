# OLT PR #6 — Remediação de Segurança

**Missão:** `OLT-PR6-SECURITY`
**Base:** PR #6 `claude/repository-comprehensive-review-5a0cpr` → `main`
**HEAD de origem:** `49e1e2498ff448f34555e35b5f69c0a62df797be`
**Worktree isolado:** `fix/olt-pr6-security`
**Escopo de segurança:** nenhuma alteração em `main`, na branch de refatoração, em `.env`, em credenciais, no banco real, no histórico Git remoto ou em serviços externos.

## Resultado

A falha P0 de webhook fail-open foi corrigida para produção:

- Com `ENV=production` ou `ENV=prod`, `WHATSAPP_APP_SECRET` vazio ou composto apenas por espaços impede a inicialização da aplicação.
- Como defesa adicional, o webhook retorna **503** antes de processar qualquer mensagem se encontrar configuração de produção inválida no runtime ativo.
- Quando há segredo configurado, requisições sem assinatura válida continuam sendo rejeitadas com **401** antes de router, persistência, fila ou envio de resposta.
- Desenvolvimento e testes continuam suportando execução sem segredo, preservando o fluxo local simulado.

## Alterações realizadas

| Área | Alteração | Evidência |
|---|---|---|
| Gate de configuração | Criada `require_whatsapp_app_secret_in_production(settings)` | `app/core/config.py:50-53` |
| Inicialização | `create_app()` valida o requisito antes de criar schema/seed | `app/main.py:11-14` |
| Webhook | A dependência de assinatura converte configuração inválida de produção em HTTP 503, antes do processamento | `app/routes/webhook.py:31-51` |
| Assinatura Meta | Assinatura HMAC ausente, inválida ou de corpo diferente permanece 401 quando o segredo existe | `app/routes/webhook.py:45-54`; `tests/test_webhook_assinatura.py` |
| Cobertura | Adicionados testes para POST 503 sem segredo em produção, startup fail-closed, alias `prod` e segredo whitespace-only | `tests/test_webhook_assinatura.py` |
| Integração de rate limit | O cenário que simula produção passou a enviar segredo fictício e assinatura HMAC válida; isso evita mascarar o gate de segurança | `tests/test_whatsapp_meta_rate_limit.py:62-72, 481-492` |
| CI | Criado workflow de pytest, com permissões `contents: read`, `ENV=test`, SQLite efêmero e timeout de 20 minutos | `.github/workflows/pytest.yml` |
| Configuração | `.env.example` documenta o requisito para produção | `.env.example:3-6` |
| Runbook | README e pendências registram gate, rotação manual e risco histórico sem repetir valores sensíveis | `README.md:87,117`; `PENDENCIAS.md:10-16,28-33` |

## Testes executados

Todos no worktree isolado e com SQLite temporário fora da árvore original:

| Comando / seleção | Resultado | Duração |
|---|---:|---:|
| RED: `test_producao_sem_app_secret_rejeita_webhook` | Falhou corretamente antes da implementação: esperado 503, obtido 200 | 0,58 s |
| RED: `test_producao_sem_app_secret_impede_inicializacao` | Falhou corretamente antes da implementação: não levantava erro | 0,65 s |
| Testes focados de assinatura, dashboard e dedup | 74 passed | 30,52 s |
| Assinatura após cobertura final | 14 passed | 7,60 s |
| Assinatura + integração de rate limit assinada | 15 passed | 5,49 s |
| Suíte integral final | **1624 passed, 22 skipped, 0 failed, 0 errors** | **570,20 s (9:30)** |

A primeira execução integral após a alteração identificou uma regressão de teste: um teste que modelava `ENV=production` não fornecia assinatura Meta. O comportamento 503 era correto sob o novo contrato. O teste foi corrigido para configurar segredo fictício e assinar o payload; a suíte final acima valida a correção.

## Revisão independente

Revisão independente final do diff:

- `passed: true`
- `security_concerns: []`
- `logic_errors: []`

Sugestão não bloqueante: fixar GitHub Actions por SHA imutável e adotar lock de dependências para maior reprodutibilidade de supply chain.

## Investigação de exposição histórica

- O commit de sanitização existente remove valores do estado atual do PR, mas a documentação do próprio projeto confirma que telefones, IDs Meta e o verify token anterior continuam no histórico Git.
- A investigação utilizou somente padrões/categorias e metadados; nenhum valor anterior foi exibido, lido de `.env` ou reproduzido neste relatório.
- Nenhuma reescrita de histórico, remoção de branch remoto, rotação automática ou alteração de credencial foi executada.

## Pendências humanas obrigatórias antes de deploy

1. Provisionar `WHATSAPP_APP_SECRET` por canal seguro no ambiente de produção e validar uma chamada Meta assinada em ambiente controlado.
2. Rotacionar `WHATSAPP_VERIFY_TOKEN` no provedor e no ambiente de produção; rotacionar qualquer credencial que possa ter coexistido no histórico exposto.
3. Confirmar que o secret e os tokens não aparecem em logs, tickets ou commits.
4. Decidir, com backup e plano aprovado, se o repositório permanecerá privado ou se será criado mirror/histórico saneado. Não reescrever histórico sem autorização explícita.
5. Publicar o workflow CI junto com esta alteração e configurar branch protection/check obrigatório conforme a política do repositório.

## Estado final

**Pronto para revisão humana e para encaminhar como patch de segurança.**
**Não pronto para deploy até a conclusão comprovada das pendências humanas acima.**

Nenhum merge, push, deploy, commit ou rotação de credencial foi efetuado.
