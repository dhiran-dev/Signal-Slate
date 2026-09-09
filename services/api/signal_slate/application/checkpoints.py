"""Request-scoped checkpoint hook; no global workflow or visitor state."""

from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

workflow_checkpoint: ContextVar[Callable[[dict[str, Any]], None] | None] = ContextVar(
    "workflow_checkpoint", default=None
)
publication_store: ContextVar[Any] = ContextVar("publication_store", default=None)


def save_workflow(data: dict[str, Any]) -> None:
    callback = workflow_checkpoint.get()
    if callback:
        callback(data)
