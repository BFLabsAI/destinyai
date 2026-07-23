# DestinyGen AI (destinyai.com.br) — Plano de Engenharia Reversa da API

Análise feita navegando na aplicação (Playwright) com o login em `documents/creds`,
inspecionando as chamadas de rede reais feitas pelo frontend, complementado com
chamadas diretas via `curl` para expor headers que o JS do navegador não enxerga
(ex: `Set-Cookie`).

## 1. O que é a aplicação

"DestinyGen AI Studio" — um SaaS de geração de vídeo por IA. O usuário escreve um
prompt (e opcionalmente sobe imagens de referência) e a plataforma gera o vídeo
usando um destes provedores, atuando como **revenda/proxy** de:

- **Veo** (Google AI) — via um agregador chamado **GeminiGen**
- **Grok** (xAI) — modelo `grok-video`

O sistema cobra em **créditos** (comprados via checkout `amplopay`) e mantém
histórico de gerações.

## 2. Autenticação — como funciona o "token"

**Não é Bearer token / JWT no header.** É sessão via **cookie HttpOnly**:

```
POST /api/auth/login
Content-Type: application/json

{
  "email": "...",
  "password": "...",
  "fullName": "",
  "phone": "",
  "confirmPassword": ""
}
```

Resposta (200):
```json
{
  "authenticated": true,
  "user": {
    "email": "...",
    "fullName": "bruno falcao",
    "id": "usr_00000000-0000-0000-0000-000000000000",
    "isAdmin": false,
    "phone": "00000000000"
  }
}
```

E o header de resposta que importa (só aparece via `curl -i`, o JS do navegador
nunca vê isso por ser `HttpOnly`):

```
Set-Cookie: destiny_session=<token hex>; Max-Age=2592000; Path=/;
            Expires=...; HttpOnly; SameSite=Lax
```

- **Sem `Secure` flag** no cookie (mesmo sendo HTTPS) — vale reportar aos sócios/dev
  como ponto de atenção de segurança, é fácil de corrigir.
- **Sem CSRF token** aparente — todas as chamadas subsequentes funcionam só com o
  cookie, sem header extra.
- Validade: 30 dias (`Max-Age=2592000`).
- Não existe token em `localStorage`/`sessionStorage` (só preferências: tema,
  idioma, histórico local). Toda autenticação é 100% via cookie.

**Implicação prática para construir uma API/integração nossa:** um client HTTP
"stateless" com só um Bearer token não funciona aqui. É preciso:
1. Fazer o POST de login uma vez.
2. Guardar o cookie `destiny_session` (cookie jar).
3. Reenviar esse cookie em toda chamada subsequente (`Cookie: destiny_session=...`).
4. Reautenticar quando expirar (30 dias, ou se vier 401).

Isso é trivial de reproduzir em qualquer linguagem (Python `requests.Session()`,
Node `axios` com `axios-cookiejar-support`, etc.) — não precisa de navegador/Playwright
para uso contínuo, só para descobrir os endpoints (o que já fizemos).

## 3. Endpoints mapeados até agora

Todos sob `https://www.destinyai.com.br`, prefixo `/api`.

| Método | Rota | Função |
|---|---|---|
| POST | `/api/auth/login` | Login, gera cookie de sessão |
| GET | `/api/account` | Dados da conta + saldo de créditos |
| GET | `/api/billing/plans` | Planos, preços por geração, pedidos, saldo |
| GET | `/api/history?filter_by=video&items_per_page=30&page=1` | Histórico de vídeos gerados |
| POST | `/api/videos` | **Dispara a geração de vídeo** |
| GET | `/api/videos/:requestId` | **Polling de status da geração + URL final do vídeo** |

⚠️ **Bug confirmado: `/api/history` nunca reflete `status: "done"`.** Comparando
o mesmo vídeo nos dois endpoints:

- `GET /api/videos/b6b8a6c8-...` → `{"status":"done","progress":100,"videoUrl":"...mp4?..."}`
  (confirmadamente pronto, com URL do vídeo funcionando).
- `GET /api/history` → o mesmo `uuid` aparece como `{"status":"running","progress":100,...}`
  **para sempre** (mesmo dias depois / múltiplas consultas), nunca com `videoUrl`.

