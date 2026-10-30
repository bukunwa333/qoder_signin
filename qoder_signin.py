"""GitHub Actions 使用的 Qoder CN 多账号签到核心，仅使用标准库。
"""
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://openapi.qoder.com.cn"
CN = timezone(timedelta(hours=8))
SUCCESS = {"CLAIMED", "ALREADY", "INACTIVE", "OK"}



class ConfigError(Exception):
    pass


class ApiError(Exception):
    def __init__(self, result, message):
        self.result = result
        super().__init__(message)


def clean_token(value):
    if not isinstance(value, str):
        raise ConfigError("token 必须为字符串")
    value = value.strip()
    if value.lower().startswith("bearer "):
        value = value[7:].strip()
    if not re.fullmatch(r"[A-Za-z0-9._~+/=-]{1,32768}", value):
        raise ConfigError("token 为空或包含非法字符")
    return value


def validate_config(data):
    if not isinstance(data, dict) or not isinstance(data.get("accounts"), list):
        raise ConfigError("QODER_ACCOUNTS 必须包含 accounts 数组")
    names = set()
    for row in data["accounts"]:
        if not isinstance(row, dict):
            raise ConfigError("每个账号必须是 JSON 对象")
        name = row.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 80 or any(ord(c) < 32 for c in name):
            raise ConfigError("账号名称必须为 1–80 个可打印字符")
        if name in names:
            raise ConfigError("账号名称不能重复")
        names.add(name)
        if not isinstance(row.get("enabled", True), bool):
            raise ConfigError("enabled 必须为布尔值")
        if "token_env" in row:
            raise ConfigError("QODER_ACCOUNTS 请直接填写 token，不使用 token_env")
        clean_token(row.get("token"))
    if not any(row.get("enabled", True) for row in data["accounts"]):
        raise ConfigError("QODER_ACCOUNTS 中没有已启用的账号")
    return data


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Api:
    def __init__(self, token, timeout=20, retries=3):
        self.token, self.timeout, self.retries = token, timeout, retries
        self.opener = urllib.request.build_opener(NoRedirect())

    def call(self, path, method="GET"):
        for attempt in range(self.retries + 1):
            request = urllib.request.Request(
                BASE_URL + path, method=method,
                data=b"" if method == "POST" else None,
                headers={"Accept": "application/json", "User-Agent": "Qoder/claim",
                         "Cosy-ClientType": "10", "Authorization": "Bearer " + self.token})
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    code, raw = response.status, response.read(1048577)
            except urllib.error.HTTPError as exc:
                code, raw = exc.code, b""
                exc.close()
            except (urllib.error.URLError, OSError, TimeoutError):
                code, raw = 0, b""
            if (code == 0 or code == 429 or 500 <= code < 600) and attempt < self.retries:
                time.sleep((5, 15, 30)[attempt])
                continue
            if code == 401:
                raise ApiError("AUTH_REJECTED", "token 已失效，请重新登录客户端后更新 token")
            if code == 403:
                raise ApiError("FORBIDDEN", "服务端拒绝访问，请检查账号资格或认证要求")
            if code == 0:
                raise ApiError("NETWORK", "网络连接失败或请求超时")
            if code != 200:
                raise ApiError("ERROR", "接口请求失败，HTTP %s" % code)
            if len(raw) > 1048576:
                raise ApiError("ERROR", "接口响应过大")
            try:
                body = json.loads(raw)
            except (ValueError, UnicodeError):
                raise ApiError("ERROR", "接口返回非 JSON 数据") from None
            if not isinstance(body, dict):
                raise ApiError("ERROR", "接口响应格式不符")
            # 两种响应形式均兼容；错误信封不能被误判为无活动。
            if isinstance(body.get("data"), dict):
                body = body["data"]
            return body

    def campaigns(self):
        data = self.call("/sash/api/v1/me/campaigns")
        rows = data.get("campaigns")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ApiError("ERROR", "活动列表格式不符，接口可能已变更")
        return rows

    def claim(self, campaign_id):
        if not isinstance(campaign_id, str) or not campaign_id:
            raise ApiError("ERROR", "活动缺少 campaignId")
        return self.call("/sash/api/v1/me/campaigns/%s/claim" % urllib.parse.quote(campaign_id, safe=""), "POST")


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def amount(row):
    benefit = row.get("benefit")
    value = benefit.get("amount") if isinstance(benefit, dict) else None
    return value if number(value) and value >= 0 else None


