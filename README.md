# 可锐 HTTPS 与证书监测

从 GitHub 标准 Linux 云端运行器检查公开网站，无需个人电脑开机。

- 每天北京时间 09:17（UTC 01:17）运行，避开整点调度高峰；GitHub 调度可能延迟，不承诺准点或实时告警。
- 校验 `creahub.art` 与 `www.creahub.art` 的证书信任、域名匹配和有效期。
- 检查主域名登录页返回 200、健康接口返回 `status=ok`，以及 `www` 跳转至主域名登录页。
- 失败间隔 20 秒复测，只有连续两次异常才进入告警判断。
- 证书不超过 7 天预警，不超过 1 天升级；新异常、加重或恢复后复发才触发告警。
- 正常、恢复、正常续期和同一异常持续都不发送消息。

新告警会使工作流失败，由 GitHub 原生通知发送邮件及站内通知。账户通知设置须开启 Actions 的邮件通知，并选择“仅失败的工作流”。已知异常持续时工作流可成功，真实状态以运行摘要及 `.monitor-state.json` 为准。

`.monitor-state.json` 保存异常去重状态；异常改变或每天首次检查时提交检查记录。工作流只接受定时及手动触发，状态提交不会重复触发运行。日常检查记录也避免仓库长期无活动导致定时任务自动停用。

公开仓库使用标准 GitHub 托管运行器免费。本项目不使用收费的大型运行器、不上传 Actions 构建产物或使用缓存，不需要额外 API 密钥。临时 `GITHUB_TOKEN` 仅用于读写本监测仓库的状态文件。不要把项目改为私有后仍假定免费。

本仓库只包含公开域名的监测逻辑，不包含可锐应用源码、生产凭据、素材或个人通知邮箱。监测不修改 DNS、证书或网站服务；证书自动续期仍由相应证书管理服务完成。

本地验证：

```sh
python3 -m unittest -v
python3 monitor.py
```

GitHub 自身故障或调度停止可能同时影响检查和告警；本方案不是有 SLA 的专用监控服务。

官方说明：[公共仓库运行器计费](https://docs.github.com/en/billing/concepts/product-billing/github-actions)、[定时任务调度限制](https://docs.github.com/en/actions/how-tos/troubleshoot-workflows)、[Actions 通知](https://docs.github.com/en/actions/concepts/workflows-and-actions/notifications-for-workflow-runs)。