Isso é muito provavelmente a causa do bug que você viu no fluxo **"Estender
vídeo"** ("nenhum vídeo disponível" no seletor de vídeo-base): se aquele
seletor filtra os vídeos elegíveis usando o campo `status` de `/api/history`
em vez de consultar `/api/videos/:id` individualmente, ele nunca vai achar
nenhum vídeo "pronto", porque esse campo trava em `running`/100% no histórico.

**Implicação pra nossa integração:** nunca usar o `status` do `/api/history`
pra saber se um vídeo terminou — usar sempre `GET /api/videos/:id` (pelo
`uuid` que aparece em `/api/history`) pra checar o status real e pegar o
`videoUrl`. Isso também é um achado bom pra reportar aos devs da Destiny.

### `GET /api/account`
```json
{
  "liveApiConfigured": true,
  "fullName": "bruno falcao",
  "email": "...",
  "planId": "PP0001",
  "availableCredit": 20,
  "lockedCredit": 0,
  "destinyCreditBalance": 20,
  "benefits": []
}
```

### `GET /api/billing/plans`
```json
{
  "balance": 20,
  "generationPrices": [
    {"id": "grok-480p", "provider": "grok", "label": "Grok 480p", "priceCents": 60},
    {"id": "grok-720p", "provider": "grok", "label": "Grok 720p", "priceCents": 70},
    {"id": "veo-3", "provider": "veo", "label": "VEO 3", "priceCents": 50}
  ],
  "mode": "amplopay",
  "orders": [ /* histórico de compras de créditos, com checkoutUrl da amplopay */ ],
  "plans": [ /* pacotes de créditos disponíveis para compra: topup-20, topup-50, topup-100, topup-200 */ ]
}
```

### `POST /api/videos` — geração (Veo)
Payload capturado a partir de um envio real feito na tela "Criar novo":
```json
{
  "prompt": "um gato andando num patio ",
  "provider": "veo",
  "model": "veo-3.1-fast",
  "aspectRatio": "9:16",
  "resolution": "720p",
  "duration": 8,
  "mode": "custom",
  "workflow": "create"
}
```

Campos variáveis confirmados:
- `provider`: `"veo"` | `"grok"`
- `model`: para Veo → `veo-3.1-fast` | `veo-3.1-lite` | `veo-2`; para Grok → `grok-video`
- `aspectRatio`: `16:9` (Paisagem) | `9:16` (Retrato)
- `resolution`: `720p` | `1080p` (só aparece pra Veo)
- `duration`: `4` | `6` | `8` (segundos)
- `workflow`: `"create"` (existe também aba "Estender vídeo" → provavelmente `"extend"`, ainda não
  testado).

### ✅ Imagens de referência (Veo) — confirmado

**Não é upload multipart.** As duas imagens (início e fim) vão embutidas no
próprio corpo JSON do `POST /api/videos`, como **data URI base64**:

```json
{
  "prompt": "...",
  "provider": "veo",
  "model": "veo-3.1-fast",
  "imageDataUrl": "data:image/jpeg;base64,/9j/4QVoRXhpZgAAS...",       // primeira imagem
  "lastImageDataUrl": "data:image/jpeg;base64,/9j/4QRARXhpZgAAS...",  // última imagem
  "aspectRatio": "9:16",
  "resolution": "720p",
  "duration": 8,
  "mode": "custom",
  "workflow": "create"
}
```

- `imageDataUrl` → primeira imagem (opcional, sozinha já funciona).
- `lastImageDataUrl` → última imagem (opcional, só faz sentido junto com a primeira).
- Ambas confirmadas num teste real com as duas imagens juntas — o payload ficou
  com ~420KB nesse caso (imagens de ~200KB cada em base64).
- Isso significa que pra nossa integração não precisamos de um endpoint de
  upload separado nem `multipart/form-data`: é só ler o arquivo, converter pra
  base64 e montar a data URI (`data:image/jpeg;base64,<...>` ou `image/png`,
  `image/webp` conforme o tipo aceito pelo input: `.jpg`, `.jpeg`, `.png`, `.webp`).
