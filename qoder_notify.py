"""钉钉自定义机器人 Markdown 通知，仅使用标准库。"""
import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from qoder_signin import NoRedirect


class NotifyError(Exception):
    pass


def webhook_url(webhook, secret="", timestamp=None):
    try:
        url = urllib.parse.urlsplit(webhook.strip())
        if (url.scheme != "https" or url.hostname != "oapi.dingtalk.com"
                or url.port not in (None, 443) or url.username or url.password
                or url.path != "/robot/send" or url.fragment):
            raise ValueError()
        query = urllib.parse.parse_qsl(url.query, keep_blank_values=True)
        if not any(key == "access_token" and value for key, value in query):
            raise ValueError()
    except ValueError:
        raise NotifyError("DINGDING_WEBHOOK 必须为有效的钉钉 HTTPS 机器人地址") from None
    if secret:
        stamp = str(int(time.time() * 1000) if timestamp is None else timestamp)
        message = (stamp + "\n" + secret).encode("utf-8")
        sign = base64.b64encode(hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()).decode("ascii")
        query = [(key, value) for key, value in query if key not in ("timestamp", "sign")]
        query.extend([("timestamp", stamp), ("sign", sign)])
    return urllib.parse.urlunsplit((url.scheme, url.netloc, url.path, urllib.parse.urlencode(query), ""))


def send_dingtalk(webhook, secret, title, text):
    # 长账号列表保留开头的总览；限制消息体长度，避免钉钉拒绝过长消息。
    if len(text.encode("utf-8")) > 15000:
        text = text.encode("utf-8")[:14500].decode("utf-8", "ignore") + "\n\n账号详情已截断，请查看 Actions 日志。"
    payload = {"msgtype": "markdown", "markdown": {"title": title, "text": text}, "at": {"isAtAll": False}}
    request = urllib.request.Request(webhook_url(webhook, secret),
                                     data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=20) as response:
            if response.status != 200:
                raise NotifyError("钉钉通知 HTTP 请求失败")
            raw = response.read(65537)
    except urllib.error.HTTPError as exc:
        exc.close()
        raise NotifyError("钉钉通知 HTTP 请求失败") from None
    except (urllib.error.URLError, OSError, TimeoutError):
        raise NotifyError("钉钉通知网络连接失败或超时") from None
    try:
        if len(raw) > 65536:
            raise ValueError()
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError()
    except (ValueError, UnicodeError):
        raise NotifyError("钉钉通知响应格式错误") from None
    if data.get("errcode") != 0:
        # errmsg 可能包含 URL、签名等敏感信息，不写日志。
        raise NotifyError("钉钉拒绝消息，请检查机器人加签、关键词与安全设置")
