import os
import json
import uuid
import time
import shutil
import sys
from pathlib import Path


def _configure_django():
    repo_root = str(Path(__file__).resolve().parents[1])
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pdf_automation.settings')
    import django  # noqa: WPS433

    django.setup()


def _ensure_media_root(media_root: str) -> None:
    from django.conf import settings

    settings.MEDIA_ROOT = media_root


def _make_ranges(n: int, start_page: int = 1) -> str:
    # Important: the project's normalize_split_spec() collapses newlines into spaces,
    # so we must use ';' to separate outputs/groups.
    return ";".join([f"{start_page + i}-{start_page + i}" for i in range(n)])


def enqueue_split_only(
    pdf_source: str,
    media_root: str,
    n_ranges: int,
    label: str,
) -> str:
    from processing.tasks import preflight_split_job, split_pdf_job

    job_id = uuid.uuid4().hex
    job_dir = Path(media_root) / 'processing' / 'preflight' / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    input_pdf_path = job_dir / 'input.pdf'
    shutil.copyfile(pdf_source, input_pdf_path)

    page_ranges_text = _make_ranges(n_ranges)
    with open(job_dir / 'request.json', 'w', encoding='utf-8') as f:
        json.dump({'page_ranges': page_ranges_text, 'patient_name': f'BENCH_{label}'}, f, ensure_ascii=False)

    preflight_async = preflight_split_job.delay(job_id, str(input_pdf_path), page_ranges_text)
    split_async = split_pdf_job.delay(job_id)

    print(f"JOB {label}: {job_id}")
    print(f"  preflight task: {preflight_async.id}")
    print(f"  split task:     {split_async.id}")
    return job_id


def wait_for_completion(job_id: str, timeout_s: int = 3600, poll_s: float = 2.0) -> dict:
    from pdfs.models import ProcessingRun, ProcessingStep

    t0 = time.time()
    last_status = None

    while True:
        run = ProcessingRun.objects.filter(job_id=job_id).order_by('-started_at').first()
        if run is None:
            if time.time() - t0 > timeout_s:
                raise TimeoutError(f"Timed out waiting for ProcessingRun for job_id={job_id}")
            time.sleep(poll_s)
            continue

        if run.status != last_status:
            print(f"  status: {run.status}")
            last_status = run.status

        if run.status != 'RUNNING':
            steps = list(ProcessingStep.objects.filter(run=run).order_by('started_at'))
            return {
                'job_id': job_id,
                'status': run.status,
                'run_duration_ms': run.duration_ms,
                'run_started_at': run.started_at,
                'run_finished_at': run.finished_at,
                'steps': [
                    {
                        'step': s.step,
                        'status': s.status,
                        'duration_ms': s.duration_ms,
                        'count_total': s.count_total,
                        'count_done': s.count_done,
                        'count_failed': s.count_failed,
                    }
                    for s in steps
                ],
            }

        if time.time() - t0 > timeout_s:
            raise TimeoutError(f"Timed out waiting for completion for job_id={job_id}")

        time.sleep(poll_s)


def main():
    media_root = os.environ.get('BENCH_MEDIA_ROOT', r'D:\hyperlink_POC\Sample')
    pdf_source = os.environ.get('BENCH_PDF', r'D:\hyperlink_POC\Sample\Medical Records.pdf')

    _configure_django()
    _ensure_media_root(media_root)

    print('MEDIA_ROOT:', media_root)
    print('PDF_SOURCE:', pdf_source)
    if not os.path.exists(pdf_source):
        raise FileNotFoundError(pdf_source)

    from processing.tasks import get_pdf_page_count

    total_pages = get_pdf_page_count(pdf_source)
    print('PDF_PAGES:', total_pages)

    desired = [25, 100, 300]
    cases = []
    for n in desired:
        cases.append((min(n, total_pages), f"R{n}"))

    results = []
    for n_ranges, label in cases:
        print('\n=== Enqueue', label, f"({n_ranges} ranges) ===")
        job_id = enqueue_split_only(pdf_source, media_root, n_ranges, label)
        print('--- Waiting for completion ---')
        res = wait_for_completion(job_id)
        results.append(res)

    print('\n\n=== SUMMARY (ms) ===')
    for res in results:
        run_ms = res.get('run_duration_ms')
        print(f"job={res['job_id']} status={res['status']} run_ms={run_ms}")
        for s in res['steps']:
            print(
                f"  {s['step']}: status={s['status']} duration_ms={s['duration_ms']} "
                f"done={s['count_done']}/{s['count_total']} failed={s['count_failed']}"
            )


if __name__ == '__main__':
    main()
