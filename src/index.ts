#!/usr/bin/env node
import * as p from "@clack/prompts";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { homedir } from "node:os";
import {
  existsSync,
  mkdirSync,
  writeFileSync,
  readFileSync,
  cpSync,
  rmSync,
  lstatSync,
  symlinkSync,
  readlinkSync,
  chmodSync,
} from "node:fs";

const __dirname = dirname(fileURLToPath(import.meta.url));
// Quando rodando de dist/index.js dentro do pacote publicado, skill-payload
// fica um nivel acima (ver campo "files" do package.json).
const SKILL_PAYLOAD_DIR = join(__dirname, "..", "skill-payload");

const BASE = "https://www.destinyai.com.br";
const DESTINY_DIR = join(homedir(), ".destiny");
const ENV_PATH = join(DESTINY_DIR, ".env");
const SESSION_PATH = join(DESTINY_DIR, "session.json");

const AGENTS_SKILLS_DIR = join(homedir(), ".agents", "skills");
const CLAUDE_SKILLS_DIR = join(homedir(), ".claude", "skills");
const SKILL_NAME = "destiny-api";

interface Args {
  email?: string;
  password?: string;
  yes: boolean;
  targets?: string[]; // subset of ["claude", "agents"]
}

function parseArgs(argv: string[]): Args {
  const args: Args = { yes: false };
  for (const raw of argv) {
    const [flag, ...rest] = raw.split("=");
    const value = rest.join("=");
    switch (flag) {
      case "--email":
        args.email = value;
        break;
      case "--password":
        args.password = value;
        break;
      case "--yes":
        args.yes = true;
        break;
      case "--targets":
        args.targets = value.split(",").map((s) => s.trim()).filter(Boolean);
        break;
    }
  }
  return args;
}

function readCurrentSession(): { cookie: string; expiresAt: string } | null {
  if (!existsSync(SESSION_PATH)) return null;
  try {
    const data = JSON.parse(readFileSync(SESSION_PATH, "utf8"));
    if (new Date(data.expiresAt).getTime() > Date.now()) return data;
  } catch {
    // arquivo corrompido, ignora
  }
  return null;
}

