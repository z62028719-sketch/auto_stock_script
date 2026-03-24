#!/usr/bin/env python3
"""
股票信号监控脚本 - Stock Signal Monitor
自动点击坐标，检测抄底/卖出信号，并发送邮件报告
支持 macOS / Windows，周期性执行，去重不重复发送
"""

import platform
import subprocess
import sys
import time
import smtplib
import json
import os
import logging
from collections import deque
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from pathlib import Path

import pyautogui

# ─────────────────────────────────────────────
# 日志配置
# ─────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / f"monitor_{datetime.now().strftime('%Y%m%d')}.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 加载配置文件
# ─────────────────────────────────────────────
CONFIG_PATH = Path(__file__).parent / "config.json"

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

# pyautogui 安全设置：移到角落不自动中止，提升稳定性
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.1

# ─────────────────────────────────────────────
# 鼠标点击（pyautogui，macOS / Windows 通用）
# ─────────────────────────────────────────────
def click(x, y):
    """先移动鼠标到指定坐标再点击，确保顺序可见、可追踪"""
    log.info(f"  点击坐标 ({x}, {y})")
    pyautogui.moveTo(x, y, duration=0.25)
    pyautogui.click()

# ─────────────────────────────────────────────
# 截图信号检测区域
# ─────────────────────────────────────────────
def capture_signal_region(config, save_path):
    """截取 signal_region 配置的矩形区域"""
    sr = config["signal_region"]
    x1, y1, x2, y2 = sr["x1"], sr["y1"], sr["x2"], sr["y2"]
    w, h = x2 - x1, y2 - y1
    img = pyautogui.screenshot(region=(x1, y1, w, h))
    img.save(str(save_path))
    return img

# ─────────────────────────────────────────────
# 颜色检测信号（红色=抄底，绿色=卖出）
# ─────────────────────────────────────────────
def detect_signal(image_path, config):
    """
    对截图做颜色检测：
    - 红色像素超过阈值 → 抄底
    - 绿色像素超过阈值 → 卖出
    返回: "抄底" | "卖出" | None
    """
    try:
        from PIL import Image
        import numpy as np

        img = Image.open(image_path).convert("RGB")
        arr = np.array(img)

        cd = config["color_detect"]
        r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]

        red_count = int(((r > cd["red_min_r"]) & (g < cd["red_max_g"]) & (b < cd["red_max_b"])).sum())
        green_count = int(((g > cd["green_min_g"]) & (r < cd["green_max_r"]) & (b < cd["green_max_b"])).sum())
        threshold = cd["min_pixels"]

        log.info(f"    颜色检测 - 红色像素: {red_count}, 绿色像素: {green_count}, 阈值: {threshold}")

        has_red = red_count >= threshold
        has_green = green_count >= threshold

        if has_red and has_green:
            return "抄底" if red_count >= green_count else "卖出"
        if has_red:
            return "抄底"
        if has_green:
            return "卖出"
        return None

    except ImportError:
        log.error("    Pillow/numpy 未安装！请运行: pip install Pillow numpy")
        return None
    except Exception as e:
        log.warning(f"    颜色检测失败: {e}")
        return None

