import os
from typing import Any

from runner.executor_registry import (
    DEFAULT_EXECUTION_PROVIDER,
    is_supported_execution_provider,
    get_executor_provider_display,
)
from runner.runner_settings import RunnerSettings, RunnerSettingsStore
from schemas.plan import BuildRunnerPlan, BuildVersion


def resolve_version_execution_provider(
    *,
    plan: BuildRunnerPlan,
    version: BuildVersion | None,
    fallback_provider: str,
) -> str:
    if version is not None and version.execution is not None:
        vp = version.execution.provider
        if vp and is_supported_execution_provider(vp):
            return vp
    me = plan.model_execution
    if me and me.provider and is_supported_execution_provider(me.provider):
        return me.provider
    if is_supported_execution_provider(fallback_provider):
        return fallback_provider
    return DEFAULT_EXECUTION_PROVIDER


def load_runner_settings_for_project(project_root: str) -> RunnerSettings:
    runner_dir = resolve_project_runner_dir(project_root)
    plan_file = os.path.join(runner_dir, "plan.json")
    return RunnerSettingsStore().load_for_project(project_root, plan_file)


def resolve_version_execution_model(
    *,
    plan: BuildRunnerPlan,
    version: BuildVersion | None,
    provider: str,
    settings: RunnerSettings | None = None,
) -> str | None:
    provider_key = provider.strip().lower()
    if provider_key not in ("pi", "codex", "opencode"):
        return None

    def str_val(v: Any) -> str | None:
        return v.strip() if isinstance(v, str) and v.strip() else None

    def v_field(name: str) -> str | None:
        if version is not None and version.execution is not None:
            return str_val(getattr(version.execution, name, None))
        return None

    def p_field(name: str) -> str | None:
        if plan.model_execution is not None:
            return str_val(getattr(plan.model_execution, name, None))
        return None

    if provider_key == "opencode":
        model = v_field("opencode_model") or v_field("model") or v_field("model_name")
        if model:
            return model
        model = _profile_model_for_provider(settings, provider_key)
        if model:
            return model
        return p_field("opencode_model") or p_field("model") or p_field("model_name") or p_field("model_command")

    if provider_key == "codex":
        model = v_field("codex_model") or v_field("model") or v_field("model_name")
        if model:
            return model
        model = _profile_model_for_provider(settings, provider_key)
        if model:
            return model
        return p_field("codex_model") or p_field("model") or p_field("model_name") or p_field("model_command")

    model = v_field("pi_model") or v_field("model") or v_field("model_name")
    if model:
        return model
    model = _profile_model_for_provider(settings, provider_key)
    if model:
        return model
    return p_field("pi_model") or p_field("model") or p_field("model_name") or p_field("model_command")


def resolve_execution_reasoning_effort(
    *,
    provider: str,
    settings: RunnerSettings | None = None,
) -> str | None:
    provider_key = provider.strip().lower()
    if provider_key not in ("pi", "codex", "opencode"):
        return None
    if settings is None or settings.executor_profile is None:
        return None
    profile = settings.executor_profile
    if (
        profile.reasoning_effort
        and profile.provider
        and profile.provider.strip().lower() == provider_key
    ):
        return profile.reasoning_effort.strip()
    return None


def _profile_model_for_provider(
    settings: RunnerSettings | None,
    provider: str,
) -> str | None:
    if settings is None or settings.executor_profile is None:
        return None
    profile = settings.executor_profile
    if profile.model and profile.provider and profile.provider.strip().lower() == provider.strip().lower():
        return profile.model
    return None


def get_version_execution_summary(
    *,
    plan: BuildRunnerPlan,
    version: BuildVersion | None,
    fallback_provider: str,
    settings: RunnerSettings | None = None,
) -> dict[str, Any]:
    provider = resolve_version_execution_provider(
        plan=plan, version=version, fallback_provider=fallback_provider,
    )
    model = resolve_version_execution_model(
        plan=plan, version=version, provider=provider, settings=settings,
    )
    source = "settings"
    if version is not None and version.execution is not None:
        exec_fields = (
            version.execution.provider, version.execution.model, version.execution.model_name,
            version.execution.pi_model, version.execution.codex_model,
            version.execution.opencode_model, version.execution.lane,
            version.execution.capability_level, version.execution.notes,
        )
        if any(f is not None for f in exec_fields):
            source = "version"
    if source == "settings" and plan.model_execution is not None:
        plan_fields = (
            plan.model_execution.provider, plan.model_execution.model,
            plan.model_execution.model_name, plan.model_execution.pi_model,
            plan.model_execution.codex_model, plan.model_execution.opencode_model,
            plan.model_execution.model_command,
        )
        if any(f is not None for f in plan_fields):
            source = "plan"

    lane: str | None = None
    capability_level: str | None = None
    if version is not None and version.execution is not None:
        if version.execution.lane:
            lane = version.execution.lane
        if version.execution.capability_level:
            capability_level = version.execution.capability_level

    return {
        "provider": provider,
        "provider_display": get_executor_provider_display(provider),
        "model": model,
        "model_display": model if model else "默认模型",
        "source": source,
        "lane": lane,
        "capability_level": capability_level,
    }
from runner.runner_paths import resolve_project_runner_dir
