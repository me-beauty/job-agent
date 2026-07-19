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
# 卡片式 HTML 渲染器（QQ 邮箱友好 — 完整渲染，不丢内容）
# ============================================================

CSS = """
<style>
  body{font-family:'Microsoft YaHei','PingFang SC',sans-serif;background:#f5f6fa;margin:0;padding:16px;color:#2c3e50}
  .header{background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;padding:20px 24px;border-radius:12px;margin-bottom:16px}
  .header h1{font-size:18px;margin:0 0 6px;font-weight:700}
  .header .meta{font-size:12px;opacity:.85;line-height:1.7}
  .card{background:#fff;border-radius:12px;padding:14px 18px;margin-bottom:12px;box-shadow:0 1px 4px rgba(0,0,0,.06)}
  .card h2{font-size:15px;margin:0 0 10px;padding-bottom:6px;border-bottom:2px solid #f0f0f0}
  .card h3{font-size:13px;margin:10px 0 6px;color:#555}
  .card p,.card li{font-size:12px;line-height:1.7;margin:4px 0;color:#444}
  .card blockquote{font-size:11px;border-left:3px solid #d0d5dd;padding:6px 10px;margin:8px 0;color:#888;background:#f9fafb;border-radius:0 6px 6px 0}
  .card ul{padding-left:18px;margin:6px 0}
  .card hr{border:none;border-top:1px solid #e8ecf1;margin:10px 0}
  table{width:100%;border-collapse:collapse;font-size:11px;margin:6px 0}
  th{background:#f0f1f5;padding:6px 4px;text-align:center;font-weight:600;font-size:10px;color:#666;border:1px solid #e0e0e0}
  td{padding:5px 4px;text-align:center;border:1px solid #e8ecf1;font-size:10px}
  td:nth-child(2),td:nth-child(3){text-align:left}
  .badge{display:inline-block;padding:1px 6px;border-radius:8px;font-size:10px;font-weight:600;white-space:nowrap}
  .badge-y{background:#c8e6c9;color:#2e7d32}
  .badge-n{background:#f5f5f5;color:#ccc}
  .badge-st3{background:#fff9c4;color:#f57f17}
  .badge-st2{background:#e8eaf6;color:#3949ab}
  .badge-st1{background:#f5f5f5;color:#999}
  .badge-off{background:#e3f2fd;color:#1565c0}
  .badge-web{background:#fff3e0;color:#e65100}
  .stat-row{display:flex;gap:10px;flex-wrap:wrap;margin:4px 0}
  .stat-tag{display:inline-flex;align-items:center;gap:3px;background:#f8f9fc;border:1px solid #e8ecf1;border-radius:8px;padding:5px 10px;font-size:12px}
  .stat-tag .num{font-size:16px;font-weight:700}
  .change-row{display:flex;gap:14px;margin:4px 0;font-size:13px}
  .change-row .num{font-size:20px;font-weight:800}
  .footer{text-align:center;font-size:10px;color:#bbb;padding:12px 0}
  @media(max-width:600px){body{padding:6px}.card{padding:10px 12px}table{font-size:9px}th,td{padding:4px 2px}}
</style>
"""


def _render_cards(md_text):
    """逐区块渲染 Markdown → 卡片 HTML，不丢任何内容"""
    blocks = _split_blocks(md_text)
    html = ['<html><head><meta charset="utf-8">', CSS, '</head><body>']

    for b in blocks:
        kind = b["kind"]
        content = b["content"]
        if kind == "header_card":
            html.append(_render_header_card(content))
        elif kind == "h1":
            # 非首部的 # 标题：开新卡片
            html.append(f'<div class="card" style="padding:8px 18px"><h2 style="border:none;margin:0;font-size:15px">{_escape(content)}</h2></div>')
        elif kind == "card":
            html.append('<div class="card">')
            html.append(_render_block_body(content))
            html.append('</div>')

    html.append('<div class="footer">🤖 自动日报 · 每天 08:00 发送</div>')
    html.append('</body></html>')
    return "\n".join(html)


