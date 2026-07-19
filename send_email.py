#!/usr/bin/env python3
"""
邮件发送模块 — 读取当天最新日报，通过 QQ 邮箱 SMTP 发送。

前置条件（设置环境变量）：
  set QQ_EMAIL=你的QQ号@qq.com
  set QQ_AUTH_CODE=你的QQ邮箱授权码

获取授权码：QQ邮箱 → 设置 → 账户 → POP3/SMTP服务 → 开启 → 复制授权码

用法：
  python send_email.py                              # 发送当天日报
  python send_email.py daily_report_2026-07-19.md   # 发送指定文件
"""

import smtplib
import datetime
import os
import re
import sys
import io
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='ignore')

# ============================================================
# 配置（从环境变量读取）
# ============================================================
QQ_MAIL = os.environ.get("QQ_EMAIL")
QQ_AUTH_CODE = os.environ.get("QQ_AUTH_CODE")

if not QQ_MAIL or not QQ_AUTH_CODE:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                    if name == "QQ_EMAIL" and not QQ_MAIL:
                        QQ_MAIL = value
                    if name == "QQ_AUTH_CODE" and not QQ_AUTH_CODE:
                        QQ_AUTH_CODE = value
                    i += 1
                except OSError:
                    break
            winreg.CloseKey(key)
    except (ImportError, OSError):
        pass

SMTP_SERVER = "smtp.qq.com"
SMTP_PORT = 465
REPORT_DIR = Path(__file__).parent


def find_latest_report():
    """找到当天最新的日报文件（优先自动版）"""
    today = datetime.date.today().strftime("%Y-%m-%d")
    for p in [
        REPORT_DIR / f"daily_report_{today}_自动版.md",
        REPORT_DIR / f"daily_report_{today}.md",
    ]:
        if p.exists():
            return p
    return None