async function testLogin(email: string, password: string): Promise<{ cookie: string; account: any }> {
  const loginRes = await fetch(`${BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, fullName: "", phone: "", confirmPassword: "" }),
  });
  if (!loginRes.ok) {
    const body = (await loginRes.json().catch(() => ({}))) as { error?: string };
    throw new Error(body.error || `Login falhou (HTTP ${loginRes.status})`);
  }

  // getSetCookie() existe em Node/undici mais novo; fallback pro header cru.
  const headersAny = loginRes.headers as any;
  const setCookieList: string[] = typeof headersAny.getSetCookie === "function"
    ? headersAny.getSetCookie()
    : [loginRes.headers.get("set-cookie") ?? ""];
  const setCookie = setCookieList[0];
  if (!setCookie) throw new Error("Login OK mas nenhum cookie de sessao foi recebido (Set-Cookie ausente).");
  const cookie = setCookie.split(";")[0]!;

  const accountRes = await fetch(`${BASE}/api/account`, { headers: { Cookie: cookie } });
  if (!accountRes.ok) throw new Error(`Login pareceu ok mas /api/account falhou (HTTP ${accountRes.status})`);
  const account = await accountRes.json();
  return { cookie, account };
}

function writeCredentials(email: string, password: string) {
  mkdirSync(DESTINY_DIR, { recursive: true });
  const content = `DESTINY_EMAIL=${email}\nDESTINY_PASSWORD=${password}\n`;
  writeFileSync(ENV_PATH, content, { mode: 0o600 });
  chmodSync(ENV_PATH, 0o600);
}

function writeSession(cookie: string) {
  mkdirSync(DESTINY_DIR, { recursive: true });
  const expiresAt = new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString();
  writeFileSync(SESSION_PATH, JSON.stringify({ cookie, expiresAt }, null, 2), { mode: 0o600 });
  chmodSync(SESSION_PATH, 0o600);
}

/** Instala o conteudo real da skill em ~/.agents/skills/destiny-api (sempre —
 * e a fonte da verdade), e opcionalmente cria um symlink em
 * ~/.claude/skills/destiny-api apontando pra la. Mesmo padrao usado pela
 * skill "skill-creator" neste ambiente: conteudo unico + symlink, nunca
 * duas copias divergentes. */
function installSkill(targets: string[]): { agentsPath: string; claudePath: string | null } {
  const agentsPath = join(AGENTS_SKILLS_DIR, SKILL_NAME);
  mkdirSync(AGENTS_SKILLS_DIR, { recursive: true });
  if (existsSync(agentsPath)) rmSync(agentsPath, { recursive: true, force: true });
  cpSync(SKILL_PAYLOAD_DIR, agentsPath, { recursive: true });
  chmodSync(join(agentsPath, "scripts", "destiny_client.py"), 0o755);

  let claudePath: string | null = null;
  if (targets.includes("claude")) {
    claudePath = join(CLAUDE_SKILLS_DIR, SKILL_NAME);
    mkdirSync(CLAUDE_SKILLS_DIR, { recursive: true });
    if (existsSync(claudePath) || isBrokenSymlink(claudePath)) {
      const st = lstatSync(claudePath);
      if (st.isSymbolicLink() && readlinkSync(claudePath) === agentsPath) {
        // ja aponta pro lugar certo, nada a fazer
      } else {
        rmSync(claudePath, { recursive: true, force: true });
        symlinkSync(agentsPath, claudePath);
      }
    } else {
      symlinkSync(agentsPath, claudePath);
    }
  }

  return { agentsPath, claudePath };
}

function isBrokenSymlink(path: string): boolean {
  try {
    lstatSync(path);
    return true;
  } catch {
    return false;
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));

  p.intro("Destiny API — setup de sessao");

  let email = args.email ?? process.env.DESTINY_EMAIL;
  let password = args.password ?? process.env.DESTINY_PASSWORD;

  const cached = readCurrentSession();
  if (cached && !email && !password) {
    p.log.info("Sessao existente encontrada em ~/.destiny/session.json (ainda valida).");
    const reuse = args.yes
      ? true
      : await p.confirm({ message: "Reutilizar essa sessao (sem pedir email/senha de novo)?", initialValue: true });
    if (p.isCancel(reuse)) return cancelAndExit();
    if (reuse) {
      const targets = await resolveTargets(args);
      const { agentsPath, claudePath } = installSkill(targets);
      finishOutro(agentsPath, claudePath);
      return;
    }
  }

  if (!email) {
    const answer = await p.text({
      message: "Email da conta Destiny",
      validate: (v) => (v.includes("@") ? undefined : "Digite um email valido"),
    });
    if (p.isCancel(answer)) return cancelAndExit();
    email = answer;
  }

  if (!password) {
    const answer = await p.password({
      message: "Senha",
      validate: (v) => (v.length > 0 ? undefined : "Senha nao pode ser vazia"),
    });
    if (p.isCancel(answer)) return cancelAndExit();
    password = answer;
  }

  const s = p.spinner();
  s.start("Testando login...");
  let cookie: string;
  let account: any;
  try {
    const result = await testLogin(email, password);
    cookie = result.cookie;
    account = result.account;
    s.stop(`Login OK — ${account.fullName ?? account.email} (${account.availableCredit} creditos disponiveis)`);
  } catch (err) {
    s.stop("Login falhou.");
    p.log.error(err instanceof Error ? err.message : String(err));
    p.outro("Nada foi salvo em disco. Rode de novo com credenciais corretas.");
    process.exitCode = 1;
    return;
  }

  writeCredentials(email, password);
  writeSession(cookie);

  const targets = await resolveTargets(args);
  const installSpinner = p.spinner();
  installSpinner.start("Instalando skill...");
  const { agentsPath, claudePath } = installSkill(targets);
  installSpinner.stop("Skill instalada.");

  finishOutro(agentsPath, claudePath);
}

async function resolveTargets(args: Args): Promise<string[]> {
  if (args.targets) return args.targets;
  if (args.yes) return ["claude", "agents"];
  // O conteudo real sempre vai pra ~/.agents/skills (fonte da verdade); a
  // unica decisao real do usuario e se tambem quer o atalho pro Claude Code.
  const answer = await p.confirm({
    message: "Criar atalho da skill em ~/.claude/skills tambem (alem de ~/.agents/skills)?",
    initialValue: true,
  });
  if (p.isCancel(answer)) return cancelAndExit();
  return answer ? ["claude", "agents"] : ["agents"];
}

function finishOutro(agentsPath: string, claudePath: string | null) {
  p.log.success(`Skill instalada em: ${agentsPath}`);
  if (claudePath) p.log.success(`Atalho (symlink) criado em: ${claudePath}`);
  p.log.info("Credenciais: ~/.destiny/.env  |  Sessao: ~/.destiny/session.json");
  p.log.info(`Teste rapido: python3 ${agentsPath}/scripts/destiny_client.py account`);
  p.outro("Pronto. Qualquer agente com a skill carregada ja sabe usar a API da Destiny.");
}

function cancelAndExit(): never {
  p.cancel("Cancelado.");
  process.exit(1);
}

main().catch((err) => {
  p.log.error(err instanceof Error ? err.stack ?? err.message : String(err));
  process.exitCode = 1;
});