def _split_blocks(md_text):
    """把 Markdown 拆成区块列表。每个区块是 {'kind': ..., 'content': ...}"""
    lines = md_text.split("\n")
    blocks = []

    # --- 第 1 步：收集头部 meta（第一个 # 标题前的所有 > 引用行） ---
    header_title = ""
    header_meta = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            header_title = stripped[2:].strip()
            i += 1
            break
        i += 1

    # 收集 meta（标题后的引用行和属性行）
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith("> "):
            text = stripped[2:].strip()
            # 去掉 Markdown 加粗标记
            text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
            header_meta.append(text)
            i += 1
        elif stripped.startswith("---"):
            i += 1
            break
        elif stripped == "":
            i += 1
        else:
            break

    # 跳过空行和 --- 直到下一个内容
    while i < len(lines) and (lines[i].strip() == "" or lines[i].strip() == "---"):
        i += 1

    if header_title:
        blocks.append({"kind": "header_card", "content": {"title": header_title, "meta": header_meta}})

    # --- 第 2 步：把剩余内容按 ## 标题拆成卡片 ---
    current_h2 = ""
    current_lines = []

    def flush_card():
        nonlocal current_h2, current_lines
        if current_lines:
            blocks.append({"kind": "card", "content": {"heading": current_h2, "lines": list(current_lines)}})
        current_h2 = ""
        current_lines = []

    while i < len(lines):
        stripped = lines[i].strip()

        # 遇到 ## 标题：flush 上一个 card，开新的
        if stripped.startswith("## "):
            flush_card()
            current_h2 = stripped[3:].strip()
            i += 1
            continue

        # 遇到 # 标题（二级主标题）：也 flush，但作为 h1 块
        if stripped.startswith("# ") and not stripped.startswith("## "):
            flush_card()
            blocks.append({"kind": "h1", "content": stripped[2:].strip()})
            i += 1
            # 跳过紧随的空行和 ---
            while i < len(lines) and (lines[i].strip() == "" or lines[i].strip() == "---"):
                i += 1
            continue

        current_lines.append(lines[i])
        i += 1

    flush_card()

    # --- 第 3 步：过滤空卡片 ---
    blocks = [b for b in blocks if b["kind"] != "card" or any(l.strip() for l in b["content"]["lines"])]

    return blocks


def _render_header_card(content):
    """渲染紫色渐变头部卡片"""
    title = _escape(content["title"])
    meta = content["meta"]

    html = ['<div class="header"><h1>', title, '</h1>']
    if meta:
        html.append('<div class="meta">')
        for m in meta:
            html.append(f'<div>{m}</div>')
        html.append('</div>')
    html.append('</div>')
    return "".join(html)


def _render_block_body(content):
    """渲染一个卡片内部的全部内容（段落、表格、列表、引用等）"""
    heading = content["heading"]
    lines = content["lines"]

    html = []
    if heading:
        html.append(f'<h2>{_escape(heading)}</h2>')

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()

        # 空行
        if stripped == "":
            i += 1
            continue

        # 三级标题
        if stripped.startswith("### "):
            html.append(f'<h3>{_escape(stripped[4:].strip())}</h3>')
            i += 1
            continue

        # 引用
        if stripped.startswith("> "):
            quote_lines = []
            while i < len(lines) and lines[i].strip().startswith("> "):
                t = lines[i].strip()[2:].strip()
                t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
                quote_lines.append(t)
                i += 1
            html.append('<blockquote>' + "<br>".join(quote_lines) + '</blockquote>')
            continue

        # Markdown 表格（连续的 | 行）
        if stripped.startswith("|"):
            table_html, consumed = _render_table_block(lines, i)
            html.append(table_html)
            i += consumed
            continue

        # 无序列表
        if stripped.startswith("- ") or stripped.startswith("* "):
            list_items = []
            while i < len(lines) and (lines[i].strip().startswith("- ") or lines[i].strip().startswith("* ")):
                item = lines[i].strip()[2:]
                item = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", item)
                list_items.append(item)
                i += 1
            html.append('<ul>' + "".join(f'<li>{li}</li>' for li in list_items) + '</ul>')
            continue

        # 普通段落（连续的非空、非标记行合并为一 <p>）
        para_lines = []
        while i < len(lines) and lines[i].strip() != "" and not _is_block_start(lines[i].strip()):
            t = lines[i].strip()
            t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
            t = re.sub(r"`(.+?)`", r"<code>\1</code>", t)
            para_lines.append(t)
            i += 1
        if para_lines:
            html.append('<p>' + "<br>".join(para_lines) + '</p>')
        else:
            i += 1

    return "".join(html)