- No resultado (`GET /api/videos/:id`), a miniatura da imagem de referência usada
  aparece em `thumbnailUrl` com sufixo `/ref/first-reference_200px.jpg` (em vez do
  formato padrão `<uuid>_0_600px.jpg` de quando não há imagem de referência).

### ✅ Prompt avançado — confirmado

O modo "Avançado" (alternado por um toggle `Básico`/`Avançado` na tela) **não é
um campo separado na API** — o frontend simplesmente monta um único `prompt`
concatenando rótulos fixos com o texto que o usuário digita em cada campo:

```
Main subject: <texto> Action: <texto> Setting / environment: <texto> Lighting / time of day: <texto> Visual style: <texto> Camera shot: <texto> Additional details: <texto>
```

Exemplo real capturado:
```
Main subject: um homem andando e falando trocando de cenario num estudio fotografico.
Action: andando dentro de um estudio e trocando o cenario.
Setting / environment: estudio fotografico em preto e branco.
Lighting / time of day: preto e branco cinematografico.
Visual style: preto e branco.
Camera shot: Close-up.
Additional details: um homem tirando uma foto, depois olhando para camera e dizendo:
você é seu melhor amigo! Faça mais por você!! com falas pausadas, aspecto dramatico,
pausa dramatica entra as falas.
```

Isso confirma o que você notou — não existe uma API separada de "prompt
estruturado" no backend do Veo/GeminiGen; é a Destiny que monta essa string
formatada e manda como um `prompt` comum. **Pra nossa própria integração,
podemos pular esse "quebra-galho" da UI e já mandar o prompt bem escrito
direto**, sem precisar simular os campos separados — só reproduzir esse
template se quisermos manter a mesma UX pro usuário final.

**Resposta imediata (202 — job aceito):**
```json
{
  "requestId": "aa1a13fe-86a0-11f1-817a-ba4f920ea6f2",
  "status": "running",
  "progress": 1,
  "provider": "veo",
  "model": "veo-3.1-fast",
  "usedCredit": 0.5,
  "balance": 19
}
```

O `requestId` é o identificador do job, usado no polling.

### ✅ Provider Grok — confirmado

Payload real capturado (com imagem de referência):
```json
{
  "prompt": "gere um video da pessoa na @image que esta em um estudio fazendo fotografias e dizendo uma frase motivacional para a camera com o intuito de: ...",
  "provider": "grok",
  "model": "grok-video",
  "imageDataUrl": "data:image/jpeg;base64,/9j/4QVoRXhpZgAAS...",
  "aspectRatio": "9:16",
  "resolution": "720p",
  "duration": 10,
  "mode": "custom",
  "workflow": "create"
}
```

Resposta imediata:
```json
{
  "requestId": "98a0f0fe-86a3-11f1-98da-6e33524f0b04",
  "status": "running",
  "progress": 1,
  "provider": "grok",
  "model": "grok-video",
  "usedCredit": 1.2,
  "balance": ...
}
```
`usedCredit: 1.2` bate exatamente com o preço da tabela `/api/billing/plans`
pra `grok-720p-10s` (`priceCents: 120` → 1.2 créditos). Confirma que o preço é
resolvido no backend a partir da combinação `resolution` + `duration`, não é um
campo enviado pelo client.

Diferenças do Grok em relação ao Veo (segundo você observou na UI, ainda não
testei uma a uma):
- **Só uma imagem de referência** (`imageDataUrl`) — não existe `lastImageDataUrl`
  pro Grok.
- Convenção de prompt: **`@image`** dentro do texto referencia a imagem
  selecionada (ex.: "a pessoa na @image..."). Isso é só uma instrução textual
  pro modelo entender a referência — não é um placeholder substituído pelo
  frontend, é literal `@image` mesmo no `prompt` enviado (visto no payload
  capturado acima).
- ✅ **`mode` — 4 literais confirmados** lendo o bundle JS (array `la` no
  código-fonte) e testados em request real: `"custom"`, `"normal"`,
  `"extremely-crazy"`, `"extremely-spicy-or-crazy"` (todos com **hífen**, não
  espaço — os rótulos da UI são "Normal", "Extremamente louco" e "Extremamente
  apimentado ou louco", mas o valor enviado à API é sempre o slug em inglês
  acima). Todos os 4 testados com sucesso em geração real.