def active(row, now):
    for key in ("startAt", "endAt"):
        if row.get(key) is not None and not number(row[key]):
            raise ApiError("ERROR", "活动时间格式不符")
    return (row.get("startAt") is None or now >= row["startAt"]) and (row.get("endAt") is None or now < row["endAt"])


def process_account(api, action, dry_run=False):
    rows = api.campaigns()
    now = time.time()
    eligible = [r for r in rows if r.get("actionType") == "CLAIM_BENEFIT" and active(r, now)]
    todo = [r for r in eligible if r.get("claimStatus") == "CLAIMABLE"]
    done = [r for r in eligible if r.get("claimStatus") == "CLAIMED"]
    if action == "status" or dry_run:
        return {"result": "DRY_RUN" if dry_run else "OK", "report": "查询完成，可领取 %s 项" % len(todo),
                "claimable": len(todo), "already_claimed": len(done)}
    if not todo:
        if done and len(done) == len(eligible):
            return {"result": "ALREADY", "report": "当前周期已领取"}
        if eligible:
            return {"result": "PENDING", "report": "活动存在，但有活动当前不可领取"}
        return {"result": "INACTIVE", "report": "当前没有可领取的活动"}
    claimed, errors = [], []
    for row in todo:
        try:
            data = api.claim(row.get("campaignId"))
            if data.get("status") != "CLAIMED":
                raise ApiError("ERROR", "领取未返回 CLAIMED，请查询状态确认")
            value = amount(data)
            claimed.append({"credits": amount(row) if value is None else value,
                            "replayed": data.get("replayed") is True})
        except ApiError as exc:
            errors.append({"result": exc.result, "report": str(exc)})
            if exc.result in ("AUTH_REJECTED", "FORBIDDEN"):
                break
    # replayed 仅代表服务端确认已领，不计入本轮新到账积分。
    values = [r["credits"] for r in claimed if not r["replayed"] and r["credits"] is not None]
    result = errors[0]["result"] if errors else "CLAIMED"
    return {"result": result, "report": "领取完成" if not errors else "部分或全部活动领取失败",
            "claimed_count": len(claimed), "credits": sum(values) if values else None,
            "replayed_count": sum(r["replayed"] for r in claimed), "errors": errors}


def emit(data, secrets=()):
    data = dict(data, time=datetime.now(CN).isoformat(timespec="seconds"))
    text = json.dumps(data, ensure_ascii=False)
    for secret in sorted(set(secrets), key=len, reverse=True):
        if secret:
            text = text.replace(secret, "[REDACTED]")
    print(text, flush=True)


def run_accounts(action, data, emit_fn=emit):
    if action not in ("run", "status"):
        raise ConfigError("仅支持 run 或 status")
    validate_config(data)
    rows = [row for row in data["accounts"] if row.get("enabled", True)]
    secrets = [value for row in data["accounts"] for value in (row["token"], clean_token(row["token"]))]
    counts = Counter()
    failed = 0
    for index, row in enumerate(rows):
        try:
            out = process_account(Api(clean_token(row["token"])), action, False)
        except ApiError as exc:
            out = {"result": exc.result, "report": str(exc)}
        except Exception:
            out = {"result": "ERROR", "report": "账号处理异常，请检查配置或更新脚本"}
        ok = out["result"] in SUCCESS
        counts[out["result"]] += 1
        failed += not ok
        emit_fn(dict(out, account=row["name"], needs_attention=not ok), secrets)
        if index < len(rows) - 1:
            time.sleep(3)
    emit_fn({"result": "SUMMARY", "total": len(rows), "failed": failed, "counts": dict(counts), "needs_attention": failed > 0}, secrets)
    return 1 if failed else 0
