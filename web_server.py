#!/usr/bin/env python3
"""
Job Agent Web — Flask dashboard v3.2 (interview-demo optimized).
Backend: all 28 API routes unchanged. Frontend only.
"""

import datetime, io, os, re, secrets, sys, threading
from pathlib import Path

# 禁用 .pyc 字节码缓存，避免旧缓存导致代码不生效
# 必须在 Python 启动时通过 PYTHONDONTWRITEBYTECODE=1 设置
# 如果未设置，打印警告
if not os.environ.get("PYTHONDONTWRITEBYTECODE"):
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    # 注意：上面的设置在 import 前必须生效，所以请在启动脚本中设置
    # set PYTHONDONTWRITEBYTECODE=1  或  export PYTHONDONTWRITEBYTECODE=1

from flask import Flask, abort, jsonify, request, send_from_directory, session
from dotenv import load_dotenv
load_dotenv()

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="ignore")

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
ROOT = Path(__file__).parent

from db import init_db, get_db
from utils.logger import get_logger
from utils.rate_limiter import get_limiter

init_db()

logger = get_logger("web_server")

AUTH_TOKEN = os.environ.get("JOB_AGENT_TOKEN", "job-agent-demo-token")
PUBLIC_PREFIXES = ["/", "/report/", "/files/", "/login", "/logout", "/static/"]

# ============================================================
# Auth + Rate limit middleware
# ============================================================
@app.before_request
def check_auth_and_rate():
    path = request.path
    for prefix in PUBLIC_PREFIXES:
        if path.startswith(prefix) or path == prefix.rstrip("/"): return None
    if path.startswith("/api/"):
        ah = request.headers.get("Authorization", "")
        if ah.startswith("Bearer ") and ah[7:] == AUTH_TOKEN: pass
        elif request.args.get("token") == AUTH_TOKEN: pass
        elif session.get("authenticated"): pass
        else: return jsonify({"error":"未授权","message":"请提供 Bearer Token"}), 401
        limiter = get_limiter(path)
        if not limiter.consume():
            return jsonify({"error":"请求过于频繁","message":"请稍后再试"}), 429
    return None

