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
import sys
import io
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

# 强制 stdout 使用 UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='ignore')

# ============================================================
# ⚙️ 配置（从环境变量读取，不硬编码）
# ============================================================
# 环境变量：
#   QQ_EMAIL      — QQ 邮箱地址（发件人 & 收件人）
#   QQ_AUTH_CODE  — QQ 邮箱 SMTP 授权码（不是 QQ 密码！）
# ============================================================

QQ_MAIL = os.environ.get("QQ_EMAIL")
QQ_AUTH_CODE = os.environ.get("QQ_AUTH_CODE")

# 如果当前进程环境变量没读到，尝试从 Windows 注册表读取（setx 永久变量）
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

# SMTP 服务器（QQ 邮箱固定配置，不用改）
SMTP_SERVER = "smtp.qq.com"
SMTP_PORT = 465  # SSL

# 日报文件夹（默认当前脚本所在目录）
REPORT_DIR = Path(__file__).parent


def find_latest_report():
    """找到当天最新的日报文件（优先自动版，缺省手动版）"""
    today = datetime.date.today().strftime("%Y-%m-%d")

    # 候选文件名（按优先级）
    candidates = [
        REPORT_DIR / f"daily_report_{today}_自动版.md",
        REPORT_DIR / f"daily_report_{today}.md",
    ]

    for path in candidates:
        if path.exists():
            return path

    return None


def read_report(path):
    """读取日报内容"""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def send_email(to_addr, subject, body_md):
    """通过 QQ 邮箱 SMTP 发送邮件"""
    # 构建邮件
    msg = MIMEMultipart("alternative")
    msg["From"] = QQ_MAIL
    msg["To"] = to_addr
    msg["Subject"] = subject

    # 纯文本 + HTML 双版本（QQ 邮箱兼容）
    html_body = _md_to_html(body_md)
    msg.attach(MIMEText(body_md, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    # 连接并发送
    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
        server.login(QQ_MAIL, QQ_AUTH_CODE)
        server.sendmail(QQ_MAIL, to_addr, msg.as_string())


def _md_to_html(md_text):
    """简易 Markdown → HTML（避免依赖第三方库）"""
    lines = md_text.split("\n")
    html_lines = []
    in_table = False
    in_code = False

    for line in lines:
        # 代码块
        if line.startswith("```"):
            if in_code:
                html_lines.append("</pre>")
                in_code = False
            else:
                html_lines.append('<pre style="background:#f5f5f5;padding:10px;border-radius:4px;overflow-x:auto;">')
                in_code = True
            continue

        if in_code:
            html_lines.append(line)
            continue

        # 表格分隔行
        if line.startswith("|---"):
            in_table = True
            continue

        if in_table and not line.startswith("|"):
            in_table = False

        if in_table:
            cells = [c.strip() for c in line.strip("|").split("|")]
            tag = "th" if any(c.startswith("---") or c.startswith(":--") for c in cells) else "td"
            html_cells = "".join(f"<{tag}>{c}</{tag}>" for c in cells)
            html_lines.append(f"<tr>{html_cells}</tr>")
            continue

        # 标题
        if line.startswith("### "):
            html_lines.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("## "):
            html_lines.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("# "):
            html_lines.append(f"<h1>{line[2:]}</h1>")
        # 引用
        elif line.startswith("> "):
            html_lines.append(f'<blockquote style="border-left:3px solid #ccc;padding-left:8px;color:#666;">{line[2:]}</blockquote>')
        # 分隔线
        elif line.strip() == "---":
            html_lines.append("<hr>")
        # 列表
        elif line.startswith("- "):
            html_lines.append(f"<li>{line[2:]}</li>")
        # 加粗
        elif "**" in line:
            import re
            line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line)
            html_lines.append(f"<p>{line}</p>")
        # 普通段落
        elif line.strip():
            html_lines.append(f"<p>{line}</p>")
        else:
            html_lines.append("<br>")

    body = "\n".join(html_lines)
    return f"""<html>
<head><meta charset="utf-8"></head>
<body style="font-family: 'Microsoft YaHei', sans-serif; max-width: 800px; margin: 0 auto; padding: 20px;">
{body}
</body>
</html>"""


def main():
    # 解析参数
    if len(sys.argv) > 1:
        report_path = REPORT_DIR / sys.argv[1]
        if not report_path.exists():
            print(f"❌ 文件不存在：{report_path}")
            sys.exit(1)
    else:
        report_path = find_latest_report()
        if report_path is None:
            print(f"❌ 未找到今天的日报文件（{datetime.date.today()}）")
            print("   请先运行 daily_job_search_quick.py 生成日报")
            sys.exit(1)

    # 检查环境变量
    missing = []
    if not QQ_MAIL:
        missing.append("QQ_EMAIL")
    if not QQ_AUTH_CODE:
        missing.append("QQ_AUTH_CODE")
    if missing:
        print(f"❌ 缺少环境变量：{', '.join(missing)}")
        print("   请设置后重试：")
        print(f'   set QQ_EMAIL=你的QQ号@qq.com')
        print(f'   set QQ_AUTH_CODE=你的QQ邮箱授权码')
        print("   获取授权码：QQ邮箱 → 设置 → 账户 → POP3/SMTP服务 → 开启 → 复制授权码")
        sys.exit(1)

    # 读取并发送
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
        print(f"✅ 邮件发送成功！请检查收件箱。")
    except smtplib.SMTPAuthenticationError:
        print("❌ 登录失败：授权码错误。请确认 QQ_AUTH_CODE 是授权码而不是 QQ 密码。")
        print("   获取方式：QQ邮箱 → 设置 → 账户 → POP3/SMTP服务 → 开启 → 复制授权码")
    except smtplib.SMTPException as e:
        print(f"❌ SMTP 错误：{e}")
    except Exception as e:
        print(f"❌ 发送失败：{e}")


if __name__ == "__main__":
    main()
