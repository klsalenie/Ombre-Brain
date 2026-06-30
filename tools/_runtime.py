"""
========================================
tools/_runtime.py — 工具模块共享的运行时上下文
========================================

这个文件解决一个工程问题：拆分后每个工具子模块都需要访问
config / bucket_mgr / dehydrator / decay_engine / embedding_engine /
logger 这些 server.py 创建的全局对象，但子模块不能反向 import
server.py（会循环 import）。

做法：server.py 在初始化所有组件后调用 init(...) 把引用塞进来；
工具模块全部 `from . import _runtime as rt` 然后用 `rt.bucket_mgr` 即可。

关键行为：
- 提供一个轻量级容器，保存共享对象的引用
- init() 一次性写入；后续工具模块直接读，不修改

不做什么（边界）：
- 不创建任何对象，不做配置加载，不做日志初始化
- 不做线程安全保护：写入只发生在 server.py 启动期，单次

对外暴露：init() / config / bucket_mgr / dehydrator / decay_engine /
         embedding_engine / import_engine / logger / fire_webhook / mark_op
========================================
"""

from typing import Any, Awaitable, Callable, Optional, TypeVar

from ombrebrain.app.execution import ExecutionEnvelope

T = TypeVar("T")

# --- 共享对象引用，由 server.py 在启动时通过 init(...) 注入 ---
config: Any = None
bucket_mgr: Any = None
dehydrator: Any = None
decay_engine: Any = None
embedding_engine: Any = None
import_engine: Any = None
logger: Any = None
v3_runtime: Any = None

# --- 共享辅助回调（也由 server.py 注入，避免反向 import）---
fire_webhook: Optional[Callable[[str, dict], Awaitable[None]]] = None
mark_op: Optional[Callable[..., None]] = None


def init(**kwargs: Any) -> None:
    """server.py 在创建好所有组件后调用一次，把引用写到本模块全局上。
    测试 fixture 可以再次调用本函数覆盖个别字段，行为同 monkeypatch。"""
    g = globals()
    for k, v in kwargs.items():
        g[k] = v


def run_v3_capability(
    name: str,
    payload: object,
    *,
    permissions: tuple[str, ...],
    actor_name: str,
    source: str,
) -> object | None:
    runtime = globals().get("v3_runtime")
    if runtime is None:
        return None
    try:
        return runtime.dispatch_capability(
            name,
            payload,
            permissions=tuple(permissions),
            actor_name=actor_name,
            source=source,
        )
    except Exception as e:
        if logger is not None:
            logger.warning(f"v2.4.0 capability dispatch failed for {name}: {e}")
        return None


def record_v3_tool_event(tool_name: str, payload: dict[str, object] | None = None) -> int | None:
    runtime = globals().get("v3_runtime")
    if runtime is None or not hasattr(runtime, "record_tool_event"):
        return None
    event_payload = _with_v3_command_plan(tool_name, payload or {})
    try:
        return runtime.record_tool_event(tool_name, event_payload)
    except Exception as e:
        if logger is not None:
            logger.warning(f"v2.4.0 tool event record failed for {tool_name}: {e}")
        return None


def _with_v3_command_plan(tool_name: str, payload: dict[str, object]) -> dict[str, object]:
    runtime = globals().get("v3_runtime")
    enriched = dict(payload)
    planner = getattr(runtime, "plan_legacy_command", None)
    if not callable(planner):
        return enriched
    try:
        envelope = ExecutionEnvelope(
            module=f"tools.{tool_name}",
            operation=str(tool_name),
            payload=enriched,
            actor_name="legacy-tool",
            source="tools.record_v3_tool_event",
            permissions=("mcp:call",),
        )
        plan = planner(envelope)
        to_dict = getattr(plan, "to_dict", None)
        enriched["command_plan"] = to_dict() if callable(to_dict) else plan
    except Exception as e:
        if logger is not None:
            logger.warning(f"v2.4.0 command plan failed for tool {tool_name}: {e}")
    return enriched


def run_v3_operation(
    operation: str,
    payload: dict[str, object] | None,
    handler: Callable[[], T],
    *,
    module: str = "tools",
    permissions: tuple[str, ...] = ("mcp:call",),
    actor_name: str = "legacy-tool",
    source: str = "tools",
    writes_memory: bool = False,
) -> T:
    runtime = globals().get("v3_runtime")
    if runtime is None or not hasattr(runtime, "run_operation"):
        return handler()

    envelope = ExecutionEnvelope(
        module=module,
        operation=operation,
        payload=payload or {},
        actor_name=actor_name,
        source=source,
        permissions=permissions,
        writes_memory=writes_memory,
    )
    handler_called = False

    def guarded_handler() -> T:
        nonlocal handler_called
        handler_called = True
        return handler()

    try:
        return runtime.run_operation(envelope, guarded_handler)
    except Exception as e:
        if handler_called:
            raise
        if logger is not None:
            logger.warning(f"v2.4.0 tool operation wrapper failed for {module}.{operation}: {e}")
        return handler()


async def run_v3_async_operation(
    operation: str,
    payload: dict[str, object] | None,
    handler: Callable[[], Awaitable[T]],
    *,
    module: str = "tools",
    permissions: tuple[str, ...] = ("mcp:call",),
    actor_name: str = "legacy-tool",
    source: str = "tools",
    writes_memory: bool = False,
) -> T:
    runtime = globals().get("v3_runtime")
    if runtime is None or not hasattr(runtime, "run_async_operation"):
        return await handler()

    envelope = ExecutionEnvelope(
        module=module,
        operation=operation,
        payload=payload or {},
        actor_name=actor_name,
        source=source,
        permissions=permissions,
        writes_memory=writes_memory,
    )
    handler_called = False

    async def guarded_handler() -> T:
        nonlocal handler_called
        handler_called = True
        return await handler()

    try:
        return await runtime.run_async_operation(envelope, guarded_handler)
    except Exception as e:
        if handler_called:
            raise
        if logger is not None:
            logger.warning(f"v2.4.0 async tool operation wrapper failed for {module}.{operation}: {e}")
        return await handler()
