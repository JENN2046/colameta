from __future__ import annotations

from typing import Any


def extract_model_display_from_plan_data(plan_data: dict[str, Any] | None) -> str:
    """从 plan.json 内容提取模型展示文案。"""
    model_display = "默认模型"
    if not isinstance(plan_data, dict):
        return model_display

    model_execution = plan_data.get("model_execution")
    if isinstance(model_execution, dict):
        raw_model = (
            model_execution.get("model")
            or model_execution.get("model_name")
            or model_execution.get("codex_model")
            or model_execution.get("pi_model")
            or model_execution.get("model_command")
        )
        if isinstance(raw_model, str) and raw_model.strip():
            return raw_model.strip()

    fallback_model = plan_data.get("model")
    if isinstance(fallback_model, str) and fallback_model.strip():
        return fallback_model.strip()
    return model_display


def build_execution_display(*, provider: str, provider_display: str, model_display: str) -> dict[str, str]:
    """组装执行器展示字段。"""
    return {
        "provider": str(provider or "").strip(),
        "provider_display": str(provider_display or "").strip(),
        "model_display": str(model_display or "默认模型").strip() or "默认模型",
    }


def build_executor_session_display(
    *,
    executor_session_status: dict[str, Any] | None,
    continuation_decision: dict[str, Any] | None,
    resume_invocation_preview: dict[str, Any] | None,
    continuation_preview: dict[str, Any] | None,
) -> dict[str, Any]:
    """根据统一续接字段生成会话展示状态。"""
    session = executor_session_status if isinstance(executor_session_status, dict) else {}
    decision = continuation_decision if isinstance(continuation_decision, dict) else {}
    invocation = resume_invocation_preview if isinstance(resume_invocation_preview, dict) else {}
    preview = continuation_preview if isinstance(continuation_preview, dict) else {}
    eligibility = session.get("eligibility") if isinstance(session.get("eligibility"), dict) else {}
    head_mismatch = session.get("head_mismatch_classification")
    if not isinstance(head_mismatch, dict):
        head_mismatch = decision.get("head_mismatch_classification")
    if not isinstance(head_mismatch, dict):
        head_mismatch = preview.get("head_mismatch_classification")
    if not isinstance(head_mismatch, dict):
        head_mismatch = invocation.get("head_mismatch_classification")
    if not isinstance(head_mismatch, dict):
        head_mismatch = {}
    head_mismatch_status = str(head_mismatch.get("status") or "none")

    text = "执行会话：未记录"
    state = "untracked"

    if head_mismatch_status == "active_operation_head_mismatch":
        text = "执行会话：HEAD 不一致（运行中）"
        state = "blocked"
    elif head_mismatch_status == "completed_idle_stale_session":
        text = "执行会话：历史会话残留（HEAD 不一致，未在执行）"
        state = "stale_session"
    elif head_mismatch_status == "unknown_head_mismatch":
        text = "执行会话：HEAD 不一致（证据不足）"
        state = "blocked"
    elif session.get("active") is True:
        if decision.get("should_resume") is True:
            text = "执行会话：可继续"
            state = "resumable"
        elif decision.get("decision") == "resume_auto_eligible":
            text = "执行会话：可继续"
            state = "resumable"
        elif invocation.get("will_execute") is True:
            text = "执行会话：可继续"
            state = "resumable"
        elif decision.get("continuation_available") is False:
            text = "执行会话：不可继续"
            state = "not_resumable"
        elif preview.get("continuation_available") is True:
            text = "执行会话：可继续"
            state = "resumable"
        elif eligibility.get("preferred_continuation_available") is True:
            text = "执行会话：可继续"
            state = "resumable"
        elif eligibility.get("resume_eligible") is True:
            text = "执行会话：可继续"
            state = "resumable"
        elif "resume_eligible" in eligibility:
            text = "执行会话：不可继续"
            state = "not_resumable"
        else:
            text = "执行会话：已记录（未确认可继续）"
            state = "recorded"

    return {
        "text": text,
        "state": state,
        "resumable": state == "resumable",
        "head_mismatch_classification_status": head_mismatch_status,
        "head_mismatch_operator_message": str(head_mismatch.get("operator_message") or ""),
    }
