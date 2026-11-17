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
        self.last_error = ""
        self.last_event = "尚未开始登录"
        self.capture_count = 0
        self.notify_callback = None

    async def _notify(self, message: str):
        if self.notify_callback:
            try:
                await self.notify_callback(message)
            except Exception:
                pass

    def status_text(self) -> str:
        return (
            f"浏览器：{'运行中' if self.context else '未运行'}\n"
            f"Token：{'已捕获' if self.get_saved_token() else '未捕获'}\n"
            f"捕获次数：{self.capture_count}\n"
            f"最近状态：{self.last_event}\n"
            f"最近错误：{self.last_error or '无'}"
        )

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
        if not self.page or self.page.is_closed():
            self.last_error = "远程浏览器页面不存在或已关闭"
            return False
        try:
            found = await self.page.evaluate("""() => {
                const keys = ['X-JLC-AccessToken', 'x-jlc-accesstoken',
                              'accessToken', 'access_token', 'token'];
                for (const key of keys) {
                    try {
                        const value = localStorage.getItem(key) || sessionStorage.getItem(key);
                        if (value) return value.replace(/^Bearer\\s+/i, '');
                    } catch (_) {}
                }
                return '';
            }""")
            if found and isinstance(found, str):
                self._save_token(found.strip())
                self.last_event = "从网页存储中捕获到 Token"
                self.last_error = ""
                return True
            self.last_event = "已检查网页存储，未发现 Token"
            return False
        except Exception as exc:
            self.last_error = f"读取网页存储失败：{type(exc).__name__}: {exc}"
            self.last_event = "网页存储检查失败"
            return False

    def _on_request(self, request):
        try:
            headers = request.headers
            token = headers.get("x-jlc-accesstoken") or headers.get("X-JLC-AccessToken")
            if token:
                value = token.removeprefix("Bearer ").strip()
                if value:
                    self._save_token(value)
                    self.capture_count += 1
                    self.last_event = f"已从请求头捕获 Token（请求：{request.method} {request.url.split('?')[0][:160]}）"
                    self.last_error = ""
        except Exception as exc:
            self.last_error = f"解析请求头失败：{type(exc).__name__}: {exc}"

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

            self.last_error = ""
            self.last_event = "正在检查 Tailscale 网络"
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
                self.last_event = "嘉立创页面已打开，等待登录和订单请求"

                app = web.Application(client_max_size=1024 * 1024)
                app.router.add_get("/status", self._status)
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
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                self.last_event = "网页登录启动失败"
                await self.close()
                raise RuntimeError(f"网页登录启动失败：{self.last_error}") from exc

    def _authorized(self, request):
        return secrets.compare_digest(request.query.get("key", ""), self.key)

    async def _index(self, request):
        if not self._authorized(request):
            raise web.HTTPForbidden(text="Invalid login link")
        return web.Response(text=PAGE, content_type="text/html")

    async def _status(self, request):
        if not self._authorized(request):
            raise web.HTTPForbidden()
        await self._capture_token()
        return web.json_response({
            "token": bool(self.get_saved_token()),
            "capture_count": self.capture_count,
            "event": self.last_event,
            "error": self.last_error,
            "browser": bool(self.context),
        })

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
            self.last_event = "登录凭证捕获成功"
            self.last_error = ""
            message = "嘉立创登录成功：AccessToken 已捕获并保存，临时浏览器入口已关闭。"
            await self._notify(message)
            await self.close(keep_server=True)
            asyncio.create_task(self._stop_server())
            return web.json_response({"ok": True, "message": message})
        self.last_event = "用户点击完成，但未捕获到 Token"
        detail = self.last_error or "请求监听和网页存储均未发现 AccessToken。请确认已登录，并进入“我的订单”触发订单接口请求。"
        message = "嘉立创登录凭证获取失败：\n" + detail
        await self._notify("⚠️ " + message)
        return web.json_response({"ok": False, "message": message, "detail": detail})

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
        self.last_event = "已退出登录并清除本地会话"
        self.last_error = ""
        self.capture_count = 0


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
<p class="warn" id="msg">不要把此页面链接分享给他人。登录成功后点击“完成登录并保存凭证”。</p>
<pre id="diag" style="white-space:pre-wrap;background:#1f2937;padding:10px;border-radius:8px">正在检查登录状态…</pre></main>
<script>
const q=new URLSearchParams(location.search),key=q.get('key'),img=document.querySelector('#screen'),msg=document.querySelector('#msg'),diag=document.querySelector('#diag');
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
document.querySelector('#finish').onclick=async()=>{try{const r=await api('/finish');const d=await r.json();msg.textContent=d.message;msg.style.color=d.ok?'#86efac':'#fca5a5';await status();}catch(e){msg.textContent='提交失败：'+e;msg.style.color='#fca5a5';}};
async function status(){try{const r=await fetch('/status?key='+encodeURIComponent(key));if(!r.ok)throw new Error('HTTP '+r.status);const d=await r.json();diag.textContent='浏览器：'+(d.browser?'运行中':'已关闭')+'\nToken：'+(d.token?'已捕获':'未捕获')+'\n捕获次数：'+d.capture_count+'\n最近状态：'+d.event+'\n最近错误：'+(d.error||'无');}catch(e){diag.textContent='状态获取失败：'+e;}}
refresh();status();setInterval(refresh,1200);setInterval(status,2000);
</script></html>"""