@app.errorhandler(404)
def not_found(e): return jsonify({"error":"资源不存在"}), 404
@app.errorhandler(500)
def server_error(e): return jsonify({"error":"服务器内部错误"}), 500

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        if request.form.get("token","") == AUTH_TOKEN:
            session["authenticated"] = True
            return """<script>alert('登录成功！');location.href='/'</script>"""
        return """<script>alert('Token 错误');history.back()</script>"""
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><title>登录</title>
<style>body{{font-family:'Microsoft YaHei',sans-serif;background:#f0f2f5;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}}
.box{{background:#fff;padding:32px 40px;border-radius:14px;box-shadow:0 4px 24px rgba(0,0,0,.08);max-width:380px;width:100%}}
h2{{margin:0 0 8px}}p{{margin:0 0 20px;color:#888;font-size:13px}}
input{{width:100%;padding:10px;border:1px solid #ddd;border-radius:8px;font-size:14px;box-sizing:border-box;margin-bottom:12px}}
button{{width:100%;padding:10px;background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;border:none;border-radius:8px;font-size:14px;cursor:pointer;font-weight:600}}
.hint{{font-size:11px;color:#aaa;margin-top:12px;text-align:center}}</style></head><body>
<div class="box"><h2>🔐 登录</h2><p>输入 API Token 以使用操作功能</p>
<form method="post"><input type="password" name="token" placeholder="请输入 Token" autofocus><button type="submit">登 录</button></form>
<div class="hint">默认 Token: <code>{AUTH_TOKEN}</code></div></div></body></html>"""

@app.route("/logout")
def logout():
    session.pop("authenticated", None)
    return """<script>alert('已退出');location.href='/'</script>"""

# ---- Blueprints --------------------------------------------------------------
try:
    from business.web_api import api_bp; app.register_blueprint(api_bp); API_LOADED = True
except Exception as e:
    API_LOADED = False; logger.warning(f"api_bp not loaded: {e}")

TF_MODEL_READY = False  # torch disabled — module not loaded

# ============================================================
# CSS & Templates
# ============================================================
PAGE_HEAD = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Job Agent — 智能求职系统</title><style>
:root{--bg:#f0f2f5;--card:#fff;--text:#1a1a2e;--muted:#8a8fa0;--purple1:#667eea;--purple2:#764ba2;--green:#22c55e;--red:#ef4444;--amber:#f59e0b;--blue:#3b82f6;--radius:14px;--shadow:0 2px 12px rgba(0,0,0,.06)}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Microsoft YaHei','PingFang SC',system-ui,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;line-height:1.5}
.container{max-width:1024px;margin:0 auto;padding:16px 20px}
/* Header */
.header{background:linear-gradient(135deg,var(--purple1),var(--purple2));color:#fff;padding:24px 32px;border-radius:var(--radius);margin-bottom:20px;position:relative;overflow:hidden}
.header::after{content:'';position:absolute;right:-30px;top:-30px;width:160px;height:160px;background:rgba(255,255,255,.06);border-radius:50%}
.header h1{font-size:26px;font-weight:800;position:relative;z-index:1}
.header .sub{font-size:14px;opacity:.85;margin-top:6px;position:relative;z-index:1}
.header .tag-row{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px;position:relative;z-index:1}
.header .tag{background:rgba(255,255,255,.18);border-radius:20px;padding:4px 14px;font-size:11px;backdrop-filter:blur(4px)}
/* Cards */
.card{background:var(--card);border-radius:var(--radius);padding:20px 24px;margin-bottom:16px;box-shadow:var(--shadow);transition:transform .15s}
.card-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;padding-bottom:10px;border-bottom:2px solid #f0f1f5}
.card-header h2{font-size:16px;font-weight:700}
.card-header .desc{font-size:12px;color:var(--muted)}
.card h3{font-size:14px;margin:14px 0 8px;color:#555;font-weight:600}
/* Stat grid */
.stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:8px}
.stat-card{background:var(--card);border-radius:var(--radius);padding:18px 20px;box-shadow:var(--shadow);text-align:center;position:relative;overflow:hidden}
.stat-card::before{content:'';position:absolute;top:0;left:0;right:0;height:3px}
.stat-card.n1::before{background:var(--purple1)}.stat-card.n2::before{background:var(--blue)}.stat-card.n3::before{background:var(--green)}.stat-card.n4::before{background:var(--amber)}.stat-card.n5::before{background:var(--red)}.stat-card.n6::before{background:var(--purple2)}
.stat-card .num{font-size:32px;font-weight:800;color:var(--text)}
.stat-card .label{font-size:12px;color:var(--muted);margin-top:4px}
.stat-card .warn{font-size:10px;color:var(--amber);margin-top:2px}
/* Monitor panels: bar chart */
.monitor-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}
.mini-card{background:#f8f9fc;border-radius:12px;padding:14px 16px}
.mini-card .mc-title{font-size:13px;font-weight:700;margin-bottom:10px;color:#444}
.bar-row{display:flex;align-items:center;gap:8px;margin-bottom:6px}
.bar-label{font-size:10px;color:var(--muted);width:48px;text-align:right;flex-shrink:0}
.bar-track{flex:1;height:18px;background:#e8ecf1;border-radius:9px;overflow:hidden}
.bar-fill{height:100%;border-radius:9px;transition:width .6s;min-width:2px;display:flex;align-items:center;justify-content:flex-end;padding-right:5px;font-size:9px;color:#fff;font-weight:600}
.bar-fill.low{background:linear-gradient(90deg,#a0aec0,#cbd5e1);color:#555}
.bar-fill.mid{background:linear-gradient(90deg,#3b82f6,#60a5fa)}
.bar-fill.high{background:linear-gradient(90deg,#22c55e,#4ade80)}
.bar-fill.top{background:linear-gradient(90deg,#f59e0b,#fbbf24)}
/* Tool call table */
.tc-table{width:100%;font-size:11px;border-collapse:collapse}
.tc-table th{background:#f0f2f5;padding:6px 8px;text-align:left;font-size:10px;color:var(--muted);border:1px solid #e8ecf1}
.tc-table td{padding:5px 8px;border:1px solid #e8ecf1;font-size:10px}
.tc-ok{color:var(--green);font-weight:600}
.tc-fail{color:var(--red);font-weight:600}
/* Collapsible */
.collapse-trigger{cursor:pointer;user-select:none;display:flex;align-items:center;gap:8px;padding:10px 16px;background:#f0f2f5;border-radius:10px;font-size:13px;font-weight:600;color:var(--muted);margin-bottom:10px}
.collapse-trigger:hover{background:#e8ecf1}
.collapse-body{display:none;margin-bottom:14px}
.collapse-body.open{display:block}
/* Buttons */
.btn{display:inline-flex;align-items:center;gap:6px;padding:8px 16px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;border:none;text-decoration:none;transition:all .15s}
.btn-primary{background:linear-gradient(135deg,var(--purple1),var(--purple2));color:#fff}
.btn-primary:hover{opacity:.9;transform:translateY(-1px)}
.btn-ghost{background:#fff;color:var(--purple1);border:1px solid #e0e0e0}
.btn-ghost:hover{background:#f8f9fc}
.btn-sm{font-size:10px;padding:4px 10px}
/* Badges */
.badge{display:inline-block;border-radius:10px;padding:2px 10px;font-size:10px;font-weight:600;white-space:nowrap}
.badge-prec{background:#e8eaf6;color:#3949ab}.badge-quick{background:#fff3e0;color:#e65100}
.badge-ok{background:#dcfce7;color:#166534}.badge-err{background:#fecdd3;color:#991b1b}.badge-run{background:#fef9c3;color:#92400e}.badge-pend{background:#e0e0e0;color:#666}
.badge-active{background:#dcfce7;color:#166534}
/* Forms */
.frm-group{display:flex;flex-direction:column;gap:8px}
.frm-input{padding:8px 10px;border:1px solid #ddd;border-radius:8px;font-size:12px;outline:none;transition:border .15s}
.frm-input:focus{border-color:var(--purple1)}
.frm-row{display:flex;gap:8px}
.frm-row .frm-input{flex:1}
textarea.frm-input{resize:vertical}
/* Report list */
.report-row{display:flex;align-items:center;justify-content:space-between;padding:10px 0;border-bottom:1px solid #f0f1f5;gap:12px}
.report-row:last-child{border-bottom:none}.report-row .name a{color:var(--text);text-decoration:none;font-size:14px;font-weight:500}.report-row .name a:hover{color:var(--purple1)}.report-row .size{font-size:11px;color:var(--muted);white-space:nowrap}
.empty-state{text-align:center;padding:30px 20px;color:var(--muted);font-size:13px}
.footer{text-align:center;font-size:11px;color:#bbb;padding:24px 0}
/* Responsive */
@media(max-width:640px){.container{padding:8px 10px}.header{padding:18px 16px}.header h1{font-size:20px}.stat-grid{grid-template-columns:repeat(2,1fr)}.monitor-grid{grid-template-columns:1fr}}
</style></head><body><div class="container">
"""

PAGE_FOOT = """<div class="footer">🤖 Job Agent v3.3 · 计算机技术实习求职助手 · {year}</div></div></body></html>"""

def _header(title, subtitle=None):
    h = PAGE_HEAD
    h += f'<div class="header"><h1>{title}</h1>'
    if subtitle: h += f'<div class="sub">{subtitle}</div>'
    h += '<div class="tag-row"><span class="tag">📡 4数据源</span><span class="tag">🧠 PyTorch</span><span class="tag">🔍 ChromaDB</span><span class="tag">🌐 Browser</span><span class="tag">🔌 MCP</span></div></div>'
    return h

def _footer(): return PAGE_FOOT.format(year=datetime.date.today().year)

def md_to_html(md_text):
    import markdown as md_lib
    h = md_lib.markdown(md_text, extensions=["tables","fenced_code","codehilite"])
    h = h.replace("✅",'<span style="color:#2e7d32;font-weight:600">✅</span>').replace("❌",'<span style="color:#ccc">—</span>')
    for s,c in [("⭐⭐⭐","#f57f17"),("⭐⭐","#3949ab"),("⭐","#999")]:
        bg={"#f57f17":"#fff9c4","#3949ab":"#e8eaf6","#999":"#f5f5f5"}[c]
        h=h.replace(s,f'<span style="display:inline-block;background:{bg};color:{c};border-radius:8px;padding:1px 8px;font-size:10px;font-weight:600">{s}</span>')
    return re.sub(r"(<blockquote>\s*)<p>",r"\1<p>💡 ",h)

# ============================================================
# DASHBOARD (redesigned v3.2)
# ============================================================
@app.route("/")
def index():
    today = datetime.date.today(); today_str = str(today)
    host = request.host_url.rstrip("/")
    reports = []
    for f in sorted(ROOT.glob("daily_report_*.md"), reverse=True):
        s=f.stat();n=f.name
        m=re.search(r"(\d{4}-\d{2}-\d{2})",n)
        reports.append({"name":n,"date":m.group(1) if m else "-","size":f"{s.st_size/1024:.1f} KB",
                        "is_today":(m.group(1) if m else "")==today_str})
    try:
        db=get_db(); job_total=db.job_count(); model_count=db.get_model_count()
    except Exception: job_total=model_count=0
    model_ready = bool(list((ROOT/"model/model_storage").glob("*.pt")))

    template_path = ROOT / "_index_template.html"
    if not template_path.exists():
        return "<h1>Error: _index_template.html not found</h1>"

    html = template_path.read_text(encoding="utf-8")

    # Simple replacements
    html = html.replace("{job_total}", str(job_total))
    html = html.replace("{model_count}", str(model_count))
    html = html.replace("{report_count}", str(len(reports)))
    html = html.replace("{model_ready}", "OK" if model_ready else "MISSING")
    html = html.replace("{model_ready_color}", "#22c55e" if model_ready else "#e65100")

    report_rows = ""
    for r in reports[:8]:
        tm = '<span style="font-size:11px;color:var(--purple)"> ● 今天</span>' if r["is_today"] else ""
        report_rows += f'<div class="report-row"><a href="/report/{r["name"]}">{r["name"]}{tm}</a><span>{r["size"]}</span></div>'
    html = html.replace("{report_rows}", report_rows or '<div class="empty-state">暂无日报</div>')

    try:
        am = db.get_active_model()
        if am:
            am_text = f'{am.get("name","?")} | MAE:{am.get("val_mae",0):.0f} | Acc:{am.get("accuracy",0):.1%}'
        else:
            am_text = "未找到激活模型"
    except Exception:
        am_text = "未找到"
    html = html.replace("{active_model}", am_text)

    return html

def view_report(filename):
    fp = (ROOT/filename).resolve()
    if not str(fp).startswith(str(ROOT.resolve())): abort(403)
    if not fp.exists() or not fp.is_file(): abort(404)
    raw = fp.read_text(encoding="utf-8")
    m = re.search(r"(\d{4}-\d{2}-\d{2})", filename)
    date = m.group(1) if m else filename
    mode_str = "⚡ 快速模式" if "_自动版" in filename else "🎯 精准模式"
    html = _header(filename, f"{mode_str} · {date}")
    html += '<div class="card">'+md_to_html(raw)+'</div>'
    html += f'<div style="display:flex;gap:10px;margin-bottom:20px"><a href="/" class="btn btn-ghost">← 返回首页</a><a href="/files/{filename}" class="btn btn-ghost" download>📥 下载原始 MD</a></div>'
    html += _footer(); return html

@app.route("/files/<path:filename>")
def serve_file(filename): return send_from_directory(str(ROOT), filename, as_attachment=True)

# ============================================================
@app.route("/api/train_match_model", methods=["POST"])
def api_train_model():
    data = request.get_json(silent=True) or {}
    epochs = int(data.get("epochs", 25)); lr = float(data.get("lr", 3e-3))
    task_id = f"train_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    db = get_db(); db.add_task(task_id, "train", "running", {"epochs":epochs,"lr":lr})
    from engine.priority_queue import get_queue, TYPE_PRIORITY_MAP

    def _train_task(e, lr):
        import traceback
        from business.train_model import train_model
        result = train_model(epochs=e, lr=lr)
        db.update_task(task_id, "done", result)
        db.add_model({"name":result.get("model_name",task_id),"path":result.get("model_path",""),
                      "epochs":result.get("epochs",0),"val_mae":result.get("val_mae",0),
                      "val_loss":result.get("val_loss",0),"accuracy":result.get("accuracy",0),"is_active":1})
        return result

    get_queue().enqueue_by_type(task_id, "train", _train_task, epochs, lr)
    return jsonify({"task_id":task_id,"status":"started",
                    "message":f"训练已启动 (epochs={epochs}, lr={lr})。约2-3分钟。通过 /api/task/{task_id} 查询进度"}), 202


@app.route("/api/calculate_match_score", methods=["POST"])
def api_calculate_score():
    data = request.get_json(silent=True) or {}
    resume = data.get("resume_text","").strip()
    if not resume: return jsonify({"error":"resume_text 参数不能为空"}), 400
    jobs = data.get("jobs",[])
    if not jobs: return jsonify({"error":"无岗位数据，请传入 jobs 参数"}), 400
    try:
        from business.match_scorer import rank_jobs as _rank
        results = _rank(resume, jobs, min_score=0)
        scores = [{"job_id":r.get("title",r.get("id",str(i))),"company":r.get("company",""),"score":r["match_score"],"stars":r["stars"],"tier":r["tier"],"auto_apply":r["auto_apply"]} for i,r in enumerate(results)]
        return jsonify({"scores":scores,"count":len(scores)})
    except ImportError:
        from model.inference import _fallback_score
        scores=[{"job_id":j.get("title",""),"company":j.get("company",""),"score":_fallback_score(resume,f"{j.get('title','')} {j.get('company','')} {j.get('description') or j.get('desc','')}"),"stars":"⭐"} for j in jobs]
        return jsonify({"scores":scores,"count":len(scores),"mode":"fallback"})

@app.route("/api/models", methods=["GET"])
def api_list_models():
    try: return jsonify({"models":get_db().list_models(),"count":get_db().get_model_count()})
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/api/models/switch", methods=["POST"])
def api_switch_model():
    data=request.get_json(silent=True) or {}; name=data.get("name","").strip()
    if not name: return jsonify({"error":"model 名称不能为空"}),400
    try: get_db().set_active_model(name); return jsonify({"status":"ok","message":f"Active model set to {name}"})
    except Exception as e: return jsonify({"error":str(e)}),500

# ============================================================
# Startup
# ============================================================
if __name__ == "__main__":
    logger.info("Web v3.2: http://127.0.0.1:5000")
    print(f"Job Agent v3.2: http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)
