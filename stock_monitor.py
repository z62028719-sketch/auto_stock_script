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
PREV_SIGNALS_PATH = Path(__file__).parent / "prev_signals.json"

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
def send_email_report(results, config, session_time, new_signals=None, disappeared_signals=None):
    """发送 HTML 格式的邮件报告，支持多个收件人。
    new_signals / disappeared_signals 是 (股票, 类型, 周期) 的集合，用于在表格里做差异标记。
    """
    email_cfg = config["email"]
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    recipients = email_cfg.get("recipients", [email_cfg.get("recipient", "")])

    new_signals = new_signals or set()
    disappeared_signals = disappeared_signals or set()

    # 把消失的信号按 (股票, 信号类型) 分组，方便在抄底/卖出表中直接渲染划线项
    disappeared_by_stock_type = {}
    for stock, sig_type, period in disappeared_signals:
        disappeared_by_stock_type.setdefault((stock, sig_type), []).append(period)
    for key in disappeared_by_stock_type:
        disappeared_by_stock_type[key].sort()
    stocks_with_disappeared = {stock for stock, _ in disappeared_by_stock_type}

    chao_di = [(name, data) for name, data in results.items() if data.get("chao_di_notes")]
    mai_chu = [(name, data) for name, data in results.items() if data.get("mai_chu_notes")]
    # 本轮无任何信号、且也没有刚消失的信号 → 才算真正"无信号"
    no_signal = [
        (name, data) for name, data in results.items()
        if not data.get("chao_di_notes")
        and not data.get("mai_chu_notes")
        and name not in stocks_with_disappeared
    ]

    def render_periods(name, signal_type, periods, base_color):
        """渲染周期列表：新增的加 🆕 高亮，已消失的用横线划掉。"""
        parts = []
        for p in periods:
            if (name, signal_type, p) in new_signals:
                parts.append(
                    f"<span style='background:#fff3cd;color:#d35400;"
                    f"padding:2px 8px;border-radius:6px;font-weight:bold;"
                    f"margin-right:6px;border:1px solid #ffeaa7'>🆕 {p}</span>"
                )
            else:
                parts.append(f"<span style='color:{base_color};margin-right:8px'>{p}</span>")
        # 上一轮存在、本轮消失的周期，用横线划掉
        for p in disappeared_by_stock_type.get((name, signal_type), []):
            parts.append(
                f"<span style='color:#95a5a6;text-decoration:line-through;"
                f"margin-right:8px' title='上一轮存在，本轮已消失'>{p}</span>"
            )
        return "".join(parts)

    def signal_rows(items, color, signal_key, signal_type):
        """渲染抄底/卖出表：包含本轮信号 + 本轮该类型已完全消失的股票（整行划掉）。"""
        current_stocks = {name for name, _ in items}
        # 本轮该类型完全没信号、但上一轮有的股票（需要新起一行用划线展示）
        extra_stocks = sorted({
            stock for (stock, t) in disappeared_by_stock_type
            if t == signal_type and stock not in current_stocks
        })

        if not items and not extra_stocks:
            return f"<tr><td colspan='2' style='color:#999;padding:8px'>无</td></tr>"

        rows_html = ""
        for name, data in items:
            periods = data.get(signal_key, [])
            rows_html += (
                f"<tr>"
                f"<td style='padding:8px 16px;font-weight:bold;color:{color}'>{name}</td>"
                f"<td style='padding:8px 16px;color:{color}'>{render_periods(name, signal_type, periods, color)}</td>"
                f"</tr>"
            )
        # 追加：本轮该类型已完全消失的股票，整行用淡灰+划线
        for name in extra_stocks:
            rows_html += (
                f"<tr>"
                f"<td style='padding:8px 16px;font-weight:bold;color:#95a5a6;"
                f"text-decoration:line-through'>{name}</td>"
                f"<td style='padding:8px 16px'>{render_periods(name, signal_type, [], color)}</td>"
                f"</tr>"
            )
        return rows_html

    new_count = len(new_signals)
    disappeared_count = len(disappeared_signals)

    diff_summary = ""
    if new_count or disappeared_count:
        diff_summary = (
            f"<p style='color:#555;background:#f8f9fa;padding:8px 12px;border-left:4px solid #f39c12;border-radius:4px'>"
            f"📌 与上轮对比：<b style='color:#d35400'>新增 {new_count}</b> 条，"
            f"<b style='color:#7f8c8d'>消失 {disappeared_count}</b> 条"
            f"</p>"
        )

    html = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:600px;margin:auto">
    <h2 style="color:#333">📊 股票信号监控报告</h2>
    <p style="color:#666">检测时间：{now_str}（{session_time}场）</p>
    {diff_summary}

    <h3 style="color:#e74c3c">🔴 抄底信号（{len(chao_di)} 只）</h3>
    <table style="width:100%;border-collapse:collapse;background:#fff5f5;border-radius:8px">
      <tr style="border-bottom:1px solid #fcc"><th style="padding:8px 16px;text-align:left">股票</th><th style="padding:8px 16px;text-align:left">触发周期</th></tr>
      {signal_rows(chao_di, '#e74c3c', 'chao_di_notes', '抄底')}
    </table>

    <h3 style="color:#27ae60">🟢 卖出信号（{len(mai_chu)} 只）</h3>
    <table style="width:100%;border-collapse:collapse;background:#f0fff4;border-radius:8px">
      <tr style="border-bottom:1px solid #cfc"><th style="padding:8px 16px;text-align:left">股票</th><th style="padding:8px 16px;text-align:left">触发周期</th></tr>
      {signal_rows(mai_chu, '#27ae60', 'mai_chu_notes', '卖出')}
    </table>

    <h3 style="color:#999">⚪ 无信号（{len(no_signal)} 只）</h3>
    <table style="width:100%;border-collapse:collapse;background:#f9f9f9;border-radius:8px">
      {"".join(f"<tr><td style='padding:8px 16px;color:#999'>{name}</td></tr>" for name, _ in no_signal) or "<tr><td style='color:#999;padding:8px'>无</td></tr>"}
    </table>

    <p style="margin-top:16px;color:#aaa;font-size:12px">
      标记说明：<span style='background:#fff3cd;color:#d35400;padding:1px 6px;border-radius:4px;border:1px solid #ffeaa7'>🆕 周期</span> 表示本轮新增；
      <span style='color:#95a5a6;text-decoration:line-through'>周期</span> 表示上一轮存在、本轮已消失。
    </p>
    <p style="margin-top:8px;color:#aaa;font-size:12px">
      此邮件由股票监控脚本自动发送 · Stock Monitor v1.0
    </p>
    </body></html>
    """

    subject_diff = ""
    if new_count or disappeared_count:
        subject_diff = f" [新增{new_count}/消失{disappeared_count}]"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = (
        f"[股票信号] {now_str} {'早' if session_time=='早上' else '晚'}场监控报告"
        f" - 抄底{len(chao_di)}只 卖出{len(mai_chu)}只{subject_diff}"
    )
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
# 信号差异比较（与上一轮对比，记录新增/消失）
# ─────────────────────────────────────────────
def extract_signal_set(results):
    """
    将本轮检测结果展开为信号集合：
    {(股票名, 信号类型, 触发周期), ...}
    例如: {("AAPL", "抄底", "1h"), ("GLD", "卖出", "day")}
    """
    sigs = set()
    for name, data in results.items():
        for note in data.get("chao_di_notes", []) or []:
            sigs.add((name, "抄底", note))
        for note in data.get("mai_chu_notes", []) or []:
            sigs.add((name, "卖出", note))
    return sigs


def load_prev_signals():
    """读取上一轮持久化的信号集合，文件不存在或读取失败时返回 None。"""
    if not PREV_SIGNALS_PATH.exists():
        return None
    try:
        with open(PREV_SIGNALS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {(s["stock"], s["type"], s["period"]) for s in data.get("signals", [])}
    except Exception as e:
        log.warning(f"读取上一轮信号记录失败: {e}")
        return None


def save_current_signals(curr_set):
    """把本轮信号集合持久化，供下一轮做 diff。"""
    try:
        signals = [
            {"stock": s, "type": t, "period": p}
            for (s, t, p) in sorted(curr_set)
        ]
        with open(PREV_SIGNALS_PATH, "w", encoding="utf-8") as f:
            json.dump(
                {"timestamp": datetime.now().isoformat(), "signals": signals},
                f, ensure_ascii=False, indent=2,
            )
    except Exception as e:
        log.warning(f"保存本轮信号记录失败: {e}")


def diff_signals(prev_set, curr_set):
    """
    返回 (new_signals, disappeared_signals)。
    首次运行（prev_set 为 None）返回 (set(), set()) ，避免把全部当新增。
    """
    if prev_set is None:
        return set(), set()
    new_signals = curr_set - prev_set
    disappeared = prev_set - curr_set
    return new_signals, disappeared


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
    prev_signals = load_prev_signals()

    log.info(f"监控启动 - 每 {interval} 分钟执行一次，去重最近 {history_size} 次记录")
    if prev_signals is None:
        log.info("未发现上一轮信号记录，本轮将作为基线，不进行新增/消失对比")
    else:
        log.info(f"已加载上一轮信号 {len(prev_signals)} 条，将用于本轮 diff")

    while True:
        config = load_config()
        try:
            results, session_time = run_once(config)
        except Exception as e:
            log.error(f"本轮监控异常: {e}")
            time.sleep(config.get("run_interval_minutes", 10) * 60)
            continue

        curr_signals = extract_signal_set(results)
        new_signals, disappeared_signals = diff_signals(prev_signals, curr_signals)

        if new_signals:
            log.info(
                f"🆕 新增信号 {len(new_signals)} 条: "
                + ", ".join(f"{s}-{t}({p})" for s, t, p in sorted(new_signals))
            )
        if disappeared_signals:
            log.info(
                f"⏹️  消失信号 {len(disappeared_signals)} 条: "
                + ", ".join(f"{s}-{t}({p})" for s, t, p in sorted(disappeared_signals))
            )

        fp = _make_fingerprint(results)
        has_signal = fp != "__NO_SIGNAL__"

        if has_signal and fp in history:
            log.info(f"⏭️  本轮信号与最近 {history_size} 次中某次相同，跳过发送邮件")
        elif has_signal:
            send_email_report(results, config, session_time, new_signals, disappeared_signals)
            history.append(fp)
        else:
            log.info("本轮无任何信号，不发送邮件")

        # 无论是否发送邮件，都更新基线，避免下次把"早就存在的信号"误判为新增
        save_current_signals(curr_signals)
        prev_signals = curr_signals

        interval = config.get("run_interval_minutes", 10)
        log.info(f"下一轮将在 {interval} 分钟后执行...\n")
        time.sleep(interval * 60)


if __name__ == "__main__":
    run_monitor()