- ⚠️ **`aspectRatio` no Grok — CORREÇÃO IMPORTANTE.** O que eu tinha
  documentado antes (`3:4`, `4:3`) estava **errado** — vinha do campo
  `apiValue` do bundle, mas o schema de validação real do backend (confirmado
  por um erro `400` real) é:
  ```
  Invalid enum value. Expected '16:9' | '9:16' | '1:1' | '2:3' | '3:2'
  ```
  Ou seja, pro Grok o valor correto **não é a razão de aspecto "bonita"**
  (`3:4`/`4:3`) — é um código interno da UI (`2:3` pro rótulo "Vertical
  (3:4)"; `3:2` pro rótulo "Horizontal (4:3)"). Tabela completa:

  | Rótulo na UI | Valor real aceito pela API |
  |---|---|
  | Paisagem (16:9) | `16:9` |
  | Retrato (9:16) | `9:16` |
  | Quadrado (1:1) | `1:1` |
  | Vertical (3:4) | **`2:3`** (não `3:4`) |
  | Horizontal (4:3) | **`3:2`** (não `4:3`) |

  Confirmado com 2 chamadas reais: `aspectRatio: "3:4"` e `aspectRatio: "4:3"`
  foram **rejeitados com 400** (sem cobrar crédito); `aspectRatio: "2:3"` foi
  aceito e gerou vídeo com sucesso.
- `resolution`: `480p` | `720p` (não tem 1080p como o Veo) — ambos confirmados.
- `duration`: `6` | `10` | `15` (segundos — diferente do Veo que é 4/6/8) —
  os 3 valores confirmados em request real.
- Tabela de preço completa por combinação (de `/api/billing/plans`,
  confirmada empiricamente em todas as combinações testadas):
  `grok-480p-6s`=0.6, `grok-480p-10s`=0.9, `grok-480p-15s`=1.2,
  `grok-720p-6s`=0.9, `grok-720p-10s`=1.2, `grok-720p-15s`=1.5 créditos.
- 🆕 **Achado bônus:** no Grok, o `GET /api/videos/:id` só **normaliza pra
  palavra** os 3 aspect ratios "nomeáveis" — enviei `"16:9"` e voltou
  `"landscape"`; `"1:1"` voltou `"square"`; `"9:16"` voltou `"portrait"`. Já
  `"2:3"` (testado) voltou **literal**, sem normalizar. Ou seja, o
  comportamento não é consistente — não dá pra assumir que `aspectRatio` na
  resposta sempre bate com o que foi enviado no request; é preciso tratar os
  dois formatos (`16:9`/`landscape`/etc.) ao exibir pro usuário. Nos testes
  de Veo isso não aconteceu — a resposta sempre ecoou a razão numérica
  enviada (ex. `"aspectRatio":"16:9"`).

### `GET /api/videos/:requestId` — polling de status ✅ confirmado

O frontend faz polling a cada **~6 segundos** neste endpoint até o job terminar.

Enquanto processando:
```json
{
  "id": "aa1a13fe-86a0-11f1-817a-ba4f920ea6f2",
  "status": "running",
  "progress": 1,
  "usedCredit": 0.5,
  "duration": 8,
  "aspectRatio": "9:16",
  "resolution": "720p"
}
```

Quando termina (nesse teste levou ~1min20s do POST até `status: "done"`):
```json
{
  "id": "aa1a13fe-86a0-11f1-817a-ba4f920ea6f2",
  "status": "done",
  "progress": 100,
  "videoUrl": "https://edge-files.snapgen.ai/geminigen-prd-upload-bucket/2005569/generated_result/video/aa1a13fe-86a0-11f1-817a-ba4f920ea6f2/20260723_141324_0_UTC_0.mp4?response-content-type=application%2Foctet-stream&AWSAccessKeyId=...&Signature=...&Expires=1785420882",
  "thumbnailUrl": "https://r3t3.c16.e2-3.dev/geminigen-prd-public-bucket/thumbnails/2005569/aa1a13fe-86a0-11f1-817a-ba4f920ea6f2/aa1a13fe-86a0-11f1-817a-ba4f920ea6f2_0_600px.jpg",
  "usedCredit": 0.5,
  "duration": 8,
  "aspectRatio": "9:16",
  "resolution": "720p"
}
```

- `videoUrl` é uma **URL assinada (presigned, estilo S3)** com `AWSAccessKeyId`,
  `Signature` e `Expires` (timestamp Unix) — ou seja, **expira** e não deve ser
  guardada como definitiva; para uso real precisamos baixar o arquivo assim que
  `status` vira `done` e persistir nós mesmos (ou versionar a URL com sua
  expiração).
- Bucket é da infra do GeminiGen/Snapgen (`geminigen-prd-upload-bucket`,
  `edge-files.snapgen.ai`), reforçando que a Destiny é uma camada de revenda em
  cima desse agregador.
- `status` observados: `running` → `done`. Existe também um `errorCode`/`error`
  quando falha na criação do job (visto no teste anterior com `402`), mas ainda
  não vimos o formato de uma falha *durante* o processamento (status tipo
  `failed`) — assumir que existe e tratar defensivamente.

⚠️ **Nota sobre o teste anterior com erro 402 (`NOT_ENOUGH_CREDIT`):** na
tentativa anterior a API estava em manutenção (segundo você) e recusou o job
mesmo com saldo suficiente. Depois que a manutenção terminou, uma geração real
funcionou normalmente e debitou exatamente os `0.5` crédito esperados
(saldo caiu de 19.5 pra 19). Ou seja, não era um bug de unidade — era
instabilidade temporária da API/upstream durante a manutenção. Ainda assim,
vale sempre tratar `402` no client como "sem saldo, retryable: false" e não
insistir automaticamente.

### ✅ Fluxo "Estender vídeo" (`workflow: "extend"`) — confirmado

A UI tem um bug (ver seção anterior sobre `/api/history`) que impede escolher um
vídeo-base pela tela — o seletor mostra "nenhum vídeo disponível" mesmo tendo
vídeos prontos. Contornamos isso lendo o **bundle JS do frontend**
(`/assets/index-*.js`) pra achar o formato exato do payload que o código já
sabia montar, e disparamos direto via `fetch`/`curl`. Funcionou de primeira:

```json
{
  "prompt": "continue o vídeo mostrando a pessoa saindo do estúdio e acenando pra câmera",
  "provider": "veo",
  "model": "veo-3.1-fast",
  "aspectRatio": "9:16",
  "resolution": "720p",
  "duration": 8,
  "mode": "custom",
  "workflow": "extend",
  "refHistory": "b6b8a6c8-869d-11f1-8a7c-e6b95c6cb394"
}
```

- **`refHistory`** é o campo-chave: recebe direto o **`uuid`** (string) do vídeo
  de origem já concluído — não é um objeto, não precisa de upload de frame.
- Resposta imediata (202) igual ao `create`: `requestId`, `status: "running"`,
  `usedCredit`, `balance`.
- Durante o processamento, o `thumbnailUrl` intermediário aponta pro **último
  frame do vídeo original** (`.../ref/<uuid-original>_last_frame_200px.jpg`),
  confirmando que ele usa esse frame como ponto de partida da extensão.
- Ao concluir, resposta idêntica ao fluxo normal: `status: "done"` +
  `videoUrl` (mesmo padrão de URL assinada/expirável) + `thumbnailUrl` final.
- Testado com sucesso ponta a ponta: POST → polling → `done` com vídeo pronto,
  gastando exatamente `0.5` crédito (mesmo preço do Veo 3, o `duration`/`resolution`
  da extensão que definem o custo, não é cobrança extra por "ser extensão").
- No código-fonte, quando `workflow==="extend"`, o frontend **reaproveita**
  automaticamente `model`, `resolution` e `duration` do vídeo de origem (o
  usuário só edita o `prompt`) — mas nada impede a nossa integração de mandar
  valores diferentes manualmente, já que é só um campo JSON comum.

⚠️ **Recomendação pra reportar aos devs da Destiny:** o bug do `/api/history`
travado em `"running"` é o que quebra essa tela pro usuário final — vale
priorizar o conserto, porque hoje ninguém consegue estender vídeo pela
interface, só via chamada direta como fizemos aqui.

### 🆕 Achado bônus: existe um terceiro workflow, `"storyboard"` (Grok 30s)

Vasculhando o bundle JS aparece um modo **"Grok 30s"** (`createStoryboard` na
UI) que **não vimos na tela ainda** — provavelmente escondido atrás de alguma
flag ou fora do fluxo principal ("Criar novo" / "Estender vídeo"). O payload
usa outro campo em vez de `prompt` único:

```js
storyboardScenes: [{ duration, mode, prompt }, ...]  // várias cenas
imageDataUrl: <primeira imagem, se houver>
workflow: "storyboard"
```

Ou seja, um vídeo de até 30s montado a partir de **múltiplas cenas**, cada uma
com seu próprio `prompt`, `mode` e `duration`. Não testamos isso ainda (nem
achamos o botão na UI) — vale investigar se está mesmo acessível ou se é uma
feature em desenvolvimento/desativada (o texto "modo Grok 30s esta
temporariamente indisponivel" também aparece no bundle, sugerindo que pode
estar desligada de propósito no momento).

## 4. Ainda não mapeado (próximos passos)

1. **Fluxo `storyboard`/"Grok 30s"** — achado no bundle mas não testado; parece
   estar temporariamente desativado segundo o próprio texto da aplicação.
2. **Valores literais do `mode` do Grok** — só vimos `"custom"` até agora; falta
   testar `normal`, `extremely crazy` e `extremely spicy`/`crazy` pra saber o
   literal exato que cada um manda no JSON.
3. **Combinações de `aspectRatio`/`resolution`/`duration` ainda não testadas**:
   - Veo: só testamos `9:16` + `720p`/`1080p` + `8s`. Falta `16:9` e `4s`/`6s`.
   - Grok: só testamos `9:16` + `720p` + `10s`. Faltam `16:9`, `1:1`, `3:4`,
     `4:3`, `480p`, e `6s`/`15s`.
4. Confirmar o formato de um job que **falha** durante o processamento (não só
   na criação) — útil pra tratamento de erro robusto no client.

~~Endpoint de upload de imagem de referência~~, ~~estrutura do prompt avançado~~,
~~payload do provider Grok~~ e ~~fluxo "Estender vídeo"~~ ✅ já mapeados — ver
seção 3 acima.

## 5. Como replicar isso fora do navegador (script simples)

```bash
# 1. login e guarda cookie
curl -s -c cookies.txt -X POST https://www.destinyai.com.br/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"...","password":"...","fullName":"","phone":"","confirmPassword":""}'

# 2. qualquer chamada autenticada reaproveita o cookie
curl -s -b cookies.txt https://www.destinyai.com.br/api/account

# 3. disparo de geração (retorna requestId)
curl -s -b cookies.txt -X POST https://www.destinyai.com.br/api/videos \
  -H "Content-Type: application/json" \
  -d '{"prompt":"...","provider":"veo","model":"veo-3.1-fast","aspectRatio":"9:16","resolution":"720p","duration":8,"mode":"custom","workflow":"create"}'

# 4. polling até status virar "done" (repetir a cada ~6s)
curl -s -b cookies.txt https://www.destinyai.com.br/api/videos/<requestId>
# quando status == "done", pegar o campo videoUrl e baixar o mp4 (a URL expira)
```

Isso é basicamente o esqueleto de uma classe `DestinyClient` (Python/Node) pra
usarmos como wrapper interno até (ou em vez de) termos uma API oficial deles.
Fluxo completo validado ponta a ponta: login → POST /api/videos → polling
GET /api/videos/:id → download do mp4 via `videoUrl`.

## 6. Observação de segurança

O `.txt` com credenciais em `documents/creds` está em texto puro na pasta do
projeto — se este repo for versionado/compartilhado, recomendo mover isso pra
um `.env` fora do controle de versão (e adicionar ao `.gitignore`) antes de
seguir com o desenvolvimento da integração.
