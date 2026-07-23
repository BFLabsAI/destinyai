# destinyai

Instalador de sessão + skill da API não-oficial da Destiny (DestinyGen AI,
destinyai.com.br) para agentes de IA (Claude Code, e qualquer outra
ferramenta que leia `~/.agents/skills`).

Não existe API oficial pública da Destiny — o que este pacote instala é o
resultado de uma engenharia reversa completa e testada (login por sessão de
cookie, geração/extensão de vídeo, polling, download). Detalhes técnicos
completos ficam na skill instalada (`SKILL.md` + `references/`).

## Uso

```bash
npx destinyai
```

Ele vai pedir email e senha da conta Destiny, testar o login, e instalar:

- `~/.destiny/.env` — credenciais (email/senha), `chmod 600`
- `~/.destiny/session.json` — cookie de sessão + validade (30 dias)
- `~/.agents/skills/destiny-api/` — conteúdo real da skill (SKILL.md,
  documentação de referência, client Python pronto pra uso)
- `~/.claude/skills/destiny-api` — symlink pro diretório acima (opcional,
  perguntado durante o setup; pode recusar se só quiser o `.agents/skills`)

Depois de instalado, qualquer histórico de geração fica indexado em
`~/.destiny/history.db` (SQLite) e todo vídeo baixado cai em
`~/.destiny/downloads/`.

### Modo não-interativo (CI / outro agente rodando o setup)

```bash
DESTINY_EMAIL=voce@exemplo.com DESTINY_PASSWORD=senha npx destinyai --yes
```

Flags disponíveis:

| Flag | Efeito |
|---|---|
| `--email=...` | Email (senão lê `DESTINY_EMAIL` do ambiente, senão pergunta) |
| `--password=...` | Senha (senão lê `DESTINY_PASSWORD`, senão pergunta) |
| `--yes` | Não pergunta nada — assume sessão nova se não houver cookie válido, instala em `.agents` e `.claude` |
| `--targets=claude,agents` | Onde instalar a skill (por padrão pergunta; sempre inclui `agents` como fonte real) |

Rodar de novo com uma sessão ainda válida em `~/.destiny/session.json` só
reinstala/atualiza os arquivos da skill, sem pedir credenciais de novo.

## Testar um vídeo depois de instalado

```bash
python3 ~/.agents/skills/destiny-api/scripts/destiny_client.py account
python3 ~/.agents/skills/destiny-api/scripts/destiny_client.py generate \
  --provider veo --model veo-3.1-fast --aspect-ratio 9:16 \
  --resolution 720p --duration 8 --prompt "um gato andando num jardim" --wait
```

(Requer `pip install requests` — única dependência externa do client Python;
o resto é biblioteca padrão, incluindo SQLite.)

## Desenvolvimento

```bash
npm install
npm run dev      # roda direto via tsx, sem compilar
npm run build    # compila TypeScript -> dist/
npm start        # roda a versão compilada
```

`skill-payload/` é a cópia exata do que vai pra `~/.agents/skills/destiny-api`
— editar a skill em si (documentação, client Python) deve ser feito ali.

## Publicar

```bash
npm run build
npm publish   # exige estar logado (npm login) e o nome do pacote disponível
```

Nome confirmado e disponível no npm: `destinyai`.
