#!/usr/bin/env python3
"""Cliente de referência pra API não-oficial da Destiny (DestinyGen AI).

Uso como biblioteca:
    from destiny_client import DestinyClient
    client = DestinyClient()
    job = client.create_video(prompt="...", provider="veo", model="veo-3.1-fast",
                               aspect_ratio="9:16", resolution="720p", duration=8)
    finished = client.wait_for_video(job["requestId"])
    client.download_by_id(job["requestId"])

Uso como CLI:
    python3 destiny_client.py account
    python3 destiny_client.py generate --provider veo --model veo-3.1-fast \
        --aspect-ratio 9:16 --resolution 720p --duration 8 --prompt "um gato andando"
    python3 destiny_client.py status <requestId>
    python3 destiny_client.py wait <requestId>
    python3 destiny_client.py download <requestId>
    python3 destiny_client.py download-all
    python3 destiny_client.py search "gato"
    python3 destiny_client.py list

Toda a documentação de campos, limites por provider, tabela de preços e os
bugs conhecidos da API estão em ../references/api-guide.md — leia antes de
montar um payload que não seja um dos exemplos já testados aqui.
"""

import argparse
import json
import mimetypes
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

BASE = "https://www.destinyai.com.br"
DESTINY_DIR = Path.home() / ".destiny"
ENV_PATH = DESTINY_DIR / ".env"
SESSION_PATH = DESTINY_DIR / "session.json"
DB_PATH = DESTINY_DIR / "history.db"
DOWNLOADS_DIR = DESTINY_DIR / "downloads"


def _read_env_file():
    if not ENV_PATH.exists():
        raise RuntimeError(
            f"Credenciais não encontradas em {ENV_PATH}. "
            "Rode o instalador da skill primeiro (cria DESTINY_EMAIL/DESTINY_PASSWORD lá)."
        )
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
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        return None  # expirado
    return data["cookie"]


def _write_session(cookie):
    DESTINY_DIR.mkdir(parents=True, exist_ok=True)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    SESSION_PATH.write_text(json.dumps({"cookie": cookie, "expiresAt": expires_at}, indent=2))
    os.chmod(SESSION_PATH, 0o600)


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


def file_to_data_url(path):
    """Converte um arquivo de imagem local em data URI base64 (formato exigido
    por imageDataUrl/lastImageDataUrl)."""
    import base64
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{b64}"


