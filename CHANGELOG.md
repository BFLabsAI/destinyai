# Changelog

Todas as mudanças notáveis deste pacote são documentadas aqui.
Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/),
versionamento segue [SemVer](https://semver.org/lang/pt-BR/).

## [Unreleased]

### Conhecido / planejado
- `history.db` e `~/.destiny/downloads/` não são isolados por conta — ao
  trocar de credenciais numa instalação existente (novo `email`/`password`),
  o histórico e os vídeos baixados da conta anterior continuam misturados
  com os da conta nova. Planejado: coluna `account_email` no SQLite e
  namespacing de pastas por conta, se virar necessidade real de uso
  multi-conta na mesma máquina/VPS.
- Workflow `storyboard` ("Grok 30s") da Destiny existe no backend mas está
  desativado pela própria aplicação — não exposto na skill até isso mudar.
- Faltam testar/confirmar: valores de `duration`/`resolution` inválidos por
  provider (comportamento de rejeição vs. normalização silenciosa) e o
  formato exato de um job que falha *durante* o processamento (só o de falha
  na criação, HTTP 402, foi confirmado).

## [0.1.1] — 2026-07-23

### Corrigido
- `engines.node` no `package.json` pedia `>=22.5.0` sem necessidade — esse
  requisito veio de um exemplo de client Node.js (na documentação da skill)
  que usa `node:sqlite`, mas o **instalador em si** não usa SQLite, só
  `fetch` e `fs` nativos. Corrigido para `>=18`, que é o mínimo real.
  Detectado ao validar a instalação numa VPS com Node 20.20.2 (funcionava só
  porque `engines` sem `engine-strict` é aviso, não bloqueio).

## [0.1.0] — 2026-07-23

Primeira versão publicada.

### Adicionado
- CLI interativo (`npx destinyai`) usando `@clack/prompts`: pede email/senha,
  testa login real contra a API da Destiny, mostra saldo de créditos.
- Suporte a modo não-interativo via flags (`--email`, `--password`, `--yes`,
  `--targets=claude,agents`) e variáveis de ambiente (`DESTINY_EMAIL`,
  `DESTINY_PASSWORD`) — para rodar em CI/VPS/outro agente sem prompt.
- Persistência de credenciais em `~/.destiny/.env` (`chmod 600`) e sessão de
  cookie em `~/.destiny/session.json`, com detecção de sessão ainda válida
  pra não pedir login de novo em execuções repetidas.
- Instalação da skill `destiny-api` sempre em `~/.agents/skills/destiny-api`
  (fonte real, nunca duplicada — apagada e recriada a cada execução) com
  symlink opcional em `~/.claude/skills/destiny-api`, mesmo padrão usado
  pela skill `skill-creator` (conteúdo único + atalho, nunca cópias
  divergentes).
- Skill instalada inclui:
  - `SKILL.md` — resumo operacional, tabela de comandos, gotchas de campo
    por provider (Veo/Grok) que evitam erro ou gasto de crédito à toa.
  - `references/api-guide.md` — documentação completa de todos os
    endpoints, campos, tabela de preços, formato de erros e clients de
    referência (Node.js, Python, bash).
  - `references/reverse-engineering.md` — histórico da investigação (como
    cada endpoint foi descoberto, bugs conhecidos do backend da Destiny).
  - `scripts/destiny_client.py` — client Python completo e executável (CLI
    + biblioteca importável), com:
    - autenticação automática (login inicial + relogin em `401`/sessão
      expirada, lendo sempre de `~/.destiny/.env`);
    - geração de vídeo (`create`) e extensão (`extend`) pros dois
      providers, com todos os campos e limites corretos por provider
      (inclui a correção do enum real de `aspectRatio` do Grok: `2:3`/`3:2`,
      não `3:4`/`4:3` como a UI da Destiny sugere);
    - polling de status com a fonte de verdade certa (`GET /api/videos/:id`,
      nunca `/api/history`, que fica travado em `"running"` mesmo com o
      vídeo pronto — bug conhecido documentado);
    - índice local em SQLite (`~/.destiny/history.db`) — 1 linha por
      geração, com prompt, payload completo (sem embutir base64 de imagem) e
      status, permitindo achar/rastrear vídeos por `id` ou por busca de
      texto no prompt sem depender da Destiny pra isso;
    - download de um vídeo específico ou de todos os prontos, sempre pra
      `~/.destiny/downloads/` por padrão (pasta única, sem duplicar
      download se o arquivo já existir localmente).

### Testado
- Fluxo completo validado ponta a ponta: `npx destinyai` rodando direto do
  registro do npm (não da pasta local), em `$HOME` isolado e depois numa VPS
  real (`bf-workspace`) — login, instalação da skill, geração de vídeo real,
  polling até conclusão, e download do `.mp4` funcionando em todos os casos.
