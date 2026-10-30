#!/usr/bin/env python3
"""GitHub Actions 入口：从 Secrets 读取账号，签到后汇总发送钉钉通知。"""
import argparse
from datetime import datetime
import json
import os
import re

import qoder_signin as q
from qoder_notify import NotifyError, send_dingtalk


def safe_text(text, secrets):
    for secret in sorted(set(secrets), key=len, reverse=True):
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text


def markdown_text(text):
    text = " ".join(str(text).split())
    return re.sub(r"([\\`*_{}\[\]()<>#!|])", r"\\\1", text)


def notification(rows, fatal, action):
    summary = next((row for row in rows if row.get("result") == "SUMMARY"), {})
    needs_attention = bool(fatal or summary.get("failed"))
    title = "Qoder CN 签到需要处理" if needs_attention else "Qoder CN 签到完成"
    if action == "status":
        title = "Qoder CN 状态查询" + ("需要处理" if needs_attention else "完成")
    lines = ["### " + title, "", "北京时间：" + datetime.now(q.CN).strftime("%Y-%m-%d %H:%M:%S"), ""]
    if fatal:
        lines.append("配置或运行错误：" + markdown_text(fatal))
    else:
        lines.append("账号总数：%s；失败：%s" % (summary.get("total", 0), summary.get("failed", 0)))
    for row in rows:
        if "account" not in row:
            continue
        detail = "- **%s**：%s — %s" % (markdown_text(row["account"]), markdown_text(row["result"]), markdown_text(row.get("report", "")))
        if row.get("credits") is not None:
            detail += "；本轮新增 %s Credits" % row["credits"]
        for error in row.get("errors", []):
            detail += "；" + markdown_text(error.get("report", ""))
        lines.extend(["", detail])
    repo, run = os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("GITHUB_RUN_ID", "")
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) and run.isdigit():
        lines.extend(["", "[查看 Actions 日志](https://github.com/%s/actions/runs/%s)" % (repo, run)])
    return title, "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("run", "status"), default="run")
    args = parser.parse_args(argv)
    webhook = os.environ.get("DINGDING_WEBHOOK", "").strip()
    secret = os.environ.get("DINGDING_SECRET", "").strip()
    secrets = [webhook, secret]
    rows, fatal = [], ""
    code = 2
    try:
        raw = os.environ.get("QODER_ACCOUNTS", "").strip()
        if not raw:
            raise q.ConfigError("请在仓库 Secrets 中设置 QODER_ACCOUNTS（包含 accounts 数组的 JSON）")
        try:
            data = json.loads(raw)
        except ValueError:
            raise q.ConfigError("QODER_ACCOUNTS 不是有效的 JSON") from None
        # 在任何日志输出前注册所有 token；不输出原始 JSON 或服务端响应。
        if isinstance(data, dict) and isinstance(data.get("accounts"), list):
            for row in data["accounts"]:
                if isinstance(row, dict) and isinstance(row.get("token"), str):
                    secrets.append(row["token"])
                    try:
                        secrets.append(q.clean_token(row["token"]))
                    except q.ConfigError:
                        pass
        def collect(out, account_secrets=()):
            cleaned = json.loads(safe_text(json.dumps(out, ensure_ascii=False), secrets + list(account_secrets)))
            rows.append(cleaned)
            q.emit(cleaned)
        code = q.run_accounts(args.action, q.validate_config(data), emit_fn=collect)
    except q.ConfigError as exc:
        fatal = safe_text(str(exc), secrets)
    except Exception:
        fatal = "签到运行异常，请查看项目配置或更新脚本"
    if fatal:
        q.emit({"result": "CONFIG_ERROR" if code == 2 else "ERROR", "report": fatal, "needs_attention": True})
    title, text = notification(rows, fatal, args.action)
    if webhook:
        try:
            send_dingtalk(webhook, secret, title, safe_text(text, secrets))
            q.emit({"result": "NOTIFIED", "report": "钉钉通知已发送"})
        except NotifyError as exc:
            q.emit({"result": "NOTIFY_ERROR", "report": str(exc), "needs_attention": True})
            return code or 1
        except Exception:
            q.emit({"result": "NOTIFY_ERROR", "report": "钉钉通知发生异常", "needs_attention": True})
            return code or 1
    else:
        q.emit({"result": "NOTIFY_SKIPPED", "report": "未配置 DINGDING_WEBHOOK，已跳过通知"})
    return code


if __name__ == "__main__":
    raise SystemExit(main())
