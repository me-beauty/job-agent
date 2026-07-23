#!/usr/bin/env python3
"""自动投递 — 求职业务插件"""

import asyncio
import json
from pathlib import Path

from engine.browser_controller import BrowserController
from engine.llm_factory import create_llm
from utils.logger import get_logger

logger = get_logger("business.apply")

RESUME_TEMPLATE_PATH = Path(__file__).parent.parent / "resume_template.json"


async def apply_job_async(
    job_url: str,
    resume_path: str = None,
    applicant_info: dict = None,
    llm_provider: str = None,
) -> dict:
    """异步自动投递（默认不提交，仅确认填写）"""
    llm = create_llm(llm_provider)

    # Load resume template
    info = {}
    if RESUME_TEMPLATE_PATH.exists():
        info = json.loads(RESUME_TEMPLATE_PATH.read_text(encoding="utf-8"))
    if applicant_info:
        for k, v in applicant_info.items():
            if k in info and isinstance(info[k], dict): info[k].update(v)
            else: info[k] = v

    personal = info.get("personal", {})
    education = info.get("education", {})
    info_text = json.dumps(info, ensure_ascii=False, indent=2)
    has_resume = resume_path and Path(resume_path).exists()

    task = f"""你是求职助手，帮我填写实习岗位申请（仅确认，不提交）。

岗位链接: {job_url}
我的信息: {info_text}
{'简历: ' + resume_path if has_resume else ''}

步骤:
1. 打开链接，等页面加载
2. 逐个填写表单字段: 姓名={personal.get('last_name','')}{personal.get('first_name','')}, 邮箱={personal.get('email','')}, 电话={personal.get('phone','')}
3. 填写学校={education.get('school','')}, 专业={education.get('major','')}
4. 如有简历上传: {'上传 ' + resume_path if has_resume else '手填技能'}
5. 截图确认，不要提交。
6. final_result 报告哪些字段成功、哪些失败。"""

    ctrl = BrowserController(llm_provider=llm_provider)
    try:
        result = await ctrl.run_agent(task, llm=llm)
        return {"success": True, "detail": result.get("final_result", ""), "url": job_url}
    except Exception as e:
        logger.error(f"Apply failed: {e}")
        return {"success": False, "message": str(e), "url": job_url}
    finally:
        ctrl.teardown()


def apply_job_sync(job_url, resume_path=None, applicant_info=None, llm_provider=None) -> dict:
    try:
        loop = asyncio.get_running_loop()
        return loop.run_until_complete(apply_job_async(job_url, resume_path, applicant_info, llm_provider))
    except RuntimeError:
        return asyncio.run(apply_job_async(job_url, resume_path, applicant_info, llm_provider))
