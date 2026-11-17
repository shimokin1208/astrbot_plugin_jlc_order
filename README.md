# astrbot_plugin_jlc_order

AstrBot 插件：定时查询嘉立创（JLC）PCB/FPC 订单进度，并推送到指定 QQ 群或私聊。

## 功能

- 按可配置间隔（默认 40 分钟）自动查询待发货订单
- 支持「仅状态变化时推送」或「每次都推送」
- 所有关键参数均可在 AstrBot WebUI 插件配置中修改
- 提供手动查询指令：`/jlc订单`
- 提供状态查看指令：`/jlc状态`

## 安装

1. 在 AstrBot 插件目录下克隆本仓库：

```bash
cd AstrBot/data/plugins
git clone https://github.com/shimokin1208/astrbot_plugin_jlc_order.git
```

2. 安装依赖：

```bash
pip install -r astrbot_plugin_jlc_order/requirements.txt
```

3. 在 AstrBot WebUI → 插件 中重载本插件。

4. 填写配置（见下方）。

## 配置项说明

在 WebUI 插件设置中填写：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `enabled` | 是否启用定时查询 | true |
| `access_token` | 嘉立创 `x-jlc-accesstoken` | 空 |
| `interval_minutes` | 轮询间隔（分钟） | 40 |
| `notify_group_id` | 推送目标 QQ 群号 | 空 |
| `notify_user_id` | 推送目标 QQ 号（私聊备用） | 空 |
| `order_status` | 查询状态，一般保持 `waitSend` | waitSend |
| `only_on_change` | 仅状态变化时推送 | true |
| `include_empty` | 无订单时是否也通知 | false |

**推送优先级**：优先使用 `notify_group_id`，为空时才使用 `notify_user_id`。

## 如何获取 AccessToken（推荐）

1. 手机或电脑浏览器打开并登录：https://m.jlc.com
2. 按 F12 打开开发者工具 → Network（网络）
3. 刷新页面或进入「我的订单」
4. 随便点开一个对 `m.jlc.com` 的请求
5. 在 Request Headers 里找到 `x-jlc-accesstoken`（或 `X-JLC-AccessToken`）
6. 复制其完整值，粘贴到插件配置的 `access_token` 中

> Token 一般有效期较长（数周到数月）。失效后插件会推送错误提示，重新抓一次即可。

### 控制台一键提取（可选）

在已登录的 `m.jlc.com` 页面打开控制台，粘贴执行：

```javascript
(() => {
  const keys = ['X-JLC-AccessToken', 'x-jlc-accesstoken', 'accessToken', 'token'];
  for (const k of keys) {
    const v = localStorage.getItem(k);
    if (v) {
      const t = v.replace(/^Bearer\s+/i, '');
      console.log(t);
      try { navigator.clipboard.writeText(t); console.log('已复制到剪贴板'); } catch(e) {}
      return t;
    }
  }
  console.log('未找到 Token，请确认已登录');
})();
```

## 指令

| 指令 | 说明 |
|------|------|
| `/jlc订单` 或 `/嘉立创订单` | 立即查询一次并推送/回复结果 |
| `/jlc状态` | 查看插件运行状态与配置摘要 |

## 注意事项

- 本插件只做**查询自己的订单**，不进行下单、支付等写操作。
- 建议间隔 ≥ 30 分钟，降低风控可能。
- Token 属于敏感信息，请勿泄露到公开地方。
- 推送依赖 AstrBot 的 QQ 适配器（aiocqhttp 等）支持主动消息。

## 开发计划

- [ ] 可选 Playwright 会话模式（首次登录后自动维护）
- [ ] 更精细的订单字段解析与物流单号展示
- [ ] 多账号 Token 支持

## License

MIT
