#!/usr/bin/env python3
"""Run checks on GitHub, persist deduplication state, signal new alerts."""
import base64
import datetime as dt
import json
import os
import re
import urllib.error
import urllib.request

from monitor import run_checks, transition


def github_request(method, path, payload=None):
    token = os.environ["GH_TOKEN"]
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        "https://api.github.com/" + path, data=data, method=method,
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json", "User-Agent": "creahub-https-monitor"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def report(result, alert_keys):
    local_zone = dt.timezone(dt.timedelta(hours=8))
    checked = dt.datetime.fromisoformat(result["checked_at_utc"].replace("Z", "+00:00")).astimezone(local_zone)
    text = ["# 可锐 HTTPS 与证书检查", "", f'检查时间（北京时间）：{checked:%Y-%m-%d %H:%M:%S}', ""]
    if alert_keys:
        text.append("发现新的或加重的异常，已触发 GitHub 工作流失败通知。")
    elif result["status"] == "attention":
        text.append("已知异常持续，本次不重复通知；工作流成功只表示没有新告警。")
    else:
        text.append("所有检查正常，不发送通知。")
    text += ["", "| 检查 | 目标 | 结果 |", "|---|---|---|"]
    for check in result["checks"]:
        details = check.get("issue", "正常")
        if "days_remaining" in check:
            expires = dt.datetime.fromisoformat(check["expires_utc"]).astimezone(local_zone)
            details += f'；证书剩余 {check["days_remaining"]} 天；到期北京时间 {expires:%Y-%m-%d %H:%M:%S}'
        if "error" in check:
            details += "；" + check["error"].replace("|", "／").replace("\n", " ")
        text.append(f'| {check["kind"]} | {check["target"]} | {details} |')
    text += ["", "探测失败表示从 GitHub 云端连续两次检查失败，需结合源站和网络证据定位。"]
    return "\n".join(text) + "\n"


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("Invalid repository identity")
    path = f"repos/{repo}/contents/.monitor-state.json"
    sha = None
    try:
        stored = github_request("GET", path)
        sha = stored["sha"]
        previous = json.loads(base64.b64decode(stored["content"]))
        if previous.get("schema_version") != 1 or not isinstance(previous.get("active"), dict):
            raise ValueError("Invalid monitor state; do not silently reset alert history")
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        previous = {}

    result = run_checks()
    state, alert_keys = transition(previous, result["checks"], result["checked_at_utc"][:10])
    summary = report(result, alert_keys)
    print(summary)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(summary)

    # A daily checkpoint retains useful history and repository activity;
    # save immediately when anomaly state changes so alerts can be deduplicated.
    if state != previous:
        encoded = base64.b64encode((json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode()).decode()
        payload = {"message": "Record HTTPS monitor state", "content": encoded}
        if sha:
            payload["sha"] = sha
        github_request("PUT", path, payload)

    if alert_keys:
        print("::error title=可锐 HTTPS 监测异常::发现新的或加重的异常，请查看本次运行摘要。")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
