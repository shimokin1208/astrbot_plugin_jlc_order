"""Capture JLC access tokens from Windows Chrome/Edge through Tailscale CDP."""
import asyncio
import json
import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

class JlcWebLogin:
    def __init__(self, data_dir: Path, cdp_url: str = ""):
        self.data_dir=Path(data_dir); self.token_file=self.data_dir/"auth.json"
        self.cdp_url=str(cdp_url or "").strip().rstrip("/")
        self.playwright=None; self.browser=None; self.context=None; self.page=None
        self.token: Optional[str]=None; self.last_error=""; self.last_event="尚未连接 Windows 浏览器"
        self.capture_count=0; self.notify_callback=None; self._lock=asyncio.Lock()

    async def _notify(self,message):
        if self.notify_callback:
            try: await self.notify_callback(message)
            except Exception: pass

    def get_saved_token(self):
        try: return str(json.loads(self.token_file.read_text(encoding="utf-8")).get("access_token") or "").strip()
        except (OSError,ValueError,TypeError): return ""

    def _save_token(self,token):
        token=str(token or "").removeprefix("Bearer ").strip()
        if not token: return
        self.data_dir.mkdir(parents=True,exist_ok=True); os.chmod(self.data_dir,0o700)
        tmp=self.token_file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"access_token":token},ensure_ascii=False),encoding="utf-8")
        os.chmod(tmp,0o600); tmp.replace(self.token_file)
        self.token=token; self.last_error=""; self.last_event="已从 Windows 浏览器请求头捕获并保存 Token"

    def _attach_page(self,page):
        if getattr(page,"_jlc_listener_attached",False): return
        page._jlc_listener_attached=True
        page.on("request",self._on_request); page.on("requestfailed",self._on_request_failed); page.on("response",self._on_response)

    def _on_request(self,request):
        try:
            h=request.headers; token=h.get("x-jlc-accesstoken") or h.get("X-JLC-AccessToken")
            if token: self._save_token(token); self.capture_count+=1
        except Exception as exc: self.last_error=f"解析浏览器请求头失败：{type(exc).__name__}: {exc}"

    def _on_request_failed(self,request):
        try:
            host=urlsplit(request.url).netloc
            if "jlc.com" in host:
                self.last_error=f"嘉立创请求失败：{request.method} {host}；{request.failure or '未知网络错误'}"
                self.last_event="嘉立创页面请求失败"
        except Exception as exc: self.last_error=f"读取请求失败信息异常：{exc}"

    def _on_response(self,response):
        try:
            if "m.jlc.com/api/" in response.url and response.status in (401,403):
                self.last_error=f"嘉立创 API 返回 HTTP {response.status}"; self.last_event="登录可能失效或接口拒绝访问"
                asyncio.create_task(self._notify(f"⚠️ 嘉立创登录请求被拒绝（HTTP {response.status}）。请确认账号登录状态。"))
        except Exception as exc: self.last_error=f"解析接口响应失败：{type(exc).__name__}: {exc}"

    async def _capture_token(self):
        if self.get_saved_token(): return True
        for page in (self.context.pages if self.context else []):
            if page.is_closed(): continue
            try:
                found=await page.evaluate("""() => {
                    const keys=['X-JLC-AccessToken','x-jlc-accesstoken','accessToken','access_token','token'];
                    for(const key of keys){try{const v=localStorage.getItem(key)||sessionStorage.getItem(key);if(v)return v.replace(/^Bearer\\s+/i,'');}catch(_){}}
                    return '';
                }""")
                if found: self._save_token(found); self.last_event="已从 Windows 浏览器网页存储捕获 Token"; return True
            except Exception: continue
        return False

    async def start(self):
        async with self._lock:
            if not self.cdp_url: raise RuntimeError("未配置 windows_cdp_url，请填写 http://Windows的Tailscale_IP:9222")
            if self.playwright and self.browser and self.browser.is_connected():
                await self._capture_token(); return "已连接 Windows 浏览器，正在监听嘉立创登录请求。"
            try: from playwright.async_api import async_playwright
            except ImportError as exc: raise RuntimeError("AstrBot 环境缺少 Playwright，请安装插件 requirements.txt 依赖。") from exc
            self.last_error=""; self.last_event="正在通过 Tailscale 连接 Windows 浏览器"
            self.playwright=await async_playwright().start()
            try:
                self.browser=await self.playwright.chromium.connect_over_cdp(self.cdp_url,timeout=15000)
                if not self.browser.contexts: raise RuntimeError("Windows 浏览器没有可用上下文，请重新运行启动脚本。")
                self.context=self.browser.contexts[0]; self.context.on("page",self._attach_page)
                for p in self.context.pages: self._attach_page(p)
                pages=self.context.pages
                self.page=next((p for p in pages if "jlc.com" in (urlsplit(p.url).netloc or "")),pages[0] if pages else None)
                if self.page is None: self.page=await self.context.new_page()
                if self.page.url=="about:blank": await self.page.goto("https://www.jlc.com/",wait_until="domcontentloaded",timeout=60000)
                await self._capture_token(); self.last_event="Windows 浏览器已连接，等待嘉立创登录请求"
                return "已成功连接 Windows 浏览器，Token 请求监听已启动。"
            except Exception as exc:
                self.last_error=f"{type(exc).__name__}: {exc}"; self.last_event="连接 Windows 浏览器失败"
                await self.close()
                raise RuntimeError(f"{self.last_error}。请确认 Windows 启动脚本、Tailscale 和 windows_cdp_url 配置。") from exc

    def status_text(self):
        connected=bool(self.browser and self.browser.is_connected()); token=bool(self.get_saved_token())
        return (f"浏览器：{'Windows 已连接' if connected else '未连接'}\n调试地址：{self.cdp_url or '未配置'}\n"
                f"Token：{'已保存' if token else '未捕获'}\n捕获次数：{self.capture_count}\n"
                f"最近状态：{self.last_event}\n最近错误：{self.last_error or '无'}")

    async def close(self):
        # 只断开客户端，不关闭 Windows 上的浏览器。
        self.context=self.page=self.browser=None
        if self.playwright:
            try: await self.playwright.stop()
            except Exception: pass
        self.playwright=None

    async def logout(self):
        await self.close()
        try: self.token_file.unlink(missing_ok=True)
        except OSError: pass
        self.token=None; self.last_event="已清除本地 Token；Windows 浏览器不会被关闭"
        self.last_error=""; self.capture_count=0
