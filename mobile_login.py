"""Android companion pairing endpoint for JLC AccessToken transfer."""
import asyncio
import hmac
import json
import os
import secrets
import shutil
import subprocess
import time
from pathlib import Path
from aiohttp import web


class JlcMobileLogin:
    """Accept one short-lived token transfer from the Android companion app."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.token_file = self.data_dir / "auth.json"
        self.key = ""
        self.host = ""
        self.port = 18763
        self.expires_at = 0.0
        self.runner = None
        self.site = None
        self.notify_callback = None
        self.last_event = "尚未发起手机登录"
        self.last_error = ""
        self._used = False
        self._lock = asyncio.Lock()

    @staticmethod
    def _tailscale_ip() -> str:
        if not shutil.which("tailscale"):
            raise RuntimeError("没有检测到 tailscale 命令，请先确认小主机已登录 Tailscale。")
        result = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=5)
        ip = result.stdout.strip().splitlines()[0] if result.returncode == 0 and result.stdout.strip() else ""
        parts = ip.split(".")
        if len(parts) != 4 or parts[0] != "100" or not parts[1].isdigit() or not 64 <= int(parts[1]) <= 127 or not all(p.isdigit() and 0 <= int(p) <= 255 for p in parts[2:]):
            raise RuntimeError("无法获取有效的 Tailscale IPv4 地址，已拒绝启动登录服务。")
        return ip

    def get_saved_token(self) -> str:
        try:
            data = json.loads(self.token_file.read_text(encoding="utf-8"))
            return str(data.get("access_token") or "").strip()
        except (OSError, ValueError, TypeError):
            return ""

    def _save_token(self, token: str):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.data_dir, 0o700)
        temp = self.token_file.with_suffix(".tmp")
        temp.write_text(json.dumps({"access_token": token}, ensure_ascii=False), encoding="utf-8")
        os.chmod(temp, 0o600)
        temp.replace(self.token_file)

    async def _notify(self, message: str):
        if self.notify_callback:
            try:
                await self.notify_callback(message)
            except Exception:
                pass

    def status_text(self) -> str:
        active = bool(self.runner and not self._used and time.time() < self.expires_at)
        state = "等待安卓手机完成登录" if active else ("已获取登录凭证" if self.get_saved_token() else self.last_event)
        return f"登录方式：安卓手机本机登录\n状态：{state}\n最近错误：{self.last_error or '无'}"

    def _authorized(self, request) -> bool:
        supplied = request.query.get("key", "")
        return bool(self.key and time.time() < self.expires_at and not self._used
                    and hmac.compare_digest(supplied, self.key))

    async def start(self) -> str:
        await self.close()
        self.host = self._tailscale_ip()
        self.key = secrets.token_urlsafe(32)
        self.expires_at = time.time() + 600
        self._used = False
        self.last_error = ""
        self.last_event = "已创建 10 分钟有效的一次性手机配对"
        app = web.Application(client_max_size=16 * 1024)
        app.router.add_get("/health", self._health)
        app.router.add_get("/open", self._open_page)
        app.router.add_post("/token", self._receive_token)
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        self.site = web.TCPSite(runner=self.runner, host=self.host, port=self.port)
        try:
            await self.site.start()
        except Exception:
            await self.close()
            raise
        from urllib.parse import quote
        endpoint = f"http://{self.host}:{self.port}"
        return f"http://{self.host}:{self.port}/open?key={quote(self.key, safe="")}"

    async def _open_page(self, request):
        if not self._authorized(request):
            raise web.HTTPForbidden(text="配对链接已失效，请重新发送 /jlc登录")
        from urllib.parse import quote
        endpoint = f"http://{self.host}:{self.port}"
        deep_link = f"jlcorder://login?server={quote(endpoint, safe=chr(0))}&key={quote(self.key, safe=chr(0))}"
        deep_link = deep_link.replace(chr(0), "")
        html = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
        <title>打开嘉立创登录助手</title><style>body{font:16px system-ui;padding:28px;line-height:1.7}a{display:block;padding:14px;background:#1677ff;color:white;text-decoration:none;border-radius:8px;text-align:center}</style>
        <h3>嘉立创手机登录</h3><p>请确认已安装嘉立创登录助手 APK，并且手机已连接 Tailscale。</p>
        <a href="DEEP_LINK">打开嘉立创登录助手</a><p>如果没有自动跳转，请点击上方按钮。</p>"""
        return web.Response(text=html.replace("DEEP_LINK", deep_link), content_type="text/html")
    async def _health(self, request):
        if not self._authorized(request):
            raise web.HTTPForbidden(text="Pairing link expired or invalid")
        return web.json_response({"ok": True, "expires_in": max(0, int(self.expires_at - time.time()))})

    async def _receive_token(self, request):
        if not self._authorized(request):
            raise web.HTTPForbidden(text="Pairing link expired or invalid")
        async with self._lock:
            if not self._authorized(request):
                raise web.HTTPForbidden(text="Pairing link already used")
            try:
                payload = await request.json()
            except Exception:
                raise web.HTTPBadRequest(text="Invalid JSON")
            token = payload.get("token") if isinstance(payload, dict) else None
            if not isinstance(token, str):
                raise web.HTTPBadRequest(text="Token missing")
            token = token.removeprefix("Bearer ").strip()
            if len(token) < 8 or len(token) > 8192 or any(ord(c) < 33 or ord(c) > 126 for c in token):
                raise web.HTTPBadRequest(text="Token format rejected")
            self._save_token(token)
            self._used = True
            self.last_event = "安卓手机已成功回传 AccessToken"
            self.last_error = ""
            await self._notify("✅ 嘉立创手机登录成功：AccessToken 已安全接收并保存。")
            asyncio.create_task(self._stop_server())
            return web.json_response({"ok": True, "message": "登录凭证已保存"})

    async def _stop_server(self):
        runner = self.runner
        await asyncio.sleep(1)
        if runner and self.runner is runner:
            await runner.cleanup()
            self.runner = self.site = None
            self.key = ""

    async def close(self):
        if self.runner:
            try:
                await self.runner.cleanup()
            except Exception:
                pass
        self.runner = self.site = None
        self.key = ""
        self.expires_at = 0.0

    async def logout(self):
        await self.close()
        try:
            self.token_file.unlink(missing_ok=True)
        except OSError:
            pass
        self.last_event = "已清除保存的嘉立创登录凭证"
        self.last_error = ""
