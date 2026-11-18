import asyncio
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.core.message.message_event_result import MessageChain
from astrbot.api.message_components import Plain

from .jlc_login import JlcWebLogin


ORDER_LIST_URL = "https://m.jlc.com/api/overseas-pcb-order/order/getOrderPageList"


@register(
    "astrbot_plugin_jlc_order",
    "shimokin1208",
    "定时查询嘉立创 PCB/FPC 订单进度并推送到 QQ",
    "1.1.0",
)
class JlcOrderPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._last_snapshot_hash: Optional[str] = None
        self._admin_platform_id: Optional[str] = None
        # 使用 AstrBot 提供的绝对插件数据目录，并兼容迁移旧版相对路径数据。
        legacy_dir = (
            Path(__file__).resolve().parents[2]
            / "plugins_data"
            / "astrbot_plugin_jlc_order"
        )
        self._data_dir = StarTools.get_data_dir("astrbot_plugin_jlc_order")
        self._data_dir.mkdir(parents=True, exist_ok=True)
        if legacy_dir.exists() and legacy_dir.resolve() != self._data_dir.resolve():
            for item in legacy_dir.iterdir():
                target = self._data_dir / item.name
                if not target.exists():
                    try:
                        shutil.move(str(item), str(target))
                    except OSError as e:
                        logger.warning(f"[jlc_order] 迁移旧数据失败 ({item}): {e}")
            try:
                legacy_dir.rmdir()
            except OSError:
                pass
        self._state_file = self._data_dir / "last_state.json"
        self._login = JlcWebLogin(self._data_dir, self.config.get("windows_cdp_url", ""))
        self._login.notify_callback = self._notify_admin
        self._last_error_notified = ""
        self._load_state()

    def _load_state(self):
        if self._state_file.exists():
            try:
                data = json.loads(self._state_file.read_text(encoding="utf-8-sig"))
                self._last_snapshot_hash = data.get("hash")
                self._admin_platform_id = str(data.get("platform_id") or "").strip() or None
            except Exception as e:
                logger.warning(f"[jlc_order] 读取状态文件失败: {e}")

    def _save_state(self, snapshot_hash: str):
        try:
            self._state_file.write_text(
                json.dumps(
                    {"hash": snapshot_hash, "platform_id": self._admin_platform_id},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            self._last_snapshot_hash = snapshot_hash
        except Exception as e:
            logger.warning(f"[jlc_order] 保存状态文件失败: {e}")

    def _remember_platform(self, event: AstrMessageEvent):
        """记住管理员当前使用的平台实例 ID，供后台通知复用。"""
        if not self._login_admin(event):
            return
        try:
            platform_id = str(event.get_platform_id() or "").strip()
        except Exception:
            platform_id = ""
        if platform_id:
            self._admin_platform_id = platform_id
            try:
                self._state_file.parent.mkdir(parents=True, exist_ok=True)
                self._state_file.write_text(
                    json.dumps(
                        {
                            "hash": self._last_snapshot_hash,
                            "platform_id": self._admin_platform_id,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            except Exception as e:
                logger.warning(f"[jlc_order] 保存平台实例信息失败: {e}")

    async def initialize(self):
        """插件加载后启动后台轮询任务"""
        if self.config.get("enabled", True):
            self._stop_event.clear()
            self._task = asyncio.create_task(self._poll_loop())
            logger.info("[jlc_order] 定时查询任务已启动")
        else:
            logger.info("[jlc_order] 插件已加载，但定时查询未启用")

    async def terminate(self):
        """插件卸载/停用时停止任务"""
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._login.close()
        logger.info("[jlc_order] 定时查询任务已停止")

    def _get_access_token(self) -> str:
        return self._login.get_saved_token()

    def _get_headers(self) -> Dict[str, str]:
        token = self._get_access_token()
        return {
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 13; Mobile) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Mobile Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "x-jlc-clienttype": "WEB",
            "x-jlc-accesstoken": token,
            "Referer": "https://m.jlc.com/",
            "Origin": "https://m.jlc.com",
        }

    async def _fetch_orders(self) -> List[Dict[str, Any]]:
        token = self._get_access_token()
        if not token:
            raise ValueError("未找到嘉立创网页登录凭证。请私聊机器人发送 /jlc登录，完成网页登录后再查询。")

        status = self.config.get("order_status") or "waitSend"
        params = {
            "current": 1,
            "pageSize": 50,
            "orderStatus": status,
            "source": "jlc_mobile_app",
            "clientType": "WEB",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                ORDER_LIST_URL,
                params=params,
                headers=self._get_headers(),
            )
            if resp.status_code in (401, 403):
                message = f"嘉立创订单接口认证失败（HTTP {resp.status_code}）。网页登录凭证可能已过期或无效，请发送 /jlc登录 重新登录。"
                await self._notify_admin("⚠️ " + message)
                raise RuntimeError(message)
            resp.raise_for_status()
            try:
                data = resp.json()
            except ValueError as exc:
                raise RuntimeError(f"嘉立创接口返回的不是有效 JSON（HTTP {resp.status_code}），可能登录状态异常或接口已变更。") from exc

        if not data.get("success", False) and data.get("code") not in (0, 200, "0", "200"):
            msg = data.get("message") or data.get("msg") or str(data)
            normalized = str(data.get("code", "")).lower()
            if normalized in ("401", "403", "unauthorized", "token_expired", "no_login"):
                message = f"嘉立创返回认证错误：{msg}。请发送 /jlc登录 重新登录。"
                await self._notify_admin("⚠️ " + message)
                raise RuntimeError(message)
            raise RuntimeError(f"嘉立创接口返回失败: {msg}")

        # 兼容不同返回结构
        result = data.get("data") or data.get("result") or {}
        if isinstance(result, list):
            return result
        records = result.get("records") or result.get("list") or result.get("rows") or []
        return records if isinstance(records, list) else []

    def _format_orders(self, orders: List[Dict[str, Any]]) -> str:
        if not orders:
            return "当前没有待发货的 PCB/FPC 订单。"

        lines = [f"📦 嘉立创订单进度（共 {len(orders)} 个）\n"]
        for i, o in enumerate(orders, 1):
            order_no = (
                o.get("orderNo")
                or o.get("orderCode")
                or o.get("code")
                or o.get("id")
                or "未知单号"
            )
            status = (
                o.get("orderStatusName")
                or o.get("statusName")
                or o.get("orderStatus")
                or o.get("status")
                or "未知状态"
            )
            progress = (
                o.get("produceProgress")
                or o.get("progress")
                or o.get("produceStatusName")
                or ""
            )
            product = (
                o.get("productName")
                or o.get("pcbName")
                or o.get("goodsName")
                or o.get("title")
                or ""
            )
            ship_time = (
                o.get("expectDeliveryTime")
                or o.get("deliveryTime")
                or o.get("planShipTime")
                or ""
            )

            block = [f"{i}. 单号: {order_no}"]
            if product:
                block.append(f"   型号: {product}")
            block.append(f"   状态: {status}")
            if progress:
                block.append(f"   进度: {progress}")
            if ship_time:
                block.append(f"   预计: {ship_time}")
            lines.append("\n".join(block))

        return "\n\n".join(lines)

    def _snapshot_hash(self, orders: List[Dict[str, Any]]) -> str:
        """用关键字段生成快照，用于判断是否有变化"""
        keys = []
        for o in orders:
            order_no = str(
                o.get("orderNo") or o.get("orderCode") or o.get("code") or o.get("id") or ""
            )
            status = str(
                o.get("orderStatusName")
                or o.get("statusName")
                or o.get("orderStatus")
                or o.get("status")
                or ""
            )
            progress = str(
                o.get("produceProgress")
                or o.get("progress")
                or o.get("produceStatusName")
                or ""
            )
            keys.append(f"{order_no}|{status}|{progress}")
        keys.sort()
        raw = "\n".join(keys)
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    async def _send_to_target(self, text: str):
        group_id = (self.config.get("notify_group_id") or "").strip()
        user_id = (self.config.get("notify_user_id") or "").strip()

        if not group_id and not user_id:
            logger.warning("[jlc_order] 未配置推送目标群号或 QQ 号，跳过发送")
            return False
        if not self._admin_platform_id:
            logger.error("[jlc_order] 未知平台实例 ID，无法发送订单通知；请先从目标平台发送一次插件指令")
            return False

        # 平台实例 ID 可能是 default 等自定义值，不能写死适配器类型名。
        if group_id:
            umo = f"{self._admin_platform_id}:GroupMessage:{group_id}"
        else:
            umo = f"{self._admin_platform_id}:FriendMessage:{user_id}"

        try:
            sent = await self.context.send_message(umo, MessageChain([Plain(text)]))
            if not sent:
                logger.error(f"[jlc_order] 平台未接受订单推送 ({umo})，send_message 返回 {sent!r}")
                return False
            logger.info(f"[jlc_order] 已推送到 {umo}")
            return True
        except Exception as e:
            logger.error(f"[jlc_order] 推送失败 ({umo}): {e}")
            return False

    async def _check_once(self, force: bool = False) -> str:
        """执行一次查询，返回可读文本"""
        orders = await self._fetch_orders()
        text = self._format_orders(orders)
        snap = self._snapshot_hash(orders)

        only_on_change = self.config.get("only_on_change", True)
        include_empty = self.config.get("include_empty", False)

        should_notify = force
        if not should_notify:
            if not orders and not include_empty:
                should_notify = False
            elif only_on_change:
                should_notify = snap != self._last_snapshot_hash
            else:
                should_notify = True

        if should_notify:
            sent = await self._send_to_target(text)
            if sent:
                self._save_state(snap)
            else:
                logger.warning("[jlc_order] 订单通知未送达，保留旧快照以便下次轮询重试")
        else:
            logger.info("[jlc_order] 订单无变化，跳过推送")

        return text

    async def _poll_loop(self):
        # 启动后稍等几秒再第一次查询，避免启动高峰
        await asyncio.sleep(5)
        while not self._stop_event.is_set():
            try:
                if self.config.get("enabled", True):
                    await self._check_once(force=False)
                    self._last_error_notified = ""
                else:
                    logger.debug("[jlc_order] 定时查询已禁用")
            except Exception as e:
                logger.error(f"[jlc_order] 轮询异常: {e}")
                err_text = str(e)
                if err_text != self._last_error_notified:
                    self._last_error_notified = err_text
                    try:
                        await self._notify_admin(f"⚠️ 嘉立创订单定时查询失败\n{err_text}")
                    except Exception:
                        pass

            interval = max(5, int(self.config.get("interval_minutes") or 40))
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval * 60)
                break
            except asyncio.TimeoutError:
                continue

    @filter.command("jlc订单", alias={"jlcorder", "嘉立创订单"})
    async def cmd_query(self, event: AstrMessageEvent):
        """立即查询一次嘉立创订单进度"""
        self._remember_platform(event)
        try:
            text = await self._check_once(force=True)
            yield event.plain_result(text)
        except Exception as e:
            logger.error(f"[jlc_order] 手动查询失败: {e}")
            yield event.plain_result(f"查询失败: {e}")

    @filter.command("jlc状态")
    async def cmd_status(self, event: AstrMessageEvent):
        """查看插件运行状态"""
        self._remember_platform(event)
        enabled = self.config.get("enabled", True)
        interval = self.config.get("interval_minutes", 40)
        group_id = self.config.get("notify_group_id") or "（未设置）"
        user_id = self.config.get("notify_user_id") or "（未设置）"
        has_token = bool(self._get_access_token())
        running = self._task is not None and not self._task.done()

        text = (
            f"嘉立创订单插件状态\n"
            f"启用: {'是' if enabled else '否'}\n"
            f"轮询任务: {'运行中' if running else '已停止'}\n"
            f"间隔: {interval} 分钟\n"
            f"推送群: {group_id}\n"
            f"推送私聊: {user_id}\n"
            f"Token: {'已配置' if has_token else '未配置'}\n"
            f"认证来源: {'网页登录' if self._login.get_saved_token() else '未登录'}\n"
            f"仅变化推送: {'是' if self.config.get('only_on_change', True) else '否'}"
        )
        yield event.plain_result(text)


    async def _notify_admin(self, message: str):
        admin_id = str(self.config.get("admin_user_id") or "").strip()
        if not admin_id:
            logger.warning("[jlc_order] 未配置 admin_user_id，无法向管理员推送登录结果")
            return False
        if not self._admin_platform_id:
            logger.error("[jlc_order] 未记录管理员的平台实例 ID，无法发送登录通知")
            return False

        umo = f"{self._admin_platform_id}:FriendMessage:{admin_id}"
        try:
            sent = await self.context.send_message(
                umo,
                MessageChain([Plain(message)]),
            )
            if not sent:
                logger.error(
                    f"[jlc_order] 管理员通知发送失败 ({umo})："
                    f"send_message 返回 {sent!r}"
                )
                return False
            logger.info(f"[jlc_order] 管理员通知已发送到 {umo}")
            return True
        except Exception as e:
            logger.error(f"[jlc_order] 管理员通知发送异常 ({umo}): {e}")
            return False

    def _login_admin(self, event: AstrMessageEvent) -> bool:
        admin_id = str(self.config.get("admin_user_id") or "").strip()
        sender_id = str(event.get_sender_id() or "").strip()
        return bool(admin_id and sender_id == admin_id)

    @filter.command("jlc登录")
    async def cmd_login(self, event: AstrMessageEvent):
        """连接 Windows 浏览器并监听嘉立创登录请求。"""
        if not self._login_admin(event):
            yield event.plain_result("无权发起登录。请先在插件配置中填写自己的 QQ 号（admin_user_id），并使用该账号操作。")
            return
        self._remember_platform(event)
        try:
            message = await self._login.start()
            yield event.plain_result(message + "\n\n请在 Windows 浏览器中完成嘉立创登录，并进入“我的订单”触发接口请求。\n完成后发送 /jlc登录状态 检查凭证是否已保存。")
        except Exception as e:
            logger.exception("[jlc_order] 连接 Windows 浏览器失败")
            yield event.plain_result(f"无法连接 Windows 浏览器：{e}")

    @filter.command("jlc登录状态")
    async def cmd_login_status(self, event: AstrMessageEvent):
        if not self._login_admin(event):
            yield event.plain_result("无权查看登录状态。")
            return
        self._remember_platform(event)
        yield event.plain_result("嘉立创网页登录状态\n" + self._login.status_text())

    @filter.command("jlc退出登录")
    async def cmd_logout(self, event: AstrMessageEvent):
        if not self._login_admin(event):
            yield event.plain_result("无权执行退出登录。")
            return
        self._remember_platform(event)
        await self._login.logout()
        yield event.plain_result("已清除插件保存的嘉立创登录凭证；Windows 浏览器不会被关闭。")
