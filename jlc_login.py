"""Temporary Tailscale-only browser login helper for JLC."""
import asyncio
import json
import os
import secrets
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from aiohttp import web


class JlcWebLogin:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.profile_dir = self.data_dir / "browser_profile"
        self.token_file = self.data_dir / "auth.json"
        self.key = secrets.token_urlsafe(24)
        self.host = ""
        self.port = 18763
        self.runner = None
        self.site = None
        self.playwright = None
        self.context = None
        self.page = None
        self.token: Optional[str] = None
        self._lock = asyncio.Lock()

    @staticmethod
    def _tailscale_ip() -> str:
        if not shutil.which("tailscale"):
            raise RuntimeError("没有检测到 tailscale 命令。请先在小主机安装并登录 Tailscale。")
        result = subprocess.run(
            ["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=5
        )
        ip = result.stdout.strip().splitlines()[0] if result.returncode == 0 and result.stdout.strip() else ""
        if not ip:
            raise RuntimeError("无法获取 Tailscale IPv4 地址，请确认 Tailscale 在线。")
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
        temp.write_text(
            json.dumps({"access_token": token}, ensure_ascii=False),
            encoding="utf-8",
        )
        os.chmod(temp, 0o600)
        temp.replace(self.token_file)
        self.token = token

    async def _capture_token(self):
        if self.page and not self.page.is_closed():
            try:
                found = await self.page.evaluate("""() => {
                    const keys = ['X-JLC-AccessToken', 'x-jlc-accesstoken',
                                  'accessToken', 'access_token', 'token'];
                    for (const key of keys) {
                        const value = localStorage.getItem(key) || sessionStorage.getItem(key);
                        if (value) return value.replace(/^Bearer\\s+/i, '');
                    }
                    return '';
                }""")
                if found and isinstance(found, str):
                    self._save_token(found.strip())
            except Exception:
                pass

    def _on_request(self, request):
        try:
            headers = request.headers
            token = headers.get("x-jlc-accesstoken") or headers.get("X-JLC-AccessToken")
            if token:
                self._save_token(token.removeprefix("Bearer ").strip())
        except Exception:
            pass

    async def start(self) -> str:
        async with self._lock:
            if self.runner:
                return f"http://{self.host}:{self.port}/?key={self.key}"
            try:
                from playwright.async_api import async_playwright
            except ImportError as exc:
                raise RuntimeError(
                    "缺少 Playwright 依赖。请在 AstrBot 虚拟环境执行："
                    "uv pip install playwright aiohttp && "
                    "uv run playwright install chromium"
                ) from exc

            self.host = self._tailscale_ip()
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.playwright = await async_playwright().start()
            try:
                self.context = await self.playwright.chromium.launch_persistent_context(
                    user_data_dir=str(self.profile_dir),
                    headless=True,
                    viewport={"width": 1280, "height": 820},
                    locale="zh-CN",
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                if self.profile_dir.exists():
                    os.chmod(self.profile_dir, 0o700)
                self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
                self.page.on("request", self._on_request)
                await self.page.goto("https://m.jlc.com/", wait_until="domcontentloaded", timeout=60000)

                app = web.Application(client_max_size=1024 * 1024)
                app.router.add_get("/", self._index)
                app.router.add_get("/screen", self._screen)
                app.router.add_post("/click", self._click)
                app.router.add_post("/move", self._move)
                app.router.add_post("/down", self._down)
                app.router.add_post("/up", self._up)
                app.router.add_post("/type", self._type)
                app.router.add_post("/key", self._key)
                app.router.add_post("/scroll", self._scroll)
                app.router.add_post("/finish", self._finish)
                runner = web.AppRunner(app, access_log=None)
                await runner.setup()
                site = web.TCPSite(runner, self.host, self.port)
                await site.start()
                self.runner, self.site = runner, site
                return f"http://{self.host}:{self.port}/?key={self.key}"
            except Exception:
                await self.close()
                raise

    def _authorized(self, request):
        return secrets.compare_digest(request.query.get("key", ""), self.key)

    async def _index(self, request):
        if not self._authorized(request):
            raise web.HTTPForbidden(text="Invalid login link")
        return web.Response(text=PAGE, content_type="text/html")

    async def _screen(self, request):
        if not self._authorized(request):
            raise web.HTTPForbidden()
        await self._capture_token()
        if not self.page or self.page.is_closed():
            raise web.HTTPGone()
        shot = await self.page.screenshot(type="jpeg", quality=65)
        return web.Response(body=shot, content_type="image/jpeg", headers={"Cache-Control": "no-store"})

    async def _payload(self, request):
        if not self._authorized(request):
            raise web.HTTPForbidden()
        return await request.json()

    async def _click(self, request):
        data = await self._payload(request)
        if self.page:
            await self.page.mouse.click(float(data["x"]), float(data["y"]))
        return web.json_response({"ok": True})

    async def _move(self, request):
        data = await self._payload(request)
        if self.page:
            await self.page.mouse.move(float(data["x"]), float(data["y"]))
        return web.json_response({"ok": True})

    async def _down(self, request):
        await self._payload(request)
        if self.page:
            await self.page.mouse.down()
        return web.json_response({"ok": True})

    async def _up(self, request):
        await self._payload(request)
        if self.page:
            await self.page.mouse.up()
        return web.json_response({"ok": True})

    async def _type(self, request):
        data = await self._payload(request)
        if self.page:
            await self.page.keyboard.insert_text(str(data.get("text", ""))[:2000])
        return web.json_response({"ok": True})

    async def _key(self, request):
        data = await self._payload(request)
        allowed = {"Enter", "Tab", "Escape", "Backspace", "Delete", "ArrowUp",
                   "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End"}
        key = str(data.get("key", ""))
        if self.page and key in allowed:
            await self.page.keyboard.press(key)
        return web.json_response({"ok": True})

    async def _scroll(self, request):
        data = await self._payload(request)
        if self.page:
            await self.page.mouse.wheel(float(data.get("x", 0)), float(data.get("y", 0)))
        return web.json_response({"ok": True})

    async def _finish(self, request):
        if not self._authorized(request):
            raise web.HTTPForbidden()
        await self._capture_token()
        found = bool(self.get_saved_token())
        if found:
            await self.close(keep_server=True)
            asyncio.create_task(self._stop_server())
            return web.json_response({"ok": True, "message": "凭证已保存，临时浏览器和登录入口已关闭。"})
        return web.json_response({"ok": False, "message": "尚未捕获到 Token。请在远程浏览器中进入“我的订单”，等待订单请求完成后再点击此按钮。"})

    async def _stop_server(self):
        await asyncio.sleep(1)
        if self.runner:
            await self.runner.cleanup()
        self.runner = self.site = None

    async def close(self, keep_server=False):
        if self.context:
            try:
                await self.context.close()
            except Exception:
                pass
        self.context = self.page = None
        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception:
                pass
        self.playwright = None
        if not keep_server and self.runner:
            try:
                await self.runner.cleanup()
            except Exception:
                pass
            self.runner = self.site = None

    async def logout(self):
        await self.close()
        for path in (self.token_file, self.profile_dir):
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink(missing_ok=True)
            except OSError:
                pass
        self.token = None


PAGE = r"""<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>嘉立创网页登录</title>
<style>
body{font:15px system-ui;margin:0;background:#111827;color:#f9fafb}header{padding:12px 16px;background:#1f2937;position:sticky;top:0}
main{max-width:1280px;margin:auto;padding:12px}#screen{width:100%;display:block;cursor:crosshair;background:#fff;touch-action:pan-y}
.row{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}button,input{font:inherit;padding:10px;border:0;border-radius:7px}button{background:#2563eb;color:white}input{flex:1;min-width:180px}
small{color:#cbd5e1}.warn{color:#fbbf24}
</style>
<header><b>嘉立创网页登录</b>　<small>临时 Tailscale 登录入口</small></header>
<main><p>请在下方浏览器中登录嘉立创。点击页面输入账号信息；输入框可输入文字，按回车提交。手机扫码可直接用手机扫描屏幕二维码。</p>
<img id="screen" alt="正在连接浏览器…">
<div class="row"><input id="text" placeholder="在当前焦点输入框中输入文字"><button id="send">输入</button></div>
<div class="row"><button data-key="Enter">回车</button><button data-key="Tab">Tab</button><button data-key="Escape">Esc</button><button data-key="Backspace">退格</button><button id="refresh">刷新画面</button></div>
<div class="row"><button id="finish">完成登录并保存凭证</button></div>
<p class="warn" id="msg">不要把此页面链接分享给他人。登录成功后点击“完成登录并保存凭证”。</p></main>
<script>
const q=new URLSearchParams(location.search),key=q.get('key'),img=document.querySelector('#screen'),msg=document.querySelector('#msg');
const api=(p,b={})=>fetch(p+'?key='+encodeURIComponent(key),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});
let busy=false;
async function refresh(){if(busy)return;busy=true;try{const r=await fetch('/screen?key='+encodeURIComponent(key)+'&t='+Date.now());if(r.ok)img.src=URL.createObjectURL(await r.blob());else msg.textContent='浏览器会话已结束或链接失效。'}catch(e){}busy=false;}
let dragging=false,moved=false;
function pos(e){const r=img.getBoundingClientRect();return {x:(e.clientX-r.left)*img.naturalWidth/r.width,y:(e.clientY-r.top)*img.naturalHeight/r.height};}
let mouseQueue=Promise.resolve();
function enqueue(path,data){mouseQueue=mouseQueue.then(()=>api(path,data));return mouseQueue;}
img.addEventListener('pointerdown',e=>{dragging=true;moved=false;img.setPointerCapture(e.pointerId);enqueue('/move',pos(e)).then(()=>enqueue('/down',{}));});
img.addEventListener('pointermove',e=>{if(dragging){moved=true;enqueue('/move',pos(e));}});
img.addEventListener('pointerup',e=>{if(dragging){dragging=false;enqueue('/up',{}).then(()=>setTimeout(refresh,500));}});
document.querySelector('#send').onclick=async()=>{const el=document.querySelector('#text');await api('/type',{text:el.value});el.value='';setTimeout(refresh,500);};
document.querySelector('#text').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();document.querySelector('#send').click();}});
document.querySelectorAll('[data-key]').forEach(b=>b.onclick=()=>api('/key',{key:b.dataset.key}).then(()=>setTimeout(refresh,500)));
img.addEventListener('wheel',e=>{e.preventDefault();api('/scroll',{x:e.deltaX,y:e.deltaY}).then(()=>setTimeout(refresh,500));},{passive:false});
document.querySelector('#refresh').onclick=refresh;
document.querySelector('#finish').onclick=async()=>{const r=await api('/finish');const d=await r.json();msg.textContent=d.message;};
refresh();setInterval(refresh,1200);
</script></html>"""
