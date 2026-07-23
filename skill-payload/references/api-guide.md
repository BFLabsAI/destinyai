# Destiny API — Guia Completo de Uso

Documentação de referência completa da API não-oficial da Destiny
(`https://www.destinyai.com.br`), construída via engenharia reversa (ver
`reverse-engineering-plan.md` para o histórico da investigação — este
documento é a consolidação **pronta pra uso**, sem a narrativa).

Esta é a documentação que vai dentro da pasta `.destiny/` instalada pelo
script de setup, e é o que qualquer agente/integração deve seguir pra operar
a API corretamente.

---

## Índice

1. [Visão geral](#1-visão-geral)
2. [Autenticação](#2-autenticação)
3. [Endpoints — referência completa](#3-endpoints--referência-completa)
4. [Gerar vídeo (`workflow: "create"`)](#4-gerar-vídeo-workflow-create)
5. [Prompt simples vs. prompt avançado](#5-prompt-simples-vs-prompt-avançado)
6. [Imagens de referência (base64)](#6-imagens-de-referência-base64)
7. [Provider Veo — campos e limites](#7-provider-veo--campos-e-limites)
8. [Provider Grok — campos e limites](#8-provider-grok--campos-e-limites)
9. [Tabela de preços por combinação](#9-tabela-de-preços-por-combinação)
10. [Estender vídeo (`workflow: "extend"`)](#10-estender-vídeo-workflow-extend)
11. [Polling — lógica completa](#11-polling--lógica-completa)
12. [Download do vídeo final](#12-download-do-vídeo-final)
13. [Erros e códigos conhecidos](#13-erros-e-códigos-conhecidos)
14. [Bugs conhecidos da API](#14-bugs-conhecidos-da-api)
15. [Cliente de referência completo (Node.js)](#15-cliente-de-referência-completo-nodejs)
16. [Cliente de referência completo (Python)](#16-cliente-de-referência-completo-python)
17. [Cliente de referência completo (bash/curl)](#17-cliente-de-referência-completo-bashcurl)
18. [Pendências / não mapeado](#18-pendências--não-mapeado)

---

## 1. Visão geral

A Destiny (DestinyGen AI Studio) é um SaaS que revende geração de vídeo por
IA, atuando como camada de proxy/revenda em cima de um agregador chamado
**GeminiGen** (infra visível nos buckets `geminigen-prd-*`,
`edge-files.snapgen.ai`). Dois provedores de modelo:

- **Veo** (Google AI, via GeminiGen) — melhor qualidade, suporta imagem de
  referência de início **e** fim.
- **Grok** (xAI) — mais rápido, só uma imagem de referência, mais opções de
  aspect ratio.

Cobrança em **créditos** (1 crédito ≈ R$1,00 na tabela de compra padrão). O
preço de cada geração é resolvido no **backend** a partir da combinação
`provider` + `resolution` + `duration` — o client nunca envia um "preço".

Todas as rotas abaixo usam base `https://www.destinyai.com.br`.

---

## 2. Autenticação

**Não existe API key.** A autenticação é feita via **cookie de sessão
HttpOnly** (`destiny_session`), igual a um login normal de navegador.

### 2.1. Login

```
POST /api/auth/login
Content-Type: application/json

{
  "email": "seu@email.com",
  "password": "sua_senha",
  "fullName": "",
  "phone": "",
  "confirmPassword": ""
}
```

Os campos `fullName`, `phone`, `confirmPassword` são vestígios do mesmo
formulário servir cadastro — em login, mande sempre como string vazia.

**Resposta 200:**
```json
{
  "authenticated": true,
  "user": {
    "email": "seu@email.com",
    "fullName": "Nome Completo",
    "id": "usr_...",
    "isAdmin": false,
    "phone": "..."
  }
}
```

**Header que importa (não aparece pro JS do navegador, só via inspeção HTTP
direta — `curl -i`, proxy, etc., porque o cookie é `HttpOnly`):**
```
Set-Cookie: destiny_session=<token hex de 64 chars>; Max-Age=2592000; Path=/;
            Expires=<data>; HttpOnly; SameSite=Lax
```

- **Validade: 30 dias** (`Max-Age=2592000` segundos).
- **Sem flag `Secure`** no cookie (mesmo servindo em HTTPS) — falha de
  segurança do lado da Destiny, não nossa, mas bom saber.
- **Sem CSRF token.** Nenhuma chamada subsequente pede header extra além do
  cookie.
- Não existe nada relevante em `localStorage`/`sessionStorage` — é 100%
  cookie.

### 2.2. Usar a sessão

Toda chamada autenticada só precisa reenviar o cookie:

```
GET /api/account
Cookie: destiny_session=<token>
```

### 2.3. Reautenticação

- Se qualquer chamada retornar **401**, a sessão expirou/foi invalidada →
  refazer `POST /api/auth/login` com as credenciais salvas e repetir a
  chamada original.
- Também vale reautenticar proativamente se `expiresAt` (calculado no
  momento do login: `agora + 30 dias`) já passou, sem esperar o 401.

### 2.4. Onde fica salvo (nesta instalação)

```
~/.destiny/.env           # DESTINY_EMAIL=...  /  DESTINY_PASSWORD=...
~/.destiny/session.json   # {"cookie": "destiny_session=...", "expiresAt": "ISO-8601"}
```

`~/.destiny/.env` é escrito **uma vez** pelo instalador (a partir do que o
usuário digita) e nunca mais precisa ser preenchido de novo — é a fonte pra
qualquer relogin automático. `~/.destiny/session.json` é gerenciado pelo
próprio client (reescrito a cada login).

**Fluxo padrão de qualquer client (Node/Python/bash, ver §15–17):**
1. Ler `~/.destiny/session.json`. Se existir e `expiresAt` no futuro → usar
   o `cookie` direto, sem logar de novo.
2. Se não existir, estiver expirado, ou qualquer chamada voltar `401` → ler
   `~/.destiny/.env` (`DESTINY_EMAIL`/`DESTINY_PASSWORD`), chamar
   `POST /api/auth/login`, e regravar `session.json` com o novo cookie e
   `expiresAt = agora + 30 dias`.
3. Repetir a chamada original.

Isso é o que garante que, depois da instalação inicial, **nenhum agente
precisa pedir email/senha de novo** — a skill só olha pra esses dois
arquivos.

---

## 3. Endpoints — referência completa

| Método | Rota | Auth | Função |
|---|---|---|---|
| POST | `/api/auth/login` | não | Login, gera cookie de sessão |
| GET | `/api/account` | sim | Dados da conta + saldo de créditos |
| GET | `/api/billing/plans` | sim | Tabela de preços por geração, pacotes de créditos, pedidos |
| GET | `/api/history?filter_by=video&items_per_page=30&page=1` | sim | Histórico de gerações (⚠️ status não confiável, ver §14) |
| POST | `/api/videos` | sim | Dispara geração (`create`) ou extensão (`extend`) |
| GET | `/api/videos/:requestId` | sim | **Fonte da verdade** do status do job + URL do vídeo pronto |

### `GET /api/account`

```json
{
  "liveApiConfigured": true,
  "fullName": "bruno falcao",
  "email": "seu@email.com",
  "planId": "PP0001",
  "availableCredit": 18.5,
  "lockedCredit": 4,
  "destinyCreditBalance": 18.5,
  "benefits": []
}
```

- `availableCredit` / `destinyCreditBalance` parecem sempre iguais nos testes
  feitos — provavelmente o segundo é um alias/legado do primeiro.
- `lockedCredit` sobe quando há geração em andamento (reserva de crédito) e
  não necessariamente volta a 0 mesmo com o job concluído (ver §14).

### `GET /api/billing/plans`

```json
{
  "balance": 18.5,
  "generationPrices": [
    {"id": "grok-480p-6s",  "provider": "grok", "label": "Grok 480p 6s",  "priceCents": 60},
    {"id": "grok-480p-10s", "provider": "grok", "label": "Grok 480p 10s", "priceCents": 90},
    {"id": "grok-480p-15s", "provider": "grok", "label": "Grok 480p 15s", "priceCents": 120},
    {"id": "grok-720p-6s",  "provider": "grok", "label": "Grok 720p 6s",  "priceCents": 90},
    {"id": "grok-720p-10s", "provider": "grok", "label": "Grok 720p 10s", "priceCents": 120},
    {"id": "grok-720p-15s", "provider": "grok", "label": "Grok 720p 15s", "priceCents": 150},
    {"id": "veo-3",         "provider": "veo",  "label": "VEO 3",         "priceCents": 50}
  ],
  "mode": "amplopay",
  "orders": [
    {
      "id": "ord_...",
      "amountCents": 2000,
      "credits": 20,
      "createdAt": "2026-07-23T13:06:40.833Z",
      "paymentProvider": "amplopay",
      "planId": "topup-20",
      "status": "paid",
      "updatedAt": "2026-07-23T13:07:52.266Z",
      "userId": "usr_...",
      "checkoutUrl": "https://seguroamplopay.com/checkout/...",
      "externalId": "ord_...",
      "paidAt": "2026-07-23T13:07:52.266Z"
    }
  ],
  "plans": [
    {"id": "topup-20",  "name": "Essencial", "priceCents": 2000,  "baseCredits": 20,  "bonusCredits": 0,   "credits": 20,  "description": "Entrada direta para testar o fluxo e gerar os primeiros vídeos."},
    {"id": "topup-50",  "name": "Creator",   "priceCents": 5000,  "baseCredits": 50,  "bonusCredits": 10,  "credits": 60,  "description": "Mais margem para criar campanhas curtas com bônus premium."},
    {"id": "topup-100", "name": "Pro",       "priceCents": 10000, "baseCredits": 100, "bonusCredits": 30,  "credits": 130, "description": "Melhor equilíbrio entre preço e bônus para uso recorrente.", "featured": true},
    {"id": "topup-200", "name": "Scale",     "priceCents": 20000, "baseCredits": 200, "bonusCredits": 100, "credits": 300, "description": "Maior pacote para volume, produtos e operação comercial."}
  ]
}
```

- `generationPrices[].priceCents / 100` = créditos gastos naquela combinação
  (ex.: `priceCents: 120` → `usedCredit: 1.2`). Note que os `id` de Veo na
  tabela (`veo-3`) não distinguem resolução/duração — na prática todo `POST`
  Veo testado até agora custou `0.5` crédito independente de `720p`/`1080p`.
- `checkoutUrl` (dentro de `orders[]`) é o link de pagamento da **amplopay**
  (gateway usado pra comprar créditos) — não precisamos mexer nisso pra
  consumir a API, só documentando que existe.

### `GET /api/history`

```
GET /api/history?filter_by=video&items_per_page=30&page=1
```

```json
{
  "liveApiConfigured": true,
  "success": true,
  "total": 5,
  "result": [
    {
      "id": 67404060,
      "uuid": "98a0f0fe-86a3-11f1-98da-6e33524f0b04",
      "model": "grok-video",
      "prompt": "...",
      "type": "video",
      "usedCredit": 1.2,
      "status": "running",
      "progress": 100,
      "statusDesc": "",
      "createdAt": "2026-07-23T14:34:22",
      "updatedAt": "2026-07-23T14:35:36",
      "thumbnailUrl": "https://assets.geminigen.ai/.../thumbnails/.../..._1_600px.jpg",
      "lastFrameUrl": "https://assets.geminigen.ai/.../last_frames/..._last_frame.jpg"
    }
  ]
}
```

⚠️ **`status` e `progress` deste endpoint não são confiáveis** — ver §14.
Use `uuid` daqui só como **índice** pra depois chamar
`GET /api/videos/:uuid` e pegar o status real.

---

## 4. Gerar vídeo (`workflow: "create"`)

```
POST /api/videos
Content-Type: application/json
Cookie: destiny_session=...
```

**Corpo (todos os campos possíveis, nem todos obrigatórios):**

```json
{
  "prompt": "string, obrigatório, mínimo 8 caracteres",
  "provider": "veo | grok",
  "model": "ver §7/§8",
  "imageDataUrl": "data:image/jpeg;base64,... (opcional)",
  "lastImageDataUrl": "data:image/jpeg;base64,... (opcional, só Veo)",
  "aspectRatio": "ver §7/§8",
  "resolution": "ver §7/§8",
  "duration": 4 ,
  "mode": "custom",
  "workflow": "create"
}
```

**Validação client-side observada no bundle** (o backend provavelmente
replica isso, então vale checar antes de mandar):
- `prompt.trim().length >= 8` — senão erro `"Write a prompt with at least 8
  characters."` / `"Escreva um prompt com pelo menos 8 caracteres."`

**Resposta imediata — `202 Accepted`:**
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

- `requestId` = identificador do job. **É o mesmo valor usado como `uuid` no
  histórico e como parâmetro em `GET /api/videos/:requestId`.**
- `balance` já vem com o crédito debitado (a cobrança acontece na criação do
  job, não na conclusão).
- Isso não é o vídeo pronto — é só a confirmação de que o job entrou na fila.
  Sempre siga com polling (§11).

---

## 5. Prompt simples vs. prompt avançado

**Isso não é um campo diferente na API — é só um comportamento da UI.**

- **Modo Básico**: o texto que o usuário digita vira o `prompt` diretamente.
- **Modo Avançado**: a UI tem 7 campos separados (Main subject, Action,
  Setting/environment, Lighting/time of day, Visual style, Camera shot,
  Additional details) e **concatena tudo num template de texto único** antes
  de mandar — o backend recebe só um `prompt` normal, sem saber que veio do
  modo avançado.

**Template exato usado pela UI:**
```
Main subject: <texto> Action: <texto> Setting / environment: <texto> Lighting / time of day: <texto> Visual style: <texto> Camera shot: <texto> Additional details: <texto>
```

Exemplo real:
```
Main subject: um homem andando e falando trocando de cenario num estudio fotografico. Action: andando dentro de um estudio e trocando o cenario. Setting / environment: estudio fotografico em preto e branco. Lighting / time of day: preto e branco cinematografico. Visual style: preto e branco. Camera shot: Close-up. Additional details: um homem tirando uma foto, depois olhando para camera e dizendo: você é seu melhor amigo! Faça mais por você!! com falas pausadas, aspecto dramatico, pausa dramatica entra as falas.
```

**Recomendação pra integração própria:** não precisa reproduzir os 7 campos
separados — é só um artifício de UX da Destiny pra guiar o usuário leigo a
escrever um prompt melhor. Nossa integração pode:
- (a) mandar o `prompt` final já bem escrito direto, ou
- (b) reproduzir o mesmo template se quisermos oferecer a mesma UX
  "estruturada" pro usuário final da nossa aplicação.

**Campo `Camera shot`** (visto na UI) tem valores predefinidos tipo
`Close-up` — outros valores possíveis (Wide shot, Medium shot, etc.) ainda
não foram todos capturados; qualquer texto livre também funciona já que vira
só uma frase dentro do `prompt`.

---

## 6. Imagens de referência (base64)

**Não existe upload multipart / endpoint de upload separado.** As imagens
vão **embutidas inteiras** dentro do corpo JSON do `POST /api/videos`, como
[data URI](https://developer.mozilla.org/en-US/docs/Web/URI/Reference/Schemes/data)
em base64.

### 6.1. Formato

```
data:<mime-type>;base64,<conteúdo em base64>
```

Tipos aceitos pela UI (`accept` do input de arquivo): `image/png`,
`image/jpeg`, `image/webp`.

### 6.2. Como converter um arquivo local

**bash:**
```bash
MIME="image/jpeg"   # ajustar conforme o arquivo (png/jpeg/webp)
DATA_URL="data:${MIME};base64,$(base64 -i foto.jpg | tr -d '\n')"
```

**Node.js:**
```js
import { readFileSync } from "node:fs";
function fileToDataUrl(path, mime = "image/jpeg") {
  const b64 = readFileSync(path).toString("base64");
  return `data:${mime};base64,${b64}`;
}
```

**Python:**
```python
import base64, mimetypes

def file_to_data_url(path):
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{b64}"
```

### 6.3. Campos

| Campo | Provider | Obrigatório | Descrição |
|---|---|---|---|
| `imageDataUrl` | Veo e Grok | não | Imagem de referência inicial. No Grok, referenciar no `prompt` com `@image` (ver §8). |
| `lastImageDataUrl` | **só Veo** | não | Imagem de referência final (último frame desejado). Só faz sentido combinado com `imageDataUrl`. |

- Payload fica grande: uma imagem de referência de ~200KB vira ~270KB em
  base64; com as duas imagens do Veo (início+fim), um payload real chegou a
  **~420KB**. Não é um problema pro backend (aceitou de boa), mas vale
  considerar timeout de rede em conexões lentas.
- Quando há imagem de referência, o `thumbnailUrl` que volta no polling tem
  sufixo `/ref/first-reference_200px.jpg` (em vez do padrão
  `<uuid>_0_600px.jpg` sem referência).

---

## 7. Provider Veo — campos e limites

| Campo | Valores aceitos | Testado? |
|---|---|---|
| `model` | `veo-3.1-fast`, `veo-3.1-lite`, `veo-2` | só `veo-3.1-fast` testado em request real |
| `aspectRatio` | `16:9` (Paisagem), `9:16` (Retrato) | ✅ ambos testados |
| `resolution` | `720p`, `1080p` | ✅ ambos testados |
| `duration` | `4`, `6`, `8` (segundos) | ✅ todos testados |
| `imageDataUrl` | data URI base64 | ✅ testado |
| `lastImageDataUrl` | data URI base64 | ✅ testado |
| `mode` | não se aplica ao Veo — mandar `"custom"` ou omitir | — |

**Custo confirmado invariante:** todas as combinações de `resolution`
(`720p`/`1080p`) e `duration` (`4`/`6`/`8`) testadas custaram exatamente
`0.5` crédito — o preço do Veo parece ser **fixo por vídeo**, não varia por
essas dimensões (diferente do Grok, ver §9).

**Regra de negócio observada no bundle:** ao trocar de resolução, se
`resolution === "1080p"` a UI força `duration` pra um valor válido; e a lista
de durações válidas do Veo é fixa em `[4, 6, 8]` — mandar outro valor
provavelmente é rejeitado ou normalizado pelo backend (não confirmado, ver §18).

---

## 8. Provider Grok — campos e limites

| Campo | Valores aceitos | Testado? |
|---|---|---|
| `model` | `grok-video` (único valor) | testado |
| `aspectRatio` | `16:9` (Paisagem), `9:16` (Retrato), `1:1` (Quadrado), `3:4` (Vertical), `4:3` (Horizontal) | só `9:16` testado |
| `resolution` | `480p`, `720p` | só `720p` testado |
| `duration` | `6`, `10`, `15` (segundos) | só `10` testado |
| `imageDataUrl` | data URI base64 (única imagem — **não existe `lastImageDataUrl` pro Grok**) | testado |
| `mode` | `normal`, `extremely crazy`, `extremely spicy`/`crazy`, `custom` | só `"custom"` testado |

### 8.1. Convenção `@image`

Quando há `imageDataUrl`, o prompt deve referenciar a imagem literalmente com
`@image` no texto — é uma instrução textual pro modelo entender que deve
usar aquela imagem como base, **não** é um placeholder substituído pelo
frontend (o literal `@image` mesmo vai dentro do `prompt` enviado ao
backend). Exemplo real:

```json
{
  "prompt": "gere um video da pessoa na @image que esta em um estudio fazendo fotografias e dizendo uma frase motivacional para a camera com o intuito de: você também pode!!! em pt-br com tom dramatico e falas lentas e pausadas",
  "imageDataUrl": "data:image/jpeg;base64,..."
}
```

### 8.2. Regra de negócio (bundle)

Ao trocar `resolution` pra `"1080p"` no contexto Grok a UI força de volta pra
`"720p"` (Grok não suporta 1080p); durações válidas fixas em `[6, 10, 15]`.

---

## 9. Tabela de preços por combinação

Direto de `GET /api/billing/plans` → `generationPrices` (créditos =
`priceCents / 100`):

| Combinação | `priceCents` | Créditos |
|---|---|---|
| Grok 480p, 6s | 60 | 0.6 |
| Grok 480p, 10s | 90 | 0.9 |
| Grok 480p, 15s | 120 | 1.2 |
| Grok 720p, 6s | 90 | 0.9 |
| Grok 720p, 10s | 120 | 1.2 |
| Grok 720p, 15s | 150 | 1.5 |
| Veo 3 (qualquer resolução/duração testada) | 50 | 0.5 |

Confirmado empiricamente: `usedCredit` retornado no `POST /api/videos` bate
exatamente com essa tabela (ex.: Grok 720p 10s → `usedCredit: 1.2`).

---

## 10. Estender vídeo (`workflow: "extend"`)

```json
POST /api/videos
{
  "prompt": "o que deve acontecer na continuação, mínimo 8 caracteres",
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

| Campo | Descrição |
|---|---|
| `refHistory` | **Campo-chave.** `uuid`/`requestId` (string) de um vídeo **já concluído** (`status: "done"` via `GET /api/videos/:id`). Não é upload de frame nem objeto — só a string do id. |
| Demais campos | Mesmo formato do `create`. `imageDataUrl`/`lastImageDataUrl` **não se aplicam** aqui (o vídeo de origem já fornece a referência visual). |

**Comportamento:**
- A extensão usa o **último frame** do vídeo de origem como ponto de partida
  visual — confirmado pelo `thumbnailUrl` intermediário durante o polling,
  que aponta pro frame final do vídeo original:
  `.../ref/<uuid-original>_last_frame_200px.jpg`.
- Resposta imediata e de conclusão seguem exatamente o mesmo formato do
  `create` (§4 e §11) — `requestId`, depois `status`/`videoUrl` no polling.
- Custo: mesmo preço da combinação `resolution`+`duration` normal (não há
  cobrança extra por "ser extensão").
- No código-fonte da UI, quando `workflow === "extend"` o frontend
  **pré-preenche automaticamente** `model`, `resolution` e `duration` a
  partir do vídeo de origem (usuário só edita o `prompt` na tela) — mas isso
  é só UX; nossa integração pode mandar valores diferentes manualmente, é
  só um JSON comum.

### ⚠️ Bug conhecido: a tela "Estender vídeo" não funciona pela UI

O seletor de "vídeo base" na interface mostra **"nenhum vídeo disponível"**
mesmo com vídeos prontos na conta. Root cause: ver §14 — o seletor
provavelmente filtra por `status` de `/api/history`, que nunca chega a
`"done"`. **Usar direto via API contorna o bug** — validado end-to-end
(POST → polling → vídeo pronto).

---

## 11. Polling — lógica completa

`POST /api/videos` só enfileira o job. O vídeo final só existe depois de
consultar repetidamente o status.

### 12.1. Qual endpoint usar

**Sempre `GET /api/videos/:requestId`** (nunca `/api/history`, ver §14).

```
GET /api/videos/aa1a13fe-86a0-11f1-817a-ba4f920ea6f2
```

### 12.2. Estados observados

| `status` | Significado |
|---|---|
| `running` | Em processamento. `progress` sobe até 100 mas **o job ainda não terminou** mesmo com `progress: 100` — só o `status` vira `"done"` é que confirma conclusão. |
| `done` | Concluído. Response inclui `videoUrl` e `thumbnailUrl` finais. |
| (não observado) | O backend provavelmente tem um estado de falha (`failed`/`expired` — esses literais aparecem no código do frontend, ver §19), mas não conseguimos reproduzir um job falhando durante o processamento pra confirmar o formato exato. |

**Importante:** `progress: 100` **não é sinônimo de pronto** — em vários
testes o job ficou em `status: "running", progress: 100` por dezenas de
segundos antes de finalmente virar `"done"`. Só pare o polling quando
`status === "done"` (ou um eventual `"failed"`/`"expired"`).

### 12.3. Intervalo recomendado

O frontend oficial faz polling a cada **~6 segundos**. Tempos de conclusão
observados nos testes: de ~1min20s a ~2min30s do `POST` até `status: "done"`,
variando por provider/carga.

**Estratégia recomendada pra integração própria:**
```
intervalo = 6s (igual ao frontend oficial — não há indicação de rate limit,
                 mas não há necessidade de ir mais rápido que isso)
timeout total = 5 minutos (bem acima do maior tempo observado, ~2min30s)
```

Pseudocódigo:
```
job = POST /api/videos {...}
requestId = job.requestId
deadline = now() + 5 minutos

loop:
  if now() > deadline: erro "timeout aguardando geração"
  status = GET /api/videos/{requestId}
  if status.status == "done": return status.videoUrl
  if status.status in ("failed", "expired"): erro status.errorMessage
  sleep(6s)
```

### 12.4. Exemplo de resposta intermediária

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

### 12.5. Exemplo de resposta final

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

---

## 12. Download do vídeo final

`videoUrl` é uma **URL assinada estilo S3/presigned** (bucket
`geminigen-prd-upload-bucket`, servido via `edge-files.snapgen.ai`), com
`AWSAccessKeyId`, `Signature` e `Expires` (timestamp Unix) na query string.

**Isso significa que expira.** Nos testes, o `Expires` observado foi
`now + ~30 dias` (aprox., em timestamp Unix), mas **não trate isso como
garantido** — baixe o arquivo assim que `status` virar `"done"`, e persista
o `.mp4` você mesmo (storage próprio) em vez de guardar essa URL como link
permanente.

```bash
curl -s -o video.mp4 "https://edge-files.snapgen.ai/.../*.mp4?...&Expires=..."
```

Não precisa de cookie de sessão pra baixar — é uma URL pré-assinada
independente, funciona sem autenticação Destiny.

### 12.1. Baixar todos os vídeos prontos da conta (batch)

Não é preciso ter acabado de gerar um vídeo pra baixar — dá pra consultar
**todos os vídeos já existentes na conta** e baixar os que estiverem prontos.
Fluxo testado e validado ponta a ponta (12 vídeos, ~139MB, baixados com
sucesso num teste real):

1. `GET /api/history?filter_by=video&items_per_page=30&page=1` → lista de
   `uuid`s (ignore o campo `status` daqui, ver §14).
2. Para cada `uuid`, `GET /api/videos/:uuid` → status real.
3. Se `status === "done"`, baixar `videoUrl` pro disco (ex.:
   `~/.destiny/downloads/<uuid>.mp4` ou qualquer pasta local).
4. Pular `uuid`s cujo arquivo já existe localmente (evita rebaixar toda vez).

```bash
#!/usr/bin/env bash
set -euo pipefail
BASE="https://www.destinyai.com.br"
COOKIES="cookies.txt"
DEST="${1:-./video-downloads}"
mkdir -p "$DEST"

HISTORY=$(curl -s -b "$COOKIES" "$BASE/api/history?filter_by=video&items_per_page=30&page=1")
UUIDS=$(echo "$HISTORY" | jq -r '.result[].uuid')

for uuid in $UUIDS; do
  DEST_FILE="$DEST/$uuid.mp4"
  if [ -f "$DEST_FILE" ]; then
    echo "já existe, pulando: $uuid"
    continue
  fi
  INFO=$(curl -s -b "$COOKIES" "$BASE/api/videos/$uuid")
  STATUS=$(echo "$INFO" | jq -r '.status')
  if [ "$STATUS" = "done" ]; then
    URL=$(echo "$INFO" | jq -r '.videoUrl')
    echo "baixando $uuid ..."
    curl -s -o "$DEST_FILE" "$URL"
  else
    echo "ainda não pronto ($STATUS), pulando: $uuid"
  fi
done
```

Uso: `./download-all.sh ./video-downloads`

**Paginação:** `/api/history` aceita `page` e `items_per_page` — se a conta
tiver mais de 30 vídeos, iterar `page=1,2,3...` até a página vir vazia
(`result: []`) ou `total` (campo no JSON) ser menor que
`page * items_per_page`.

Isso é a base do comando de download que a skill instalada deve expor (ver
`beta-onboarding-installer-plan.md`) — tanto pro caso "baixe automaticamente
assim que a geração que acabei de disparar terminar" (§11, `waitForVideo` +
`downloadVideo`) quanto pro caso "quero rodar uma consulta e baixar tudo que
já tiver pronto" (este aqui).

---

## 13. Erros e códigos conhecidos

**Formato genérico de erro:**
```json
{
  "error": "mensagem legível",
  "errorCode": "CODE",
  "requestId": "...",
  "retryable": false
}
```

| HTTP status | `errorCode` | Quando acontece | Ação recomendada |
|---|---|---|---|
| 402 | `NOT_ENOUGH_CREDIT` | Saldo insuficiente pra combinação escolhida | Não insistir automaticamente (`retryable: false`); avisar o usuário/pausar a fila até ter saldo |
| 401 | — | Cookie de sessão ausente/expirado/inválido | Refazer login e repetir a chamada original |
| — | `"Write a prompt with at least 8 characters."` (validação client-side) | `prompt` curto demais | Validar tamanho antes de enviar |

Mensagem de erro real observada (durante um período de instabilidade/manutenção do provider):
```json
{
  "error": "You do not have enough credit. Please buy more credit.",
  "errorCode": "NOT_ENOUGH_CREDIT",
  "requestId": "696d5aa1-eadd-49db-a6ed-080b2bba57ef",
  "retryable": false
}
```
Nesse caso específico não era falta de saldo real (a conta tinha crédito) —
era instabilidade temporária do provider durante manutenção. Ainda assim,
tratar sempre como "não insistir automaticamente" é a postura segura.

---

## 14. Bugs conhecidos da API

### 15.1. `GET /api/history` nunca reflete `status: "done"`

Comparando o mesmo vídeo nos dois endpoints:

- `GET /api/videos/<uuid>` → `{"status":"done","progress":100,"videoUrl":"...mp4"}` (correto).
- `GET /api/history` → o mesmo `uuid` continua `{"status":"running","progress":100}` **indefinidamente**, mesmo consultado dias depois.

**Impacto prático:** qualquer lógica (nossa ou da própria Destiny) que decida
"vídeo pronto" baseada em `/api/history` vai falhar. É a causa provável do
bug de UI abaixo.

**Regra pra nossa integração:** nunca usar `status`/`progress` de
`/api/history` como fonte de verdade — usar só como lista de `uuid`s
existentes, e sempre confirmar o status real com
`GET /api/videos/:uuid`.

### 15.2. Tela "Estender vídeo" não lista nenhum vídeo disponível

Consequência direta do bug acima — o seletor de vídeo-base da UI mostra
"nenhum vídeo disponível" mesmo com vídeos prontos, porque provavelmente
filtra por `status === "done"` vindo de `/api/history`. Contornado usando a
API direto (§10) com o `uuid` do vídeo (pego de `/api/history`, mesmo que o
`status` de lá esteja errado — o `uuid` em si é confiável).

### 15.3. `lockedCredit` pode não zerar após conclusão

Observado `lockedCredit: 4` em `/api/account` mesmo com jobs já concluídos.
Não afeta o `availableCredit` usado pra decidir se dá pra gerar ou não
(validado empiricamente — geração funcionou normalmente com esse valor
"travado"), mas é outro sinal de que o backend não sincroniza 100% o estado
entre `/api/account` e o estado real dos jobs.

**Recomendação:** ambos os bugs valem ser reportados formalmente aos devs da
Destiny — não são bloqueadores pra nossa integração (temos workaround), mas
travam a experiência de quem usa só a UI oficial.

---

## 15. Cliente de referência completo (Node.js)

Sem dependências externas (Node 22.5+): usa `fetch` nativo e o módulo
`node:sqlite` nativo pra manter `~/.destiny/history.db` (ver
`beta-onboarding-installer-plan.md` §4 pro schema completo). Lê e gerencia
sozinho `~/.destiny/.env` e `~/.destiny/session.json` — **nenhum agente
precisa passar email/senha na mão** depois que o instalador rodou uma vez.
(Em Node 18–21, sem `node:sqlite`, trocar por `better-sqlite3` — mesma API
usada abaixo, só muda o import.)

```js
import { homedir } from "node:os";
import { join } from "node:path";
import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";

const BASE = "https://www.destinyai.com.br";
const DESTINY_DIR = join(homedir(), ".destiny");
const ENV_PATH = join(DESTINY_DIR, ".env");
const SESSION_PATH = join(DESTINY_DIR, "session.json");
const DB_PATH = join(DESTINY_DIR, "history.db");
const DOWNLOADS_DIR = join(DESTINY_DIR, "downloads"); // pasta única/padrão de download

function openDb() {
  mkdirSync(DESTINY_DIR, { recursive: true });
  const db = new DatabaseSync(DB_PATH);
  db.exec(`
    CREATE TABLE IF NOT EXISTS generations (
      id           TEXT PRIMARY KEY,
      created_at   TEXT NOT NULL,
      provider     TEXT NOT NULL,
      prompt       TEXT NOT NULL,
      workflow     TEXT NOT NULL,
      request_json TEXT NOT NULL,
      status       TEXT NOT NULL,
      video_url    TEXT,
      local_path   TEXT,
      updated_at   TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_generations_prompt ON generations(prompt);
    CREATE INDEX IF NOT EXISTS idx_generations_status ON generations(status);
  `);
  return db;
}

function readEnvFile() {
  if (!existsSync(ENV_PATH)) {
    throw new Error(`Credenciais não encontradas em ${ENV_PATH}. Rode o instalador primeiro.`);
  }
  const out = {};
  for (const line of readFileSync(ENV_PATH, "utf8").split("\n")) {
    const m = line.match(/^([A-Z_]+)=(.*)$/);
    if (m) out[m[1]] = m[2];
  }
  if (!out.DESTINY_EMAIL || !out.DESTINY_PASSWORD) {
    throw new Error(`${ENV_PATH} precisa ter DESTINY_EMAIL e DESTINY_PASSWORD`);
  }
  return out;
}

function readSession() {
  if (!existsSync(SESSION_PATH)) return null;
  const s = JSON.parse(readFileSync(SESSION_PATH, "utf8"));
  if (new Date(s.expiresAt).getTime() <= Date.now()) return null; // expirado
  return s;
}

function writeSession(cookie) {
  mkdirSync(DESTINY_DIR, { recursive: true });
  const expiresAt = new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString();
  writeFileSync(SESSION_PATH, JSON.stringify({ cookie, expiresAt }, null, 2), { mode: 0o600 });
  return { cookie, expiresAt };
}

class DestinyClient {
  constructor() {
    this.cookie = null;
    this.db = openDb();
  }

  // Carrega sessão salva ou faz login com as credenciais do ~/.destiny/.env
  async ensureSession() {
    const cached = readSession();
    if (cached) {
      this.cookie = cached.cookie;
      return;
    }
    await this.login();
  }

  async login() {
    const { DESTINY_EMAIL, DESTINY_PASSWORD } = readEnvFile();
    const res = await fetch(`${BASE}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: DESTINY_EMAIL,
        password: DESTINY_PASSWORD,
        fullName: "",
        phone: "",
        confirmPassword: "",
      }),
    });
    if (!res.ok) throw new Error(`Login falhou: ${res.status}`);
    const setCookie = res.headers.get("set-cookie");
    this.cookie = setCookie.split(";")[0]; // "destiny_session=..."
    writeSession(this.cookie);
    return res.json();
  }

  async request(path, opts = {}, retried = false) {
    if (!this.cookie) await this.ensureSession();
    const res = await fetch(`${BASE}${path}`, {
      ...opts,
      headers: { ...(opts.headers || {}), Cookie: this.cookie, "Content-Type": "application/json" },
    });
    if (res.status === 401 && !retried) {
      await this.login(); // sessão expirou/inválida -> relogar com ~/.destiny/.env
      return this.request(path, opts, true);
    }
    const body = await res.json();
    if (!res.ok) {
      const err = new Error(body.error || `HTTP ${res.status}`);
      err.status = res.status;
      err.errorCode = body.errorCode;
      err.retryable = body.retryable;
      throw err;
    }
    return body;
  }

  account() {
    return this.request("/api/account");
  }

  billingPlans() {
    return this.request("/api/billing/plans");
  }

  history(page = 1, itemsPerPage = 30) {
    return this.request(`/api/history?filter_by=video&items_per_page=${itemsPerPage}&page=${page}`);
  }

  // workflow: "create" | "extend"
  async createVideo({
    prompt, provider, model, aspectRatio, resolution, duration,
    mode = "custom", workflow = "create",
    imageDataUrl, lastImageDataUrl, refHistory,
  }) {
    if (prompt.trim().length < 8) throw new Error("prompt precisa ter pelo menos 8 caracteres");
    const payload = {
      prompt, provider, model, aspectRatio, resolution, duration, mode, workflow,
      imageDataUrl, lastImageDataUrl, refHistory,
    };
    const res = await this.request("/api/videos", { method: "POST", body: JSON.stringify(payload) });

    // Grava a linha assim que o job é aceito (202) — antes mesmo de saber se vai
    // terminar bem. É isso que garante que o requestId nunca se perde, mesmo que
    // o processo caia no meio do polling.
    const now = new Date().toISOString();
    this.db.prepare(`
      INSERT INTO generations (id, created_at, provider, prompt, workflow, request_json, status, video_url, local_path, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)
    `).run(
      res.requestId, now, provider, prompt, workflow,
      // Não salva as imagens base64 inteiras no banco — só um resumo.
      JSON.stringify({ ...payload, imageDataUrl: imageDataUrl ? "[omitido]" : undefined, lastImageDataUrl: lastImageDataUrl ? "[omitido]" : undefined }),
      res.status, now
    );
    return res;
  }

  extendVideo({ prompt, refHistory, provider, model, aspectRatio, resolution, duration, mode = "custom" }) {
    return this.createVideo({ prompt, provider, model, aspectRatio, resolution, duration, mode, workflow: "extend", refHistory });
  }

  async getVideoStatus(requestId) {
    const status = await this.request(`/api/videos/${requestId}`);
    // Atualiza a linha a cada consulta — assim status/video_url no banco
    // sempre refletem a última vez que checamos (não confiar em /api/history).
    this.db.prepare(`
      UPDATE generations SET status = ?, video_url = COALESCE(?, video_url), updated_at = ? WHERE id = ?
    `).run(status.status, status.videoUrl ?? null, new Date().toISOString(), requestId);
    return status;
  }

  async waitForVideo(requestId, { intervalMs = 6000, timeoutMs = 5 * 60 * 1000 } = {}) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const status = await this.getVideoStatus(requestId);
      if (status.status === "done") return status;
      if (status.status === "failed" || status.status === "expired") {
        throw new Error(`Geração falhou: ${status.errorMessage || status.status}`);
      }
      await new Promise((r) => setTimeout(r, intervalMs));
    }
    throw new Error(`Timeout aguardando geração de ${requestId}`);
  }

  async downloadVideo(id, videoUrl, destPath) {
    const res = await fetch(videoUrl); // não precisa de cookie, URL já é assinada
    const buf = Buffer.from(await res.arrayBuffer());
    writeFileSync(destPath, buf);
    this.db.prepare(`UPDATE generations SET local_path = ?, updated_at = ? WHERE id = ?`)
      .run(destPath, new Date().toISOString(), id);
  }

  // Busca por id direto no banco local — sem precisar bater na Destiny de novo
  // se já tivermos local_path/video_url salvos.
  getGeneration(id) {
    return this.db.prepare(`SELECT * FROM generations WHERE id = ?`).get(id);
  }

  // Busca por texto do prompt (útil pra "cadê aquele vídeo do gato que eu gerei ontem").
  searchGenerations(text) {
    return this.db.prepare(`SELECT * FROM generations WHERE prompt LIKE ? ORDER BY created_at DESC`)
      .all(`%${text}%`);
  }

  // Baixa UM vídeo específico pelo id — usa o histórico local se já tiver
  // video_url; se não tiver (ou quisermos garantir que está fresco), consulta
  // a Destiny de novo antes de baixar. Sem destDir, cai sempre na mesma pasta
  // padrão (~/.destiny/downloads) — é isso que permite nunca baixar 2x.
  async downloadById(id, destDir = DOWNLOADS_DIR) {
    mkdirSync(destDir, { recursive: true });
    const destPath = join(destDir, `${id}.mp4`);
    if (existsSync(destPath)) return destPath; // já baixado
    const status = await this.getVideoStatus(id); // sempre revalida — videoUrl expira
    if (status.status !== "done" || !status.videoUrl) {
      throw new Error(`Vídeo ${id} ainda não está pronto (status: ${status.status})`);
    }
    await this.downloadVideo(id, status.videoUrl, destPath);
    return destPath;
  }

  // Lista todo o histórico e resolve o status REAL de cada vídeo
  // (nunca confia no status de /api/history, ver §14).
  async listAllVideos({ itemsPerPage = 30 } = {}) {
    const all = [];
    for (let page = 1; ; page++) {
      const res = await this.history(page, itemsPerPage);
      if (!res.result?.length) break;
      all.push(...res.result);
      if (all.length >= res.total) break;
    }
    const withRealStatus = await Promise.all(
      all.map((v) => this.getVideoStatus(v.uuid).catch(() => ({ id: v.uuid, status: "unknown" })))
    );
    return withRealStatus;
  }

  // Baixa todos os vídeos com status "done" que ainda não existem em destDir
  // (padrão: ~/.destiny/downloads, a mesma pasta usada por downloadById).
  async downloadAllReady(destDir = DOWNLOADS_DIR) {
    mkdirSync(destDir, { recursive: true });
    const videos = await this.listAllVideos();
    const downloaded = [];
    for (const v of videos) {
      if (v.status !== "done" || !v.videoUrl) continue;
      const destPath = join(destDir, `${v.id}.mp4`);
      if (existsSync(destPath)) continue; // já baixado
      await this.downloadVideo(v.id, v.videoUrl, destPath);
      downloaded.push(destPath);
    }
    return downloaded;
  }
}

// --- uso: gerar e baixar automaticamente assim que terminar ---
// Nenhuma credencial precisa ser passada aqui — o client lê ~/.destiny/.env
// e ~/.destiny/session.json sozinho. createVideo() já grava no history.db.
const client = new DestinyClient();

const job = await client.createVideo({
  prompt: "um gato laranja andando devagar em um jardim ensolarado",
  provider: "veo",
  model: "veo-3.1-fast",
  aspectRatio: "9:16",
  resolution: "720p",
  duration: 8,
});

const finished = await client.waitForVideo(job.requestId);
// Sem 3º argumento, cai direto em ~/.destiny/downloads/<requestId>.mp4
await client.downloadById(job.requestId);
console.log("Pronto, baixado em ~/.destiny/downloads/");

// --- uso: baixar UM vídeo específico pelo id, em outra sessão/dia qualquer ---
// (não baixa de novo se já existir em ~/.destiny/downloads)
await client.downloadById("aa1a13fe-86a0-11f1-817a-ba4f920ea6f2");

// --- uso: achar um vídeo pelo que lembro do prompt ---
console.log(client.searchGenerations("gato"));

// --- uso: baixar tudo que já estiver pronto na conta (sem gerar nada novo) ---
const baixados = await client.downloadAllReady(); // também usa ~/.destiny/downloads
console.log(`${baixados.length} vídeo(s) baixado(s):`, baixados);
```

---

## 16. Cliente de referência completo (Python)

```python
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

BASE = "https://www.destinyai.com.br"
DESTINY_DIR = Path.home() / ".destiny"
ENV_PATH = DESTINY_DIR / ".env"
SESSION_PATH = DESTINY_DIR / "session.json"
DB_PATH = DESTINY_DIR / "history.db"


def _open_db():
    DESTINY_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.execute("""
        CREATE TABLE IF NOT EXISTS generations (
            id           TEXT PRIMARY KEY,
            created_at   TEXT NOT NULL,
            provider     TEXT NOT NULL,
            prompt       TEXT NOT NULL,
            workflow     TEXT NOT NULL,
            request_json TEXT NOT NULL,
            status       TEXT NOT NULL,
            video_url    TEXT,
            local_path   TEXT,
            updated_at   TEXT NOT NULL
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_generations_prompt ON generations(prompt)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_generations_status ON generations(status)")
    db.row_factory = sqlite3.Row
    return db


def _read_env_file():
    if not ENV_PATH.exists():
        raise RuntimeError(f"Credenciais não encontradas em {ENV_PATH}. Rode o instalador primeiro.")
    env = {}
    for line in ENV_PATH.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    if "DESTINY_EMAIL" not in env or "DESTINY_PASSWORD" not in env:
        raise RuntimeError(f"{ENV_PATH} precisa ter DESTINY_EMAIL e DESTINY_PASSWORD")
    return env["DESTINY_EMAIL"], env["DESTINY_PASSWORD"]


def _read_session():
    if not SESSION_PATH.exists():
        return None
    data = json.loads(SESSION_PATH.read_text())
    expires_at = datetime.fromisoformat(data["expiresAt"])
    if expires_at <= datetime.now(timezone.utc):
        return None  # expirado
    return data["cookie"]


def _write_session(cookie):
    DESTINY_DIR.mkdir(parents=True, exist_ok=True)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    SESSION_PATH.write_text(json.dumps({"cookie": cookie, "expiresAt": expires_at}, indent=2))
    os.chmod(SESSION_PATH, 0o600)


class DestinyClient:
    # Nenhuma credencial precisa ser passada — lê ~/.destiny/.env e
    # ~/.destiny/session.json sozinho.
    def __init__(self):
        self.session = requests.Session()
        self.db = _open_db()
        cookie = _read_session()
        if cookie:
            self.session.headers["Cookie"] = cookie
            self._logged_in = True
        else:
            self._logged_in = False

    def login(self):
        email, password = _read_env_file()
        r = self.session.post(f"{BASE}/api/auth/login", json={
            "email": email, "password": password,
            "fullName": "", "phone": "", "confirmPassword": "",
        })
        r.raise_for_status()
        cookie = r.headers["set-cookie"].split(";")[0]
        self.session.headers["Cookie"] = cookie
        _write_session(cookie)
        self._logged_in = True
        return r.json()

    def _request(self, method, path, retried=False, **kwargs):
        if not self._logged_in:
            self.login()
        r = self.session.request(method, f"{BASE}{path}", **kwargs)
        if r.status_code == 401 and not retried:
            self.login()  # sessão expirou/inválida -> relogar com ~/.destiny/.env
            return self._request(method, path, retried=True, **kwargs)
        body = r.json()
        if not r.ok:
            raise RuntimeError(f"{body.get('errorCode')}: {body.get('error')} (retryable={body.get('retryable')})")
        return body

    def account(self):
        return self._request("GET", "/api/account")

    def billing_plans(self):
        return self._request("GET", "/api/billing/plans")

    def history(self, page=1, items_per_page=30):
        return self._request("GET", f"/api/history?filter_by=video&items_per_page={items_per_page}&page={page}")

    def create_video(self, prompt, provider, model, aspect_ratio, resolution, duration,
                      mode="custom", workflow="create",
                      image_data_url=None, last_image_data_url=None, ref_history=None):
        assert len(prompt.strip()) >= 8, "prompt precisa ter pelo menos 8 caracteres"
        payload = {
            "prompt": prompt, "provider": provider, "model": model,
            "aspectRatio": aspect_ratio, "resolution": resolution, "duration": duration,
            "mode": mode, "workflow": workflow,
        }
        if image_data_url:
            payload["imageDataUrl"] = image_data_url
        if last_image_data_url:
            payload["lastImageDataUrl"] = last_image_data_url
        if ref_history:
            payload["refHistory"] = ref_history
        res = self._request("POST", "/api/videos", json=payload)

        # Grava a linha assim que o job é aceito (202) — antes de saber se vai
        # terminar bem, pra nunca perder o requestId mesmo se o processo cair
        # no meio do polling.
        now = datetime.now(timezone.utc).isoformat()
        summary = {**payload}
        if image_data_url:
            summary["imageDataUrl"] = "[omitido]"
        if last_image_data_url:
            summary["lastImageDataUrl"] = "[omitido]"
        self.db.execute(
            """INSERT INTO generations (id, created_at, provider, prompt, workflow, request_json, status, video_url, local_path, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)""",
            (res["requestId"], now, provider, prompt, workflow, json.dumps(summary), res["status"], now),
        )
        self.db.commit()
        return res

    def extend_video(self, prompt, ref_history, provider, model, aspect_ratio, resolution, duration, mode="custom"):
        return self.create_video(prompt, provider, model, aspect_ratio, resolution, duration,
                                  mode=mode, workflow="extend", ref_history=ref_history)

    def get_video_status(self, request_id):
        status = self._request("GET", f"/api/videos/{request_id}")
        # Atualiza a linha a cada consulta — status/video_url no banco sempre
        # refletem a última checagem real (nunca confiar em /api/history).
        self.db.execute(
            "UPDATE generations SET status = ?, video_url = COALESCE(?, video_url), updated_at = ? WHERE id = ?",
            (status["status"], status.get("videoUrl"), datetime.now(timezone.utc).isoformat(), request_id),
        )
        self.db.commit()
        return status

    def wait_for_video(self, request_id, interval_s=6, timeout_s=300):
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            status = self.get_video_status(request_id)
            if status["status"] == "done":
                return status
            if status["status"] in ("failed", "expired"):
                raise RuntimeError(f"Geração falhou: {status.get('errorMessage', status['status'])}")
            time.sleep(interval_s)
        raise TimeoutError(f"Timeout aguardando geração de {request_id}")

    def download_video(self, video_id, video_url, dest_path):
        r = requests.get(video_url)  # não precisa de sessão, URL já é assinada
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            f.write(r.content)
        self.db.execute(
            "UPDATE generations SET local_path = ?, updated_at = ? WHERE id = ?",
            (str(dest_path), datetime.now(timezone.utc).isoformat(), video_id),
        )
        self.db.commit()

    def get_generation(self, video_id):
        row = self.db.execute("SELECT * FROM generations WHERE id = ?", (video_id,)).fetchone()
        return dict(row) if row else None

    def search_generations(self, text):
        rows = self.db.execute(
            "SELECT * FROM generations WHERE prompt LIKE ? ORDER BY created_at DESC", (f"%{text}%",)
        ).fetchall()
        return [dict(r) for r in rows]

    def download_by_id(self, video_id, dest_dir=None):
        """Baixa UM vídeo específico pelo id. Sem dest_dir, usa sempre
        ~/.destiny/downloads — pasta única/padrão, evita baixar 2x."""
        dest_dir = Path(dest_dir) if dest_dir else (DESTINY_DIR / "downloads")
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / f"{video_id}.mp4"
        if dest_path.exists():
            return str(dest_path)  # já baixado
        status = self.get_video_status(video_id)  # sempre revalida — videoUrl expira
        if status.get("status") != "done" or not status.get("videoUrl"):
            raise RuntimeError(f"Vídeo {video_id} ainda não está pronto (status: {status.get('status')})")
        self.download_video(video_id, status["videoUrl"], dest_path)
        return str(dest_path)

    def list_all_videos(self, items_per_page=30):
        """Lista o histórico inteiro e resolve o status REAL de cada vídeo
        (nunca confia no status de /api/history, ver §14)."""
        all_items = []
        page = 1
        while True:
            res = self.history(page=page, items_per_page=items_per_page)
            if not res.get("result"):
                break
            all_items.extend(res["result"])
            if len(all_items) >= res.get("total", 0):
                break
            page += 1
        resolved = []
        for v in all_items:
            try:
                resolved.append(self.get_video_status(v["uuid"]))
            except Exception:
                resolved.append({"id": v["uuid"], "status": "unknown"})
        return resolved

    def download_all_ready(self, dest_dir=None):
        """Baixa todos os vídeos com status 'done' que ainda não existem em
        dest_dir. Sem dest_dir, usa ~/.destiny/downloads (mesma pasta do
        download_by_id)."""
        dest_dir = Path(dest_dir) if dest_dir else (DESTINY_DIR / "downloads")
        dest_dir.mkdir(parents=True, exist_ok=True)
        downloaded = []
        for v in self.list_all_videos():
            if v.get("status") != "done" or not v.get("videoUrl"):
                continue
            dest_path = dest_dir / f"{v['id']}.mp4"
            if dest_path.exists():
                continue  # já baixado
            self.download_video(v["id"], v["videoUrl"], dest_path)
            downloaded.append(str(dest_path))
        return downloaded


def file_to_data_url(path):
    import base64, mimetypes
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{b64}"


# --- uso: gerar e baixar automaticamente assim que terminar ---
if __name__ == "__main__":
    client = DestinyClient()  # lê ~/.destiny/.env e ~/.destiny/session.json sozinho

    job = client.create_video(
        prompt="um gato laranja andando devagar em um jardim ensolarado",
        provider="veo", model="veo-3.1-fast",
        aspect_ratio="9:16", resolution="720p", duration=8,
    )
    client.wait_for_video(job["requestId"])
    # Sem dest_dir, cai direto em ~/.destiny/downloads/<requestId>.mp4
    path = client.download_by_id(job["requestId"])
    print("Pronto, baixado em:", path)

    # --- uso: baixar UM vídeo específico pelo id, em outra sessão/dia qualquer ---
    # (não baixa de novo se já existir em ~/.destiny/downloads)
    client.download_by_id("aa1a13fe-86a0-11f1-817a-ba4f920ea6f2")

    # --- uso: achar um vídeo pelo que lembro do prompt ---
    print(client.search_generations("gato"))

    # --- uso: baixar tudo que já estiver pronto na conta (sem gerar nada novo) ---
    baixados = client.download_all_ready()  # também usa ~/.destiny/downloads
    print(f"{len(baixados)} vídeo(s) baixado(s):", baixados)
```

---

## 17. Cliente de referência completo (bash/curl)

```bash
#!/usr/bin/env bash
set -euo pipefail

BASE="https://www.destinyai.com.br"
COOKIES="cookies.txt"
EMAIL="${DESTINY_EMAIL:?defina DESTINY_EMAIL}"
PASSWORD="${DESTINY_PASSWORD:?defina DESTINY_PASSWORD}"

login() {
  curl -s -c "$COOKIES" -X POST "$BASE/api/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\",\"fullName\":\"\",\"phone\":\"\",\"confirmPassword\":\"\"}" \
    > /dev/null
}

login

# 1. dispara geração
RESP=$(curl -s -b "$COOKIES" -X POST "$BASE/api/videos" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "um gato laranja andando devagar em um jardim ensolarado",
    "provider": "veo",
    "model": "veo-3.1-fast",
    "aspectRatio": "9:16",
    "resolution": "720p",
    "duration": 8,
    "mode": "custom",
    "workflow": "create"
  }')

REQUEST_ID=$(echo "$RESP" | jq -r '.requestId')
echo "Job criado: $REQUEST_ID"

# 2. polling a cada 6s, até 5 minutos
DEADLINE=$(($(date +%s) + 300))
while true; do
  if [ "$(date +%s)" -gt "$DEADLINE" ]; then
    echo "Timeout aguardando geração" >&2
    exit 1
  fi
  STATUS_JSON=$(curl -s -b "$COOKIES" "$BASE/api/videos/$REQUEST_ID")
  STATUS=$(echo "$STATUS_JSON" | jq -r '.status')
  echo "status=$STATUS"
  if [ "$STATUS" = "done" ]; then
    VIDEO_URL=$(echo "$STATUS_JSON" | jq -r '.videoUrl')
    echo "Vídeo pronto: $VIDEO_URL"
    curl -s -o video.mp4 "$VIDEO_URL"
    echo "Baixado em video.mp4"
    break
  fi
  if [ "$STATUS" = "failed" ] || [ "$STATUS" = "expired" ]; then
    echo "Geração falhou: $STATUS_JSON" >&2
    exit 1
  fi
  sleep 6
done
```

**Extensão de vídeo** — mesma estrutura, só troca o corpo do passo 1:
```bash
curl -s -b "$COOKIES" -X POST "$BASE/api/videos" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "continue o vídeo mostrando a pessoa saindo do estúdio",
    "provider": "veo",
    "model": "veo-3.1-fast",
    "aspectRatio": "9:16",
    "resolution": "720p",
    "duration": 8,
    "mode": "custom",
    "workflow": "extend",
    "refHistory": "<uuid do vídeo já concluído>"
  }'
```

**Imagem de referência via curl** (montando o data URI inline):
```bash
IMG_B64=$(base64 -i foto.jpg | tr -d '\n')
curl -s -b "$COOKIES" -X POST "$BASE/api/videos" \
  -H "Content-Type: application/json" \
  -d "{\"prompt\":\"gere um video da pessoa na @image...\",\"provider\":\"grok\",\"model\":\"grok-video\",\"imageDataUrl\":\"data:image/jpeg;base64,${IMG_B64}\",\"aspectRatio\":\"9:16\",\"resolution\":\"720p\",\"duration\":10,\"mode\":\"custom\",\"workflow\":\"create\"}"
```

---

## 18. Pendências / não mapeado

Testar antes de documentar como confirmado:

1. **Valores literais do `mode` do Grok** além de `"custom"` — `normal`,
   `extremely crazy`, `extremely spicy`/`crazy` (nomes exatos a confirmar
   testando cada botão da UI e capturando o payload).
2. **Combinações de `aspectRatio`/`resolution`/`duration` não testadas em
   request real:**
   - Veo: `16:9`, `4s`, `6s` (só testamos `9:16` + `720p`/`1080p` + `8s`).
   - Grok: `16:9`, `1:1`, `3:4`, `4:3`, `480p`, `6s`, `15s` (só testamos
     `9:16` + `720p` + `10s`).
3. **Formato de um job que falha durante o processamento** (não só na
   criação) — os literais `"failed"` e `"expired"` aparecem no código-fonte
   do frontend como estados esperados, mas nunca reproduzimos um job
   chegando nesse estado pra confirmar o JSON exato de erro.
4. **Limite de tamanho de payload/imagem** — maior teste real foi ~420KB
   (duas imagens ~200KB cada em base64); não sabemos o teto real aceito pelo
   backend.
5. Se durações/resoluções inválidas pra um provider (ex.: `duration: 8` no
   Grok, que só aceita 6/10/15) são **rejeitadas com erro claro** ou
   **silenciosamente normalizadas** — não testado.

**Nota:** o workflow `storyboard` ("Grok 30s") existe no código do frontend
mas está desativado pela própria Destiny no momento — propositalmente
**não documentado aqui** (ver `reverse-engineering-plan.md` seção "Achado
bônus" se precisar consultar os detalhes técnicos do payload).

Ver também `reverse-engineering-plan.md` para o histórico completo da
investigação, incluindo os testes que geraram cada um dos achados acima.
