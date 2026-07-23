---
name: destiny-api
description: Gera, estende, monitora e baixa vídeos via a API não-oficial da Destiny/DestinyGen AI (destinyai.com.br), um SaaS que revende geração de vídeo por IA usando Veo (Google) e Grok (xAI). Use esta skill sempre que o usuário pedir para gerar um vídeo com IA, estender/continuar um vídeo já gerado, checar créditos/saldo da conta Destiny, listar ou procurar vídeos já gerados, ou baixar vídeos (um específico ou todos os que estiverem prontos) — mesmo que o usuário não diga explicitamente "Destiny" ou "API", ex.: "gera um vídeo de...", "cria um vídeo com o Veo/Grok", "estende esse vídeo mostrando...", "quantos créditos eu tenho na Destiny", "baixa os vídeos que eu gerei", "cadê aquele vídeo do gato que eu fiz". Não é a API oficial da Destiny (não existe uma pública) — é engenharia reversa documentada e testada; sempre usar o client em scripts/destiny_client.py em vez de reimplementar chamadas do zero.
---

# Destiny API (DestinyGen AI)

A Destiny é um SaaS de geração de vídeo por IA (revenda de **Veo**/Google e
**Grok**/xAI via o agregador GeminiGen). Não existe API pública oficial — o
que existe aqui é o resultado de engenharia reversa completa e testada
ponta a ponta (login, geração, extensão, polling, download).

## Antes de tudo: use o client pronto, não reimplemente

`scripts/destiny_client.py` já resolve autenticação (cookie de sessão,
relogin automático), geração, polling, download e indexação local em SQLite.
**Sempre prefira chamar esse script/importar essa classe** em vez de montar
requests HTTP do zero — ele já encapsula todos os detalhes chatos (formato
exato do cookie, campos por provider, onde salvar o quê).

```bash
# como CLI
python3 scripts/destiny_client.py account
python3 scripts/destiny_client.py generate --provider veo --model veo-3.1-fast \
  --aspect-ratio 9:16 --resolution 720p --duration 8 \
  --prompt "um gato laranja andando devagar em um jardim ensolarado" --wait

# como biblioteca (import direto no seu próprio script Python)
from destiny_client import DestinyClient
client = DestinyClient()
job = client.create_video(prompt="...", provider="veo", model="veo-3.1-fast",
                           aspect_ratio="9:16", resolution="720p", duration=8)
finished = client.wait_for_video(job["requestId"])
client.download_by_id(job["requestId"])
```

Dependência: `pip install requests` (única lib externa; SQLite e o resto são
stdlib). Se o ambiente for Node/TypeScript em vez de Python, use os clients
equivalentes em `references/api-guide.md` §15 (Node.js) ou §17 (bash/curl) —
mesma lógica, mesmos campos.

## Onde tudo fica salvo (mesmo em toda instalação)

```
~/.destiny/.env           # DESTINY_EMAIL / DESTINY_PASSWORD — credenciais, escritas 1x pelo instalador
~/.destiny/session.json   # cookie de sessão + validade — gerenciado sozinho pelo client
~/.destiny/history.db     # SQLite — 1 linha por geração (id, prompt, payload, status, local_path)
~/.destiny/downloads/     # todo .mp4 baixado cai aqui, nomeado <requestId>.mp4
```

Se `~/.destiny/.env` não existir, PARE e avise o usuário que precisa rodar o
instalador da skill primeiro — não peça a senha diretamente na conversa.

## O que a skill cobre — visão rápida

| Você quer... | Comando/método |
|---|---|
| Ver créditos disponíveis | `client.account()` / `destiny_client.py account` |
| Gerar vídeo novo | `client.create_video(...)` / `generate` |
| Estender vídeo existente | `client.extend_video(...)` / `extend` |
| Saber se um vídeo terminou | `client.get_video_status(id)` / `status <id>` |
| Esperar terminar (bloqueante) | `client.wait_for_video(id)` / `wait <id>` |
| Baixar 1 vídeo específico | `client.download_by_id(id)` / `download <id>` |
| Baixar tudo que já estiver pronto | `client.download_all_ready()` / `download-all` |
| Achar um vídeo pelo prompt | `client.search_generations("texto")` / `search "texto"` |