# ─────────────────────────────────────────────
# 执行单只股票的完整操作流程
# ─────────────────────────────────────────────
def process_stock(stock, config):
    """
    对单只股票执行完整操作：
    1. 点击股票坐标
    2. 依次点击操作序列坐标
    3. 每次点击后检测信号
    返回: {"click_results": [...], "final_signal": "抄底"|"卖出"|None}
    """
    name = stock["name"]
    sx, sy = stock["x"], stock["y"]
    click_delay = config["click_delay_seconds"]
    screenshot_dir = Path(__file__).parent / "screenshots"
    screenshot_dir.mkdir(exist_ok=True)

    log.info(f"\n{'='*50}")
    log.info(f"处理股票: {name} 坐标({sx}, {sy})")

    # 点击股票后多等一会，让详情/面板完全打开再操作
    delay_after_stock = config.get("delay_after_stock_click_seconds", click_delay)
    delay_before_capture = config.get("delay_before_screenshot_seconds", 0)

    # 1. 点击股票坐标
    click(sx, sy)
    time.sleep(delay_after_stock)

    click_results = []
    # 明确按配置顺序，不可打乱
    sequence = list(config["click_sequence"])

    # 2. 严格按 click_sequence 顺序依次点击（先移光标再点，便于肉眼确认）
    for i, coord in enumerate(sequence):
        cx, cy = int(coord["x"]), int(coord["y"])
        step_num = i + 1
        total = len(sequence)
        log.info(f"  操作序列 第 {step_num}/{total} 步 -> 即将点击 ({cx}, {cy})")
        if sys.stdout and hasattr(sys.stdout, "flush"):
            sys.stdout.flush()
        click(cx, cy)
        time.sleep(click_delay)
        if delay_before_capture > 0:
            time.sleep(delay_before_capture)

        # 截图信号检测区域
        ts = datetime.now().strftime("%H%M%S")
        img_path = screenshot_dir / f"{name}_seq{i+1}_{ts}.png"
        capture_signal_region(config, img_path)

        signal = detect_signal(str(img_path), config)
        note = coord.get("_note", f"步骤{step_num}")
        click_results.append({
            "sequence_index": step_num,
            "note": note,
            "coord": coord,
            "signal": signal,
        })

        # try:
        #     img_path.unlink()
        # except OSError:
        #     pass

        if signal:
            log.info(f"  ✅ [{note}] 检测到信号: {signal}")

    # 按信号类型分组，记录每个时间周期的信号
    signal_details = [
        {"note": r["note"], "signal": r["signal"]}
        for r in click_results if r["signal"]
    ]
    chao_di_notes = [d["note"] for d in signal_details if d["signal"] == "抄底"]
    mai_chu_notes = [d["note"] for d in signal_details if d["signal"] == "卖出"]

    summary_parts = []
    if chao_di_notes:
        summary_parts.append(f"抄底({', '.join(chao_di_notes)})")
    if mai_chu_notes:
        summary_parts.append(f"卖出({', '.join(mai_chu_notes)})")

    summary = " / ".join(summary_parts) if summary_parts else "无信号"
    log.info(f"  股票 {name} 信号汇总: {summary}")

    return {
        "click_results": click_results,
        "signal_details": signal_details,
        "chao_di_notes": chao_di_notes,
        "mai_chu_notes": mai_chu_notes,
    }

# ─────────────────────────────────────────────
# 发送邮件报告
# ─────────────────────────────────────────────
def send_email_report(results, config, session_time):
    """发送 HTML 格式的邮件报告，支持多个收件人"""
    email_cfg = config["email"]
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    recipients = email_cfg.get("recipients", [email_cfg.get("recipient", "")])

    chao_di = [(name, data) for name, data in results.items() if data.get("chao_di_notes")]
    mai_chu = [(name, data) for name, data in results.items() if data.get("mai_chu_notes")]
    no_signal = [(name, data) for name, data in results.items()
                 if not data.get("chao_di_notes") and not data.get("mai_chu_notes")]

    def signal_rows(items, color, signal_key):
        if not items:
            return f"<tr><td colspan='2' style='color:#999;padding:8px'>无</td></tr>"
        rows_html = ""
        for name, data in items:
            notes = ", ".join(data.get(signal_key, []))
            rows_html += (
                f"<tr>"
                f"<td style='padding:8px 16px;font-weight:bold;color:{color}'>{name}</td>"
                f"<td style='padding:8px 16px;color:{color}'>{notes}</td>"
                f"</tr>"
            )
        return rows_html

    html = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:600px;margin:auto">
    <h2 style="color:#333">📊 股票信号监控报告</h2>
    <p style="color:#666">检测时间：{now_str}（{session_time}场）</p>

    <h3 style="color:#e74c3c">🔴 抄底信号（{len(chao_di)} 只）</h3>
    <table style="width:100%;border-collapse:collapse;background:#fff5f5;border-radius:8px">
      <tr style="border-bottom:1px solid #fcc"><th style="padding:8px 16px;text-align:left">股票</th><th style="padding:8px 16px;text-align:left">触发周期</th></tr>
      {signal_rows(chao_di, '#e74c3c', 'chao_di_notes')}
    </table>

    <h3 style="color:#27ae60">🟢 卖出信号（{len(mai_chu)} 只）</h3>
    <table style="width:100%;border-collapse:collapse;background:#f0fff4;border-radius:8px">
      <tr style="border-bottom:1px solid #cfc"><th style="padding:8px 16px;text-align:left">股票</th><th style="padding:8px 16px;text-align:left">触发周期</th></tr>
      {signal_rows(mai_chu, '#27ae60', 'mai_chu_notes')}
    </table>

    <h3 style="color:#999">⚪ 无信号（{len(no_signal)} 只）</h3>
    <table style="width:100%;border-collapse:collapse;background:#f9f9f9;border-radius:8px">
      {"".join(f"<tr><td style='padding:8px 16px;color:#999'>{name}</td></tr>" for name, _ in no_signal) or "<tr><td style='color:#999;padding:8px'>无</td></tr>"}
    </table>

    <p style="margin-top:24px;color:#aaa;font-size:12px">
      此邮件由股票监控脚本自动发送 · Stock Monitor v1.0
    </p>
    </body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[股票信号] {now_str} {'早' if session_time=='早上' else '晚'}场监控报告 - 抄底{len(chao_di)}只 卖出{len(mai_chu)}只"
    msg["From"] = email_cfg["sender"]
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(email_cfg["sender"], email_cfg["app_password"])
            server.sendmail(email_cfg["sender"], recipients, msg.as_string())
        log.info(f"✅ 邮件已发送至 {recipients}")
    except Exception as e:
        log.error(f"❌ 邮件发送失败: {e}")

