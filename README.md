# Qoder CN 每日签到 · GitHub Actions

由 GitHub Actions 每天依次为多个 Qoder CN 账号领取当前可领取的 Credits，并向钉钉发送结果汇总。无需自备服务器，Python 仅使用标准库。

## 上传到 GitHub

```text
.github/workflows/qoder-signin.yml  每日任务与手动触发
qoder_actions.py                   Secrets 解析、执行及通知汇总
qoder_signin.py                    账号校验、活动查询与领取
qoder_notify.py                    钉钉通知与加签
accounts.example.json              Secret JSON 格式示例，无真实凭据
README.md                          本说明
.gitignore                         凭据与临时文件排除规则
```

工作流必须位于仓库默认分支。请勿上传真实账号 token、WebHook 或密钥。

## 配置 Secrets

进入仓库 **Settings → Secrets and variables → Actions → New repository secret**：

| Secret | 内容 | 是否必填 |
|---|---|---|
| `QODER_ACCOUNTS` | 包含账号 token 的完整 JSON，见下例 | 是 |
| `DINGDING_WEBHOOK` | 钉钉自定义机器人完整 Webhook | 需要通知时必填 |
| `DINGDING_SECRET` | 机器人“加签”密钥，通常以 `SEC` 开头 | 启用加签时必填 |

`QODER_ACCOUNTS` 格式：

```json
{
  "accounts": [
    {"name": "账号一", "token": "账号一真实token", "enabled": true},
    {"name": "账号二", "token": "账号二真实token", "enabled": true}
  ]
}
```

使用已取得的本人 **Qoder CN access token**，不是模型 API Key 或 refresh token，可带 `Bearer ` 前缀。名称需唯一，按数组顺序执行，默认账号间隔 3 秒；`enabled: false` 可停用账号。直接将合法 JSON 保存到 Secrets，不需要 Base64 编码，也不使用 `token_env`。账号数据在运行时从 Secrets 读取并在内存中处理。

钉钉 Webhook 格式：

```text
https://oapi.dingtalk.com/robot/send?access_token=你的机器人token
```

如果机器人启用了“加签”，同步填写 `DINGDING_SECRET`，脚本自动生成时间戳及签名。若启用了关键词安全设置，可设置 `Qoder` 或 `签到`，消息包含这些词。机器人入口及可用性以当前组织和钉钉界面为准。

未配置 Webhook 时仍执行签到，日志显示 `NOTIFY_SKIPPED`。

## 手动验证

进入 **Actions → Qoder CN Daily Sign-in → Run workflow**：

1. 选择默认分支，`action` 选择 **`status`**，只查询活动并发送通知，不领取。
2. 检查各账号结果，末尾的 `NOTIFIED` 表示钉钉接口确认发送成功；同时检查群内消息。
3. 再次运行，选择 **`run`**，执行实际领取。

看不到工作流时，请确认 YAML 已上传到默认分支，仓库 Actions 已启用。Fork 的仓库也需要自行启用工作流并配置自己的 Secrets。

## 每日执行时间

默认每天**北京时间 10:05**触发，对应 UTC `02:05`：

```yaml
on:
  schedule:
    - cron: '5 2 * * *'
```

修改 `.github/workflows/qoder-signin.yml` 中的 cron 可调整时间，例如北京时间 10:15 对应 `15 2 * * *`。手动和定时任务共用 concurrency 分组，避免同时签到。

GitHub 定时调度可能延迟，高负载时可能丢弃任务，不保证精确到分钟。公开仓库连续 60 天无活动时，计划工作流会自动停用，需要检查并重新启用。本项目不会自动提交代码维持仓库活跃。任务上限为 60 分钟；Runner 无法启动、拉取代码失败、平台取消或超时时，脚本无法保证发送钉钉消息。

参考：[GitHub schedule 官方说明](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)。

## 签到结果与通知

每轮向钉钉发送一次汇总，包括账号总数、失败数、各账号结果、已知的本轮新增 Credits 和 Actions 日志链接。单个账号失败后继续处理其他账号；token 和原始接口响应不会写入通知。

| 结果 | 含义 |
|---|---|
| `CLAIMED` | 领取成功 |
| `ALREADY` | 当前周期已经领取 |
| `INACTIVE` | 当前没有可领取活动 |
| `PENDING` | 有活动但当前不可领取，需要检查 |
| `AUTH_REJECTED` | token 失效或被拒绝，更新 Secret |
| `FORBIDDEN` | 服务端拒绝访问，检查账号资格或认证要求 |
| `NETWORK` | 网络失败或超时，有限重试后仍未成功 |
| `NOTIFIED` | 钉钉接口确认发送成功 |
| `NOTIFY_ERROR` | 检查机器人 Webhook、加签、关键词、安全设置及网络 |
| `CONFIG_ERROR` | 账号 Secret 缺失、JSON 格式错误或账号配置不合法 |

`ALREADY`、`INACTIVE` 属于正常结果。账号或已配置的通知发送失败，会使当前 Actions run 失败。配置错误时也会尝试发送通知。退出码 `0` 表示处理正常，`1` 表示账号或通知失败，`2` 表示配置或运行错误。

奖励数额、有效期和活动窗口由 Qoder CN 服务端决定，不保证固定 100 Credits。网络错误、429 和 5xx 最多重试 3 次；401、403 及业务拒绝不重试。重复运行先查询领取状态；服务端确认的幂等重放不计入本轮新增积分。

## 更新 token

token 过期后，在仓库 **Settings → Secrets and variables → Actions** 编辑 `QODER_ACCOUNTS`，替换对应账号的 token，保留其他账号，再手动运行 `status` 验证。无需提交真实配置到仓库或修改工作流；脚本不自动登录或续期。

