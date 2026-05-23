from typing import Any

from celery.result import AsyncResult
from fastapi import APIRouter

from apps.worker.celery_app import celery_app

router = APIRouter(prefix="/operations", tags=["operations"])


class OperationState:
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


@router.get("/{task_id}")
def get_operation_status(task_id: str) -> dict[str, Any]:
    result = AsyncResult(task_id, app=celery_app)
    celery_state = str(result.state)
    if celery_state in {"PENDING", "RECEIVED", "RETRY"}:
        status = OperationState.QUEUED
    elif celery_state == "STARTED":
        status = OperationState.RUNNING
    elif celery_state == "SUCCESS":
        status = OperationState.SUCCESS
    elif celery_state == "FAILURE":
        status = OperationState.FAILED
    else:
        status = OperationState.QUEUED

    payload: dict[str, Any] = {
        "task_id": task_id,
        "status": status,
        "celery_state": celery_state,
    }
    if status == OperationState.SUCCESS:
        payload["result"] = result.result
    if status == OperationState.FAILED:
        payload["error"] = str(result.result)
    return payload