# ─────────────────────────────────────────────
# 结果指纹（用于去重）
# ─────────────────────────────────────────────
def _make_fingerprint(results):
    """
    将本轮检测结果转为可比较的指纹字符串。
    格式: "AAPL:抄底(30mins,1h);GLD:卖出(day);..."
    只包含有信号的股票，无信号的不参与指纹。
    """
    parts = []
    for name in sorted(results.keys()):
        data = results[name]
        sigs = []
        if data.get("chao_di_notes"):
            sigs.append(f"抄底({','.join(sorted(data['chao_di_notes']))})")
        if data.get("mai_chu_notes"):
            sigs.append(f"卖出({','.join(sorted(data['mai_chu_notes']))})")
        if sigs:
            parts.append(f"{name}:{'/'.join(sigs)}")
    return ";".join(parts) if parts else "__NO_SIGNAL__"


# ─────────────────────────────────────────────
# 单轮监控
# ─────────────────────────────────────────────
def run_once(config):
    """执行一轮完整监控，返回 results 字典"""
    now = datetime.now()
    hour = now.hour
    session_time = "早上" if 6 <= hour < 12 else "晚上"

    log.info(f"\n{'#'*60}")
    log.info(f"# 开始监控 - {now.strftime('%Y-%m-%d %H:%M:%S')} ({session_time}场)")
    log.info(f"{'#'*60}")

    stocks = config["stocks"]
    results = {}

    for stock in stocks:
        if not stock.get("enabled", True):
            log.info(f"跳过已禁用股票: {stock['name']}")
            continue
        try:
            result = process_stock(stock, config)
            results[stock["name"]] = result
        except Exception as e:
            log.error(f"处理 {stock['name']} 时出错: {e}")
            results[stock["name"]] = {"click_results": [], "chao_di_notes": [], "mai_chu_notes": [], "error": str(e)}

    # 汇总日志
    log.info(f"\n{'─'*50}")
    log.info("监控完成，汇总结果：")
    for name, data in results.items():
        parts = []
        if data.get("chao_di_notes"):
            parts.append(f"抄底({', '.join(data['chao_di_notes'])})")
        if data.get("mai_chu_notes"):
            parts.append(f"卖出({', '.join(data['mai_chu_notes'])})")
        sig = " / ".join(parts) if parts else "无信号"
        log.info(f"  {name}: {sig}")

    return results, session_time


# ─────────────────────────────────────────────
# 主循环（周期性执行 + 去重）
# ─────────────────────────────────────────────
def run_monitor():
    config = load_config()
    interval = config.get("run_interval_minutes", 10)
    history_size = config.get("dedup_history_count", 5)
    history = deque(maxlen=history_size)

    log.info(f"监控启动 - 每 {interval} 分钟执行一次，去重最近 {history_size} 次记录")

    while True:
        config = load_config()
        try:
            results, session_time = run_once(config)
        except Exception as e:
            log.error(f"本轮监控异常: {e}")
            time.sleep(config.get("run_interval_minutes", 10) * 60)
            continue

        fp = _make_fingerprint(results)
        has_signal = fp != "__NO_SIGNAL__"

        if has_signal and fp in history:
            log.info(f"⏭️  本轮信号与最近 {history_size} 次中某次相同，跳过发送邮件")
        elif has_signal:
            send_email_report(results, config, session_time)
            history.append(fp)
        else:
            log.info("本轮无任何信号，不发送邮件")

        interval = config.get("run_interval_minutes", 10)
        log.info(f"下一轮将在 {interval} 分钟后执行...\n")
        time.sleep(interval * 60)


if __name__ == "__main__":
    run_monitor()