def read_report(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ============================================================
# 卡片式 HTML 渲染器（QQ 邮箱友好）
# ============================================================

CSS = """
<style>
  body{font-family:'Microsoft YaHei','PingFang SC',sans-serif;background:#f5f6fa;margin:0;padding:16px;color:#2c3e50}
  .header{background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;padding:20px 24px;border-radius:12px;margin-bottom:16px}
  .header h1{font-size:20px;margin:0 0 6px;font-weight:700}
  .header .meta{font-size:12px;opacity:.85;line-height:1.6}
  .card{background:#fff;border-radius:12px;padding:16px 20px;margin-bottom:14px;box-shadow:0 1px 4px rgba(0,0,0,.06)}
  .card h2{font-size:16px;margin:0 0 12px;padding-bottom:8px;border-bottom:2px solid #f0f0f0}
  .card h3{font-size:14px;margin:12px 0 8px;color:#555}
  .stat-row{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:8px}
  .stat-tag{display:inline-flex;align-items:center;gap:4px;background:#f8f9fc;border:1px solid #e8ecf1;border-radius:8px;padding:6px 12px;font-size:13px}
  .stat-tag .num{font-size:18px;font-weight:700}
  .stat-tag.green{border-color:#c8e6c9;background:#e8f5e9}
  .stat-tag.red{border-color:#ffcdd2;background:#ffebee}
  .stat-tag.blue{border-color:#bbdefb;background:#e3f2fd}
  table{width:100%;border-collapse:collapse;font-size:12px;margin:8px 0}
  th{background:#f0f1f5;padding:8px 6px;text-align:center;font-weight:600;font-size:11px;color:#666;border:1px solid #e0e0e0}
  td{padding:7px 5px;text-align:center;border:1px solid #e0e0e0;font-size:11px}
  td:nth-child(2),td:nth-child(3){text-align:left}
  .badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600}
  .badge-yes{background:#c8e6c9;color:#2e7d32}
  .badge-no{background:#f5f5f5;color:#bbb}
  .badge-official{background:#e3f2fd;color:#1565c0}
  .badge-web{background:#fff3e0;color:#e65100}
  .badge-star3{background:#fff9c4;color:#f57f17;font-size:12px}
  .badge-star2{background:#e8eaf6;color:#3949ab}
  .badge-star1{background:#f5f5f5;color:#999}
  .change-row{display:flex;gap:16px;margin:6px 0}
  .change-item{display:flex;align-items:center;gap:4px;font-size:14px}
  .change-item .num{font-size:22px;font-weight:800}
  .list{font-size:12px;line-height:1.8;padding-left:16px;margin:4px 0}
  .list li{margin-bottom:2px}
  .insight{font-size:12px;line-height:1.7;color:#555;padding:8px 12px;background:#fafbff;border-radius:8px;border-left:3px solid #667eea}
  .footer{text-align:center;font-size:11px;color:#aaa;padding:16px 0}
  .highlight{background:linear-gradient(135deg,#fff3cd,#fff9c4);border-radius:4px;padding:0 2px}
  @media(max-width:600px){body{padding:8px}.card{padding:12px}table{font-size:10px}}
</style>
"""


def _render_cards(md_text):
    """将 Markdown 日报渲染为卡片式 HTML"""
    lines = md_text.split("\n")

    # 解析结构化数据
    sections = _parse_sections(lines)
    title = sections.get("_title", "智能求职日报")
    meta_lines = sections.get("_meta", [])
    h2s = sections.get("_h2", [])
    change = sections.get("_change", {})       # 历史对比
    hot = sections.get("_hot", [])              # 高匹配/中匹配/低匹配

    html = ['<html><head><meta charset="utf-8">', CSS, '</head>',
            '<body>']

    # --- 头部卡片 ---
    html.append('<div class="header">')
    html.append(f'<h1>{title}</h1>')
    html.append('<div class="meta">')
    for m in meta_lines:
        label = _escape(m["text"])
        html.append(f'<div>{label}</div>')
    html.append('</div></div>')

    # --- 核心统计卡片 ---
    stats = sections.get("_stats", {})
    if change:
        html.append('<div class="card">')
        html.append('<h2>📈 与昨日对比</h2>')
        html.append('<div class="change-row">')
        c = change
        html.append(f'<div class="change-item"><span class="num" style="color:#4caf50">+{c["new"]}</span> 🆕 新增</div>')
        html.append(f'<div class="change-item"><span class="num" style="color:#f44336">-{c["removed"]}</span> ❌ 下架</div>')
        html.append(f'<div class="change-item"><span class="num" style="color:#999">{c["unchanged"]}</span> ➖ 不变</div>')
        html.append('</div></div>')

    if stats:
        html.append('<div class="card">')
        html.append('<h2>📊 今日概览</h2>')
        html.append('<div class="stat-row">')
        html.append(f'<div class="stat-tag green"><span>⭐</span><span class="num">{stats.get("star3", 0)}</span>高匹配</div>')
        html.append(f'<div class="stat-tag blue"><span>⭐⭐</span><span class="num">{stats.get("star2", 0)}</span>中匹配</div>')
        html.append(f'<div class="stat-tag"><span>⭐</span><span class="num">{stats.get("star1", 0)}</span>低匹配</div>')
        html.append(f'<div class="stat-tag"><span>📋</span><span class="num">{stats.get("total", 0)}</span>岗位总数</div>')
        html.append('</div></div>')

    # --- 主表格卡片 ---
    table_html = _render_main_table(lines)
    if table_html:
        html.append('<div class="card">')
        html.append('<h2>📊 搜索结果汇总</h2>')
        html.append(table_html)
        html.append('</div>')

    # --- 匹配度分组卡片 ---
    if hot:
        html.append('<div class="card">')
        html.append('<h2>🏆 按匹配度分组</h2>')
        for level, items in hot:
            if not items:
                continue
            html.append(f'<h3>{level}</h3>')
            html.append('<ul class="list">')
            for item in items:
                html.append(f'<li><b>{_escape(item.get("company",""))}</b> — {_escape(item.get("position",""))} <span style="color:#999">{_escape(item.get("location",""))}</span></li>')
            html.append('</ul>')
        html.append('</div>')

    # --- 解读卡片 ---
    insight = sections.get("_insight")
    if insight:
        html.append('<div class="card">')
        html.append('<h2>💡 快速解读</h2>')
        html.append('<div class="insight">')
        for line in insight.split("\n"):
            clean = line.strip("- ").strip()
            if clean:
                html.append(f'<p style="margin:4px 0">{_escape(clean)}</p>')
        html.append('</div></div>')

    # --- 页脚 ---
    html.append('<div class="footer">')
    html.append(f'🤖 自动日报 · {datetime.date.today()}<br>')
    html.append('⏰ 明天 08:00 自动发送')
    html.append('</div>')

    html.append('</body></html>')
    return "\n".join(html)


def _parse_sections(lines):
    """解析日报 Markdown，提取结构化数据"""
    result = {
        "_title": "智能求职日报",
        "_meta": [],
        "_stats": {},
        "_change": {},
        "_hot": [],
        "_insight": "",
        "_h2": [],
    }

    current_h2 = ""
    current_h3 = ""
    in_table = False
    table_header = []
    table_rows = []

    for i, raw_line in enumerate(lines):
        line = raw_line.strip()

        # 主标题 (# 开头)
        if line.startswith("# ") and not line.startswith("## "):
            result["_title"] = line[2:].strip()
            continue

        # 引用行 — 元信息
        if line.startswith("> "):
            text = line[2:].strip()
            result["_meta"].append({"text": text})
            # 提取统计数字
            m = re.search(r"原始\s*(\d+)\s*条", text)
            if m: result["_stats"]["total_jh"] = int(m.group(1))
            continue

        # 二级标题
        if line.startswith("## "):
            current_h2 = line[3:].strip()
            current_h3 = ""
            continue

        # 三级标题
        if line.startswith("### "):
            current_h3 = line[4:].strip()
            continue

        # 表格
        if line.startswith("|"):
            if not in_table:
                in_table = True
                table_header = [c.strip() for c in line.strip("|").split("|")]
            elif not table_header:
                continue
            elif "---" in line:
                pass
            else:
                cells = [c.strip() for c in line.strip("|").split("|")]
                table_rows.append(cells)
            continue
        else:
            in_table = False

        # 变化统计
        if "与昨日对比" in current_h2:
            m = re.search(r"🆕.*?新增.*?(\d+)", line)
            if m: result["_change"]["new"] = int(m.group(1))
            m = re.search(r"❌.*?下架.*?(\d+)", line)
            if m: result["_change"]["removed"] = int(m.group(1))
            m = re.search(r"➖.*?不变.*?(\d+)", line)
            if m: result["_change"]["unchanged"] = int(m.group(1))
            continue

        # 匹配度统计
        if "高匹配" in current_h2 or "中匹配" in current_h2 or "低匹配" in current_h2:
            m = re.search(r"(\d+)\s*条", current_h2 + line)
            k = "高" if "高" in current_h2 else ("中" if "中" in current_h2 else "低")
            if m:
                result["_stats"][f"star{k}"] = result["_stats"].get(f"star{k}", 0) + int(m.group(1))

        # 高/中/低匹配列表（解析新增/下架列表）
        if re.match(r"^\d+\.\s", line):
            parts = line.split(". ", 1)[1]
            if "—" in parts:
                company, position = parts.split("—", 1)
                result.setdefault("_hot_items", []).append({
                    "company": company.strip(),
                    "position": position.strip(),
                    "level": current_h3 if "新增" in current_h3 else ("已下架" if "下架" in current_h3 else current_h2),
                })

        # 快速解读
        if "快速解读" in current_h2 and line and not line.startswith("#"):
            result["_insight"] += line + "\n"

    # 解析主表格数据
    if table_rows:
        total = len(table_rows)
        star3 = sum(1 for r in table_rows if any("⭐⭐⭐" in c for c in r))
        star2 = sum(1 for r in table_rows if any("⭐⭐" in c and "⭐⭐⭐" not in c for c in r))
        star1 = sum(1 for r in table_rows if any("⭐" in c and "⭐⭐" not in c for c in r))
        result["_stats"]["total"] = total
        result["_stats"]["star3"] = result["_stats"].get("star3", 0) or star3
        result["_stats"]["star2"] = result["_stats"].get("star2", 0) or star2
        result["_stats"]["star1"] = result["_stats"].get("star1", 0) or star1

    return result


def _render_main_table(lines):
    """渲染主搜索结果表格（带图标和徽章）"""
    # 找到表格块
    table_start = None
    table_end = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if table_start is None and "搜索结果汇总表" in stripped:
            for j in range(i + 1, min(i + 20, len(lines))):
                if lines[j].strip().startswith("|") and "公司" in lines[j]:
                    table_start = j
                    break
        if table_start is not None and table_end is None:
            if (stripped.startswith("## ") or stripped.startswith("---")) and j > table_start:
                table_end = j
                break
            if not stripped.startswith("|") and stripped != "" and not stripped.startswith(">"):
                table_end = j
                break
    if table_end is None and table_start is not None:
        # 找空行或下一个 section
        for j in range(table_start + 1, len(lines)):
            if lines[j].strip() == "" or lines[j].strip().startswith("---") or lines[j].strip().startswith("##"):
                table_end = j
                break
        if table_end is None:
            table_end = len(lines)

    if table_start is None:
        return ""

    # 收集数据行（跳过表头和分隔行）
    in_data = False
    rows = []
    for i in range(table_start, table_end):
        line = lines[i].strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if any("---" in c for c in cells):
            in_data = True
            continue
        if in_data and len(cells) >= 6:
            rows.append(cells)

    if not rows:
        return ""

    # 提取列
    html = ['<table><thead><tr>',
            '<th>公司</th><th>岗位</th><th>地点</th><th>来源</th>',
            '<th>住宿</th><th>薪资</th><th>匹配</th></tr></thead><tbody>']

    for r in rows:
        # 列：| # | 公司(1) | 岗位(2) | 地点(3) | [数据来源(4)] | 双休 | 住宿 | 薪资 | 匹配 | 关键词 |
        company = r[1] if len(r) > 1 else ""
        position = r[2] if len(r) > 2 else ""
        location = r[3] if len(r) > 3 else ""

        # 判断是否有「数据来源」列
        has_source = "数据来源" in (lines[table_start] if table_start else "")
        src_col = 4
        offset = 1 if has_source else 0
        housing_col = 4 + offset
        salary_col = 5 + offset
        match_col = 6 + offset

        source = r[4] if has_source and len(r) > 4 else "网络搜索"
        housing = r[housing_col] if len(r) > housing_col else "❌"
        salary = r[salary_col] if len(r) > salary_col else "❌"
        match_raw = r[match_col] if len(r) > match_col else ""

        # 匹配徽章
        match_stars = ""
        if "⭐⭐⭐" in match_raw:
            match_stars = '<span class="badge badge-star3">⭐⭐⭐</span>'
        elif "⭐⭐" in match_raw:
            match_stars = '<span class="badge badge-star2">⭐⭐</span>'
        elif "⭐" in match_raw:
            match_stars = '<span class="badge badge-star1">⭐</span>'
        else:
            match_stars = '<span style="color:#ccc">—</span>'

        # 住宿/薪资徽章
        housing_badge = '<span class="badge badge-yes">✅</span>' if "✅" in housing else '<span class="badge badge-no">—</span>'
        salary_badge = '<span class="badge badge-yes">✅</span>' if "✅" in salary else '<span class="badge badge-no">—</span>'

        # 数据来源徽章
        if "官方" in source:
            source_badge = '<span class="badge badge-official">🏢 官方</span>'
        else:
            source_badge = '<span class="badge badge-web">🌐 网络</span>'

        html.append(f'<tr><td>{_escape(company)}</td><td>{_escape(position)}</td>'
                    f'<td>{_escape(location)}</td><td>{source_badge}</td>'
                    f'<td>{housing_badge}</td><td>{salary_badge}</td>'
                    f'<td>{match_stars}</td></tr>')

    html.append('</tbody></table>')
    return "".join(html)


def _escape(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ============================================================
# 邮件发送
# ============================================================

def send_email(to_addr, subject, body_md):
    msg = MIMEMultipart("alternative")
    msg["From"] = QQ_MAIL
    msg["To"] = to_addr
    msg["Subject"] = subject

    # HTML 卡片版
    html_body = _render_cards(body_md)

    # 纯文本备用（提取纯文字）
    plain = _strip_markdown(body_md)

    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
        server.login(QQ_MAIL, QQ_AUTH_CODE)
        server.sendmail(QQ_MAIL, to_addr, msg.as_string())


def _strip_markdown(md_text):
    """去掉 Markdown 标记，保留纯文本"""
    text = re.sub(r"^#{1,4}\s+", "", md_text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"^>\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\|.*?\|", "", text)  # 去掉表格
    return text


def main():
    if len(sys.argv) > 1:
        report_path = REPORT_DIR / sys.argv[1]
        if not report_path.exists():
            print(f"❌ 文件不存在：{report_path}")
            sys.exit(1)
    else:
        report_path = find_latest_report()
        if report_path is None:
            print(f"❌ 未找到今天的日报文件（{datetime.date.today()}）")
            sys.exit(1)

    missing = []
    if not QQ_MAIL: missing.append("QQ_EMAIL")
    if not QQ_AUTH_CODE: missing.append("QQ_AUTH_CODE")
    if missing:
        print(f"❌ 缺少环境变量：{', '.join(missing)}")
        print(f"   set QQ_EMAIL=你的QQ号@qq.com")
        print(f"   set QQ_AUTH_CODE=你的QQ邮箱授权码")
        sys.exit(1)

    today_str = datetime.date.today().strftime("%Y-%m-%d")
    subject = f"📊 实习日报 - {today_str}"

    print(f"📧 发送中...")
    print(f"   发件人: {QQ_MAIL}")
    print(f"   收件人: {QQ_MAIL}")
    print(f"   主题:   {subject}")
    print(f"   附件:   {report_path.name}")

    try:
        body = read_report(report_path)
        send_email(QQ_MAIL, subject, body)
        print("✅ 邮件发送成功！请检查收件箱。")
        print("   (如果是 QQ 邮箱，建议用手机 QQ 邮箱 APP 查看 — 渲染更好)")
    except smtplib.SMTPAuthenticationError:
        print("❌ 登录失败：授权码错误。")
    except smtplib.SMTPException as e:
        print(f"❌ SMTP 错误：{e}")
    except Exception as e:
        print(f"❌ 发送失败：{e}")


if __name__ == "__main__":
    main()
