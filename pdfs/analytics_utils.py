from __future__ import annotations

from typing import Optional

from django.utils import timezone

from .models import ProcessingRun, ProcessingStep, ProcessingHistory


def get_or_create_run(
    *,
    job_id: str = "",
    run_mode: str,
    user=None,
    processing_history: Optional[ProcessingHistory] = None,
    patient_name: str = "",
) -> ProcessingRun:
    run, _ = ProcessingRun.objects.get_or_create(
        job_id=job_id or "",
        run_mode=run_mode,
        defaults={
            "user": user,
            "processing_history": processing_history,
            "patient_name": patient_name or "",
            "status": "RUNNING",
        },
    )

    updated = False
    if user is not None and run.user_id is None:
        run.user = user
        updated = True
    if processing_history is not None and run.processing_history_id is None:
        run.processing_history = processing_history
        updated = True
    if patient_name and not run.patient_name:
        run.patient_name = patient_name
        updated = True

    if updated:
        run.save(update_fields=["user", "processing_history", "patient_name"])

    return run


def start_step(run: ProcessingRun, step: str, *, extra: Optional[dict] = None) -> ProcessingStep:
    return ProcessingStep.objects.create(
        run=run,
        step=step,
        status="RUNNING",
        extra=extra or {},
    )


def finish_step(
    step: ProcessingStep,
    *,
    status: str,
    count_total: Optional[int] = None,
    count_done: Optional[int] = None,
    count_failed: Optional[int] = None,
    error_code: str = "",
    error_message: str = "",
    extra: Optional[dict] = None,
) -> ProcessingStep:
    step.status = status
    step.finished_at = timezone.now()
    if step.started_at and step.finished_at:
        step.duration_ms = int((step.finished_at - step.started_at).total_seconds() * 1000)

    if count_total is not None:
        step.count_total = count_total
    if count_done is not None:
        step.count_done = count_done
    if count_failed is not None:
        step.count_failed = count_failed
    if error_code:
        step.error_code = error_code
    if error_message:
        step.error_message = error_message
    if extra:
        merged = dict(step.extra or {})
        merged.update(extra)
        step.extra = merged

    step.save()
    return step


def finish_run(
    run: ProcessingRun,
    *,
    status: str,
    error_code: str = "",
    error_message: str = "",
    extra: Optional[dict] = None,
) -> ProcessingRun:
    run.status = status
    run.finished_at = timezone.now()
    if run.started_at and run.finished_at:
        run.duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)

    if error_code:
        run.error_code = error_code
    if error_message:
        run.error_message = error_message
    if extra:
        merged = dict(run.extra or {})
        merged.update(extra)
        run.extra = merged

    run.save()
    return run