## Regras que importam (evitam erro/gasto de crédito à toa)

1. **`prompt` precisa ter ≥ 8 caracteres** — o backend rejeita antes de
   cobrar, mas não vale a pena nem tentar com menos.
2. **Nunca confie no `status` de `/api/history`** — trava em `"running"`
   pra sempre, mesmo com o vídeo pronto. A fonte da verdade é sempre
   `GET /api/videos/:id` (é o que `get_video_status`/`wait_for_video` usam).
3. **`aspectRatio` do Grok tem uma pegadinha:** os valores realmente aceitos
   pelo backend são `16:9`, `9:16`, `1:1`, `2:3`, `3:2` — **não** `3:4`/`4:3`
   (isso é só o rótulo que aparece na UI da Destiny; o valor de API pra
   "Vertical (3:4)" é `2:3`, e pra "Horizontal (4:3)" é `3:2`). Mandar
   `3:4`/`4:3` direto dá erro 400 sem custar crédito, mas evite testar isso
   de novo — já está confirmado.
4. **Campos válidos são diferentes por provider** — não misture limites do
   Veo com os do Grok. Tabela completa em `references/api-guide.md` §7/§8.
   Resumo:
   - Veo: `aspectRatio` (16:9, 9:16), `resolution` (720p, 1080p), `duration`
     (4, 6, 8s). Custo fixo: 0.5 crédito por vídeo, não varia por
     resolução/duração.
   - Grok: `aspectRatio` (16:9, 9:16, 1:1, 2:3, 3:2), `resolution` (480p,
     720p), `duration` (6, 10, 15s), `mode` (`custom`, `normal`,
     `extremely-crazy`, `extremely-spicy-or-crazy` — literais exatos, com
     hífen). Custo varia por resolução+duração — ver tabela em §9 do guia.
5. **Imagens de referência são base64 embutido no JSON**, não upload
   multipart. Use `file_to_data_url(path)` (já em `destiny_client.py`) pra
   converter. Veo aceita `imageDataUrl` (início) + `lastImageDataUrl` (fim);
   Grok só aceita `imageDataUrl` (e o prompt deve conter `@image` literal pra
   referenciá-la).
6. **`videoUrl` expira** — é uma URL assinada tipo S3. Baixe assim que
   `status` virar `"done"`; não guarde a URL como link permanente.
7. **Créditos insuficientes = erro 402 `NOT_ENOUGH_CREDIT`, `retryable:
   false`** — não insista automaticamente, avise o usuário.

## Quando ir além deste resumo

- **`references/api-guide.md`** — documentação completa e testada: todo
  endpoint, todo campo, tabela de preços inteira, formato exato de erros,
  clients de referência completos em Node.js/Python/bash. Leia isso antes de
  usar qualquer campo/valor que não esteja resumido acima.
- **`references/reverse-engineering.md`** — histórico da investigação
  original: como cada endpoint foi descoberto, bugs conhecidos do backend da
  Destiny (ex.: `/api/history` travado, tela de "Estender vídeo" quebrada na
  UI oficial), e o que ainda não foi testado. Útil se algo se comportar
  diferente do documentado — pode ser um desses bugs conhecidos, não um erro
  seu.

## Workflow "storyboard" — não usar

Existe um terceiro `workflow` (`"storyboard"`, "Grok 30s") encontrado no
código-fonte do frontend da Destiny, mas a própria aplicação o marca como
temporariamente indisponível. **Não usar nem sugerir** até isso mudar — ver
`references/reverse-engineering.md` se precisar dos detalhes técnicos.