def _is_block_start(stripped):
    """判断是否为新块起始"""
    return (stripped.startswith("### ") or stripped.startswith("> ") or
            stripped.startswith("|") or stripped.startswith("- ") or
            stripped.startswith("* ") or stripped.startswith("## "))


def _render_table_block(lines, start_idx):
    """从 start_idx 开始渲染一个表格块。返回 (html, consumed_rows)。"""
    rows = []
    i = start_idx

    # 收集所有连续的表格行
    header_cells = None
    sep_row = None
    data_rows = []

    while i < len(lines) and lines[i].strip().startswith("|"):
        cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
        if header_cells is None:
            header_cells = cells
        elif any("---" in c for c in cells):
            sep_row = cells
        else:
            data_rows.append(cells)
        i += 1

    consumed = i - start_idx
    if not data_rows:
        return "", consumed

    # 推测列含义
    cols = _infer_columns(header_cells)
    rendered_cols = len(cols)

    html = ['<table><thead><tr>']
    for name in cols:
        html.append(f'<th>{name}</th>')
    html.append('</tr></thead><tbody>')

    for r in data_rows:
        html.append('<tr>')
        for ci in range(rendered_cols):
            val = r[ci] if ci < len(r) else ""
            html.append(f'<td>{_fmt_cell(val, cols[ci])}</td>')
        html.append('</tr>')

    html.append('</tbody></table>')
    return "".join(html), consumed


def _infer_columns(header):
    """根据表头内容推理渲染列名（精简为 QQ 邮箱友好宽度）"""
    mapping = {
        "#": "#", "公司": "公司", "公司/来源": "公司", "岗位": "岗位",
        "岗位名称": "岗位", "地点": "地点", "数据来源": "来源",
        "双休": "双休", "住宿": "住宿", "薪资": "薪资",
        "匹配": "匹配", "关键词": "来源", "编号": "编号",
        "关键词简述": "关键词", "结果数": "结果",
        "有匹配结果数": "匹配数", "亮点": "备注",
        "匹配项": "匹配项",
    }
    result = []
    for h in header:
        key = h.strip()
        result.append(mapping.get(key, key[:4]))
    return result


def _fmt_cell(val, col_name):
    """格式化表格单元格（徽章、高亮等）"""
    v = _escape(val)

    # 匹配星
    if "⭐⭐⭐" in v:
        v = v.replace("⭐⭐⭐", "") + ' <span class="badge badge-st3">3★</span>'
    elif "⭐⭐" in v:
        v = v.replace("⭐⭐", "") + ' <span class="badge badge-st2">2★</span>'
    elif "⭐" in v and "⭐⭐" not in v:
        v = v.replace("⭐", "") + ' <span class="badge badge-st1">1★</span>'

    # 住宿/薪资/双休 列
    if col_name in ("住宿", "双休", "薪资"):
        if "✅" in v:
            v = '<span class="badge badge-y">✅</span>'
        else:
            v = '<span class="badge badge-n">—</span>'

    # 来源列
    if col_name == "来源":
        if "官方" in v:
            v = '<span class="badge badge-off">🏢 官方</span>'
        elif "网络" in v:
            v = '<span class="badge badge-web">🌐 网络</span>'

    return v


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
