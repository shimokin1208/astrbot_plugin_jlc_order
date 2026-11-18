package com.shimokin.jlclogin

import android.app.Activity
import android.os.Bundle
import android.graphics.Color
import android.net.Uri
import android.view.ViewGroup
import android.webkit.*
import android.widget.*
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

class MainActivity : Activity() {
    private lateinit var web: WebView
    private lateinit var status: TextView
    private val client = OkHttpClient.Builder().callTimeout(12, TimeUnit.SECONDS).build()
    private var server = ""
    private var pairKey = ""
    private val sent = AtomicBoolean(false)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        buildUi()
        handlePairIntent(intent)
        if (server.isEmpty()) status.text = "请从 AstrBot 私聊收到的登录配对链接打开本应用。"
        web.loadUrl("https://m.jlc.com/")
    }

    override fun onNewIntent(intent: android.content.Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handlePairIntent(intent)
    }

    private fun buildUi() {
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setBackgroundColor(Color.WHITE) }
        val header = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(16, 12, 16, 12)
            setBackgroundColor(Color.rgb(245, 247, 250))
        }
        val title = TextView(this).apply { text = "嘉立创登录助手"; textSize = 18f; setTextColor(Color.BLACK) }
        status = TextView(this).apply { text = "等待登录配对链接…"; textSize = 13f; setTextColor(Color.DKGRAY); setPadding(0, 8, 0, 0) }
        val reload = Button(this).apply { text = "刷新页面"; setOnClickListener { web.reload() } }
        header.addView(title)
        header.addView(status)
        header.addView(reload)
        web = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.useWideViewPort = true
            settings.loadWithOverviewMode = true
            webViewClient = object : WebViewClient() {
                override fun shouldInterceptRequest(view: WebView?, request: WebResourceRequest?): WebResourceResponse? {
                    val req = request ?: return super.shouldInterceptRequest(view, request)
                    val host = req.url.host.orEmpty()
                    if (host == "m.jlc.com" || host.endsWith(".jlc.com")) {
                        val token = req.requestHeaders.entries.firstOrNull {
                            it.key.equals("x-jlc-accesstoken", ignoreCase = true)
                        }?.value
                        if (!token.isNullOrBlank()) submitToken(token)
                    }
                    return super.shouldInterceptRequest(view, request)
                }
                override fun onPageFinished(view: WebView?, url: String?) {
                    super.onPageFinished(view, url)
                    if (url?.startsWith("https://m.jlc.com") == true) pollPageStorage()
                }
            }
        }
        root.addView(header, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        root.addView(web, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        setContentView(root)
    }

    private fun handlePairIntent(intent: android.content.Intent?) {
        val uri = intent?.data ?: return
        if (uri.scheme != "jlcorder" || uri.host != "login") return
        val incomingServer = uri.getQueryParameter("server").orEmpty().trimEnd('/')
        val incomingKey = uri.getQueryParameter("key").orEmpty()
        val parsed = Uri.parse(incomingServer)
        val octets = parsed.host.orEmpty().split(".")
        val second = octets.getOrNull(1)?.toIntOrNull() ?: -1
        val validIp = octets.size == 4 && octets[0] == "100" && second in 64..127 &&
            octets.drop(2).all { (it.toIntOrNull() ?: -1) in 0..255 }
        if (parsed.scheme != "http" || !validIp || parsed.port != 18763 || incomingKey.length < 30) {
            status.text = "配对链接无效：仅接受 Tailscale 私网地址和有效的一次性密钥。"
            return
        }
        server = incomingServer
        pairKey = incomingKey
        sent.set(false)
        status.text = "已连接到小主机。请在下方登录嘉立创并完成验证。"
    }

    private fun pollPageStorage() {
        val js = """
            (() => {
              const keys = ['X-JLC-AccessToken','x-jlc-accesstoken','accessToken','access_token'];
              for (const k of keys) {
                try {
                  const v = localStorage.getItem(k) || sessionStorage.getItem(k);
                  if (v) return v.replace(/^Bearer\\s+/i, '');
                } catch(e) {}
              }
              return '';
            })();
        """.trimIndent()
        web.evaluateJavascript(js) { value ->
            val token = value?.trim()?.trim('"')?.takeIf { it.length >= 8 && it != "null" }
            if (token != null) submitToken(token)
        }
    }

    private fun submitToken(raw: String) {
        if (server.isEmpty() || pairKey.isEmpty() || sent.get()) return
        val token = raw.removePrefix("Bearer ").trim()
        if (token.length !in 8..8192 || token.any { it.code !in 33..126 }) return
        if (!sent.compareAndSet(false, true)) return
        runOnUiThread { status.text = "已捕获登录凭证，正在发送到小主机…" }
        val body = JSONObject().put("token", token).toString().toRequestBody("application/json; charset=utf-8".toMediaType())
        val request = Request.Builder().url("$server/token?key=${Uri.encode(pairKey)}").post(body).build()
        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                sent.set(false)
                runOnUiThread { status.text = "发送失败：请确认手机 Tailscale 在线后重试。" }
            }
            override fun onResponse(call: Call, response: Response) {
                response.use {
                    val ok = it.isSuccessful
                    runOnUiThread {
                        status.text = if (ok) "登录成功！凭证已发送并保存。可以关闭本应用。"
                        else {
                            sent.set(false)
                            "小主机拒绝了凭证（HTTP ${it.code}），请重新向机器人申请登录链接。"
                        }
                    }
                }
            }
        })
    }

    override fun onDestroy() {
        web.destroy()
        super.onDestroy()
    }
}
