#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
电费自动监控脚本 - 增强版
功能：自动查询电费 -> 记录历史 -> 生成可视化仪表盘 -> 微信推送
设计为 Windows 定时任务调用，无 GUI、无交互、全自动
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import requests

# CI 模式：在 GitHub Actions 中运行时，跳过 GitHub API 上传（直接 commit）
CI_MODE = os.environ.get("CI_MODE", "").lower() in ("1", "true", "yes")

# 复用现有模块
from drjf_sign import extract_defaults_from_session, load_session_cookies, query_electricity
from login_requests import login_and_dump_session

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "notify_config.json"
SESSION_FILE = SCRIPT_DIR / "session_dump.json"
LOG_FILE = SCRIPT_DIR / "query_log.json"
DASHBOARD_FILE = SCRIPT_DIR / "dashboard.html"

DEFAULT_MERCHANT_ID = 113377
DEFAULT_RECH_MER_MAP_ID = 326

# 低电量/余额阈值
LOW_POWER_THRESHOLD = 20
LOW_BALANCE_THRESHOLD = 10


def log(msg: str):
    """带时间戳的日志输出"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        log(f"[ERROR] 配置文件不存在: {CONFIG_FILE}")
        sys.exit(1)
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def looks_like_query_success(result: dict) -> bool:
    code = str(result.get("code", "")).strip()
    typ = str(result.get("type", "").strip().upper())
    return typ == "S" and code == "30300000"


def looks_like_auth_expired(result: dict) -> bool:
    code = str(result.get("code", "")).strip()
    text = f"{code} {result.get('message', '')} {result.get('msg', '')}".lower()
    if code in {"401", "40001", "40101", "1001", "9001"}:
        return True
    for kw in ["未登录", "登录", "过期", "失效", "超时", "session", "token", "auth", "认证"]:
        if kw in text:
            return True
    return False


def do_query(config: dict) -> dict:
    """执行电费查询，自动处理登录"""
    username = config.get("username")
    password = config.get("password")
    cust_rech_no = config.get("custRechNo")
    timeout = config.get("timeout", 20)
    login_timeout = config.get("loginTimeout", 20)

    if not all([username, password, cust_rech_no]):
        return {"success": False, "error": "配置不完整"}

    need_login = False
    defaults = {}
    if SESSION_FILE.exists():
        try:
            defaults = extract_defaults_from_session(str(SESSION_FILE))
        except Exception:
            pass

    user_info_id = defaults.get("userInfoId")
    merchant_id = config.get("merchantId") or defaults.get("merchantId") or DEFAULT_MERCHANT_ID

    if not user_info_id:
        need_login = True

    # 尝试现有 session 查询
    if not need_login:
        try:
            with requests.Session() as session:
                load_session_cookies(session, str(SESSION_FILE))
                sessiontoken = defaults.get("sessiontoken", "")
                result = query_electricity(
                    session=session, merchant_id=merchant_id,
                    user_info_id=user_info_id,
                    rech_mer_map_id=config.get("rechMerMapId", DEFAULT_RECH_MER_MAP_ID),
                    cust_rech_no=cust_rech_no, sessiontoken=sessiontoken, timeout=timeout,
                )
                if looks_like_query_success(result):
                    return {"success": True, "data": result, "relogin": False}
                if looks_like_auth_expired(result):
                    need_login = True
                else:
                    return {"success": False, "error": f"查询异常: code={result.get('code')}", "raw": result}
        except requests.RequestException as e:
            log(f"[WARN] 查询请求异常: {e}，尝试重新登录")
            need_login = True

    # 重新登录后查询
    if need_login:
        log("[INFO] 会话过期，自动重新登录...")
        login_result = login_and_dump_session(
            username=username, password=password,
            timeout=login_timeout, session_file=str(SESSION_FILE),
        )
        if not login_result.get("success"):
            return {"success": False, "error": f"登录失败: {login_result.get('message', '')}"}

        defaults = {}
        if SESSION_FILE.exists():
            try:
                defaults = extract_defaults_from_session(str(SESSION_FILE))
            except Exception:
                pass

        user_info_id = defaults.get("userInfoId")
        merchant_id = config.get("merchantId") or defaults.get("merchantId") or DEFAULT_MERCHANT_ID

        if not user_info_id:
            return {"success": False, "error": "登录后无法获取 userInfoId"}

        with requests.Session() as session:
            load_session_cookies(session, str(SESSION_FILE))
            sessiontoken = defaults.get("sessiontoken", "")
            result = query_electricity(
                session=session, merchant_id=merchant_id,
                user_info_id=user_info_id,
                rech_mer_map_id=config.get("rechMerMapId", DEFAULT_RECH_MER_MAP_ID),
                cust_rech_no=cust_rech_no, sessiontoken=sessiontoken, timeout=timeout,
            )
            if looks_like_query_success(result):
                return {"success": True, "data": result, "relogin": True}
            return {"success": False, "error": f"登录后查询失败: code={result.get('code')}", "raw": result}

    return {"success": False, "error": "未知错误"}


def extract_info(data: dict) -> dict:
    """从查询结果提取关键信息"""
    datajson = data.get("datajson", {})
    device_list = datajson.get("deviceInfo", [])
    apartment = ""
    power_raw, power_num = "", None
    balance_raw, balance_num = "", None
    subsidy_raw, subsidy_num = "", None

    if device_list and isinstance(device_list, list) and isinstance(device_list[0], dict):
        d = device_list[0]
        apartment = d.get("nameValue", "")
        power_raw = d.get("unitValue", "")
        if power_raw:
            m = re.search(r"[\d.]+", str(power_raw))
            if m:
                power_num = float(m.group())
        for info in d.get("infos", []):
            key = info.get("key", "")
            key_value = info.get("keyValue", "")
            match = None
            if key_value:
                m = re.search(r"[\d.]+", str(key_value))
                if m:
                    match = float(m.group())
            if key == "nMoney":
                balance_raw, balance_num = key_value, match
            elif key == "bzMoney":
                subsidy_raw, subsidy_num = key_value, match

    return {
        "apartment": apartment or f"寝室 {datajson.get('custRechNo', '')}",
        "power_raw": power_raw, "power_num": power_num,
        "balance_raw": balance_raw, "balance_num": balance_num,
        "subsidy_raw": subsidy_raw, "subsidy_num": subsidy_num,
        "school": datajson.get("rechUnitName", ""),
    }


def save_log_entry(entry: dict):
    """保存查询记录到 query_log.json"""
    try:
        existing = []
        if LOG_FILE.exists():
            existing = json.loads(LOG_FILE.read_text(encoding="utf-8"))
        if not isinstance(existing, list):
            existing = []
        existing.append(entry)
        if len(existing) > 500:
            existing = existing[-500:]
        LOG_FILE.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"[OK] 记录已保存 ({len(existing)} 条历史)")
    except Exception as e:
        log(f"[WARN] 保存日志失败: {e}")


def compute_consumption_summary() -> str:
    """计算与上次查询的用电量变化"""
    try:
        if not LOG_FILE.exists():
            return ""
        history = json.loads(LOG_FILE.read_text(encoding="utf-8"))
        if not isinstance(history, list) or len(history) < 2:
            return ""
        prev = history[-2]
        curr = history[-1]
        if prev.get("power_num") and curr.get("power_num"):
            diff = prev["power_num"] - curr["power_num"]
            if diff > 0:
                return f"本次消耗: {diff:.2f}度"
            elif diff < 0:
                return f"充值/变化: +{abs(diff):.2f}度"
            else:
                return "用电量无变化"
    except Exception:
        return ""
    return ""


def send_wxpusher(app_token: str, uids: list, content: str, summary: str) -> bool:
    """通过 WxPusher 发送微信推送（支持多 UID）"""
    if not uids:
        return False
    url = "https://wxpusher.zjiecode.com/api/send/message"
    data = {
        "appToken": app_token,
        "content": content,
        "summary": summary,
        "contentType": 1,
        "uids": uids,
    }
    try:
        resp = requests.post(url, json=data, timeout=15)
        result = resp.json()
        if result.get("code") == 1000:
            log(f"[OK] WxPusher 推送成功 (发送给 {len(uids)} 人)")
            return True
        else:
            log(f"[ERROR] WxPusher 推送失败: code={result.get('code')}, msg={result.get('msg', '')}")
            return False
    except Exception as e:
        log(f"[ERROR] WxPusher 请求异常: {e}")
        return False


def generate_dashboard():
    """调用仪表盘生成器"""
    try:
        import generate_dashboard
        generate_dashboard.main()
        log("[OK] 仪表盘已更新")
    except Exception as e:
        log(f"[WARN] 仪表盘生成失败: {e}")


def upload_to_github():
    """上传仪表盘到 GitHub Pages"""
    github_config = SCRIPT_DIR / "github_config.json"
    if not github_config.exists():
        return
    try:
        config = json.loads(github_config.read_text(encoding="utf-8"))
        token = config.get("token", "").strip()
        if not token or "粘贴" in token:
            return  # 未配置 token，跳过
        log("[INFO] 正在上传到 GitHub Pages...")
        result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "upload_to_github.py")],
            capture_output=True, text=True, timeout=60,
            cwd=str(SCRIPT_DIR), encoding="utf-8",
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    log(f"  {line.strip()}")
        else:
            log(f"[WARN] GitHub 上传出错: {result.stderr[:200] if result.stderr else '未知错误'}")
    except Exception as e:
        log(f"[WARN] GitHub 上传失败: {e}")


def main():
    log("=" * 50)
    log("电费自动监控脚本启动")
    log(f"日期: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 50)

    config = load_config()
    app_token = config.get("wxpusher_appToken", "").strip()
    cust_rech_no = config.get("custRechNo", "")

    # 构建推送 UID 列表：优先用 wxpusher_uids 数组，兼容旧版 wxpusher_uid
    uids = []
    raw_uids = config.get("wxpusher_uids", [])
    if isinstance(raw_uids, list):
        uids = [u.strip() for u in raw_uids if u.strip() and u.strip() != "ROOMMATE_UID_HERE"]
    if not uids:
        single_uid = config.get("wxpusher_uid", "").strip()
        if single_uid:
            uids = [single_uid]

    # 1. 查询电费
    log(f"[INFO] 正在查询寝室 {cust_rech_no} ...")
    result = do_query(config)

    if not result.get("success"):
        error_msg = result.get("error", "未知错误")
        log(f"[ERROR] 查询失败: {error_msg}")
        if app_token and uids:
            fail_content = (
                f"❌ 电费查询失败\n"
                f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"寝室: {cust_rech_no}\n"
                f"原因: {error_msg}"
            )
            send_wxpusher(app_token, uids, fail_content, "电费查询失败")
        sys.exit(1)

    data = result["data"]
    info = extract_info(data)
    query_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    log(f"  寝室: {cust_rech_no} - {info['apartment']}")
    log(f"  剩余电量: {info['power_raw']}")
    log(f"  当前余额: {info['balance_raw']}")
    log(f"  剩余补助: {info['subsidy_raw']}")
    if result.get("relogin"):
        log("  (本次自动重新登录)")

    # 2. 保存查询记录
    log_entry = {
        "time": query_time,
        "custRechNo": cust_rech_no,
        "power_raw": info["power_raw"], "power_num": info["power_num"],
        "balance_raw": info["balance_raw"], "balance_num": info["balance_num"],
        "subsidy_raw": info["subsidy_raw"], "subsidy_num": info["subsidy_num"],
    }
    save_log_entry(log_entry)

    # 3. 生成仪表盘
    generate_dashboard()

    # 4. 上传到 GitHub Pages（如果已配置，CI 模式下跳过——由 workflow 直接 commit）
    if not CI_MODE:
        upload_to_github()

    # 5. 构建推送内容
    consumption = compute_consumption_summary()
    low_power = info["power_num"] is not None and info["power_num"] < LOW_POWER_THRESHOLD
    low_balance = info["balance_num"] is not None and info["balance_num"] < LOW_BALANCE_THRESHOLD

    content_lines = [
        "═══════════════════",
        "  ⚡ 电费查询结果",
        "═══════════════════",
        f"⏰ {query_time}",
        f"🏠 {cust_rech_no} - {info['apartment']}",
        f"🏫 {info['school']}",
        "",
        f"⚡ 剩余电量: {info['power_raw']}",
        f"💰 当前余额: {info['balance_raw']}",
        f"🎁 剩余补助: {info['subsidy_raw']}",
    ]

    if consumption:
        content_lines.append(f"📊 {consumption}")

    if low_power or low_balance:
        content_lines.append("")
        content_lines.append("⚠️⚠️⚠️ 提醒 ⚠️⚠️⚠️")
        if low_power:
            content_lines.append(f"电量仅剩 {info['power_raw']}，请及时充值！")
        if low_balance:
            content_lines.append(f"余额仅剩 {info['balance_raw']}，请及时充值！")

    content_lines.append("")
    content_lines.append("--- 自动监控 ---")

    text_content = "\n".join(content_lines)
    summary = f"⚡{info['power_raw']} | 💰{info['balance_raw']}"

    # 6. 推送
    if app_token and uids:
        send_wxpusher(app_token, uids, text_content, summary)
    else:
        log("[WARN] 未配置 WxPusher，跳过推送")

    log("[INFO] 全部完成！")


if __name__ == "__main__":
    main()
