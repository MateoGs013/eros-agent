"""Registro en memoria de tareas largas (escaneo, evaluación en lote, artículos) que la API corre en segundo plano."""

import asyncio
import logging
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


class TaskError(RuntimeError):
    """Falla de una tarea con un código estable para el cliente (va en `error_code`)."""

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


class TaskRegistry:
    """Corre una tarea por tipo a la vez y guarda su estado para consultarlo por id.

    El estado vive en memoria del proceso: si Eros se reinicia, los ids anteriores
    dejan de existir (GET responde 404) y la tarea en curso se pierde.
    """

    def __init__(self, max_tasks: int = 100):
        self._tasks: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._handles: dict[str, asyncio.Task] = {}
        self._max_tasks = max_tasks

    def get(self, task_id: str) -> dict[str, Any] | None:
        task = self._tasks.get(task_id)
        return dict(task) if task else None

    def running(self, kind: str) -> dict[str, Any] | None:
        for task in reversed(self._tasks.values()):
            if task["kind"] == kind and task["status"] == "running":
                return dict(task)
        return None

    def latest(self, kind: str) -> dict[str, Any] | None:
        for task in reversed(self._tasks.values()):
            if task["kind"] == kind:
                return dict(task)
        return None

    def start(self, kind: str, job: Callable[[], Awaitable[Any]]) -> tuple[dict[str, Any], bool]:
        """Arranca `job` en segundo plano. Si ya hay una del mismo tipo corriendo, devuelve esa.

        Devuelve (tarea, creada). El chequeo y el alta ocurren sin await en el medio,
        así que dos pedidos simultáneos no arrancan dos tareas.
        """
        current = self.running(kind)
        if current:
            return current, False

        task_id = f"{kind}_{uuid.uuid4().hex[:12]}"
        entry: dict[str, Any] = {
            "task_id": task_id,
            "kind": kind,
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "result": None,
            "error": None,
            "error_code": None,
        }
        self._tasks[task_id] = entry
        self._trim()

        async def runner() -> None:
            try:
                entry["result"] = await job()
                entry["status"] = "done"
            except Exception as e:
                logger.error(f"Tarea {task_id} ({kind}) falló: {e}")
                entry["status"] = "failed"
                entry["error"] = str(e) or e.__class__.__name__
                # TaskError (o cualquier excepción con `code`) deja un código estable además del mensaje
                code = getattr(e, "code", None)
                entry["error_code"] = code if isinstance(code, str) else None
            finally:
                entry["finished_at"] = datetime.now(timezone.utc).isoformat()
                self._handles.pop(task_id, None)

        self._handles[task_id] = asyncio.create_task(runner())
        return dict(entry), True

    def _trim(self) -> None:
        while len(self._tasks) > self._max_tasks:
            oldest_id, oldest = next(iter(self._tasks.items()))
            if oldest["status"] == "running":
                break
            self._tasks.pop(oldest_id)