class DestinyClient:
    """Nenhuma credencial precisa ser passada — lê ~/.destiny/.env e
    ~/.destiny/session.json sozinho, relogando automaticamente quando
    necessário."""

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
            raise RuntimeError(
                f"{body.get('errorCode')}: {body.get('error')} (retryable={body.get('retryable')})"
            )
        return body

    def account(self):
        return self._request("GET", "/api/account")

    def billing_plans(self):
        return self._request("GET", "/api/billing/plans")

    def history(self, page=1, items_per_page=30):
        return self._request(
            "GET", f"/api/history?filter_by=video&items_per_page={items_per_page}&page={page}"
        )

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

        now = datetime.now(timezone.utc).isoformat()
        summary = {**payload}
        if image_data_url:
            summary["imageDataUrl"] = "[omitido]"
        if last_image_data_url:
            summary["lastImageDataUrl"] = "[omitido]"
        self.db.execute(
            """INSERT OR REPLACE INTO generations
               (id, created_at, provider, prompt, workflow, request_json, status, video_url, local_path, updated_at)
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
        dest_path = Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
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
        dest_dir = Path(dest_dir) if dest_dir else DOWNLOADS_DIR
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
        (nunca confia no status de /api/history — ver references/api-guide.md §14)."""
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
        dest_dir. Sem dest_dir, usa ~/.destiny/downloads."""
        dest_dir = Path(dest_dir) if dest_dir else DOWNLOADS_DIR
        dest_dir.mkdir(parents=True, exist_ok=True)
        downloaded = []
        for v in self.list_all_videos():
            if v.get("status") != "done" or not v.get("videoUrl"):
                continue
            dest_path = dest_dir / f"{v['id']}.mp4"
            if dest_path.exists():
                continue
            self.download_video(v["id"], v["videoUrl"], dest_path)
            downloaded.append(str(dest_path))
        return downloaded


def _cli():
    p = argparse.ArgumentParser(description="Cliente CLI da API não-oficial da Destiny")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("account", help="mostra saldo de créditos da conta")
    sub.add_parser("plans", help="mostra tabela de preços/planos")
    sub.add_parser("list", help="lista todo o histórico com status real")
    sub.add_parser("download-all", help="baixa todos os vídeos prontos em ~/.destiny/downloads")

    g = sub.add_parser("generate", help="dispara geração de vídeo (workflow=create)")
    g.add_argument("--prompt", required=True)
    g.add_argument("--provider", required=True, choices=["veo", "grok"])
    g.add_argument("--model", required=True)
    g.add_argument("--aspect-ratio", required=True)
    g.add_argument("--resolution", required=True)
    g.add_argument("--duration", required=True, type=int)
    g.add_argument("--mode", default="custom")
    g.add_argument("--image", help="caminho de arquivo local pra usar como imageDataUrl")
    g.add_argument("--last-image", help="caminho de arquivo local pra usar como lastImageDataUrl (só Veo)")
    g.add_argument("--wait", action="store_true", help="aguarda terminar e já baixa")

    e = sub.add_parser("extend", help="estende um vídeo já pronto (workflow=extend)")
    e.add_argument("--prompt", required=True)
    e.add_argument("--ref-history", required=True, help="uuid do vídeo de origem, já concluído")
    e.add_argument("--provider", required=True, choices=["veo", "grok"])
    e.add_argument("--model", required=True)
    e.add_argument("--aspect-ratio", required=True)
    e.add_argument("--resolution", required=True)
    e.add_argument("--duration", required=True, type=int)
    e.add_argument("--mode", default="custom")
    e.add_argument("--wait", action="store_true")

    s = sub.add_parser("status", help="checa status real de um vídeo")
    s.add_argument("request_id")

    w = sub.add_parser("wait", help="aguarda um vídeo terminar (polling)")
    w.add_argument("request_id")

    d = sub.add_parser("download", help="baixa um vídeo específico pelo id")
    d.add_argument("request_id")

    se = sub.add_parser("search", help="busca gerações no histórico local pelo prompt")
    se.add_argument("text")

    args = p.parse_args()
    client = DestinyClient()

    if args.cmd == "account":
        print(json.dumps(client.account(), indent=2, ensure_ascii=False))
    elif args.cmd == "plans":
        print(json.dumps(client.billing_plans(), indent=2, ensure_ascii=False))
    elif args.cmd == "list":
        print(json.dumps(client.list_all_videos(), indent=2, ensure_ascii=False))
    elif args.cmd == "download-all":
        print(json.dumps(client.download_all_ready(), indent=2, ensure_ascii=False))
    elif args.cmd == "generate":
        image_data_url = file_to_data_url(args.image) if args.image else None
        last_image_data_url = file_to_data_url(args.last_image) if args.last_image else None
        job = client.create_video(
            prompt=args.prompt, provider=args.provider, model=args.model,
            aspect_ratio=args.aspect_ratio, resolution=args.resolution, duration=args.duration,
            mode=args.mode, image_data_url=image_data_url, last_image_data_url=last_image_data_url,
        )
        print(json.dumps(job, indent=2, ensure_ascii=False))
        if args.wait:
            finished = client.wait_for_video(job["requestId"])
            path = client.download_by_id(job["requestId"])
            print(f"Pronto, baixado em: {path}")
    elif args.cmd == "extend":
        job = client.extend_video(
            prompt=args.prompt, ref_history=args.ref_history, provider=args.provider,
            model=args.model, aspect_ratio=args.aspect_ratio, resolution=args.resolution,
            duration=args.duration, mode=args.mode,
        )
        print(json.dumps(job, indent=2, ensure_ascii=False))
        if args.wait:
            finished = client.wait_for_video(job["requestId"])
            path = client.download_by_id(job["requestId"])
            print(f"Pronto, baixado em: {path}")
    elif args.cmd == "status":
        print(json.dumps(client.get_video_status(args.request_id), indent=2, ensure_ascii=False))
    elif args.cmd == "wait":
        print(json.dumps(client.wait_for_video(args.request_id), indent=2, ensure_ascii=False))
    elif args.cmd == "download":
        print(client.download_by_id(args.request_id))
    elif args.cmd == "search":
        print(json.dumps(client.search_generations(args.text), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    try:
        _cli()
    except Exception as e:
        print(f"Erro: {e}", file=sys.stderr)
        sys.exit(1)
