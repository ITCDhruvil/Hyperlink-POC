import json
import random
import time
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand
from django.test import Client

from processing.pdf_utils import get_pdf_page_count


def _make_mixed_ranges(n: int, total_pages: int) -> str:
    random.seed(9000 + n)
    parts = []
    page = 1

    for i in range(n):
        typ = i % 3
        if typ == 0:
            parts.append(str(page))
            page += 1
        elif typ == 1:
            end = min(total_pages, page + 2)
            parts.append(f"{page}-{end}")
            page = end + 1
        else:
            a = page
            b = min(total_pages, page + 1)
            c = min(total_pages, page + 3)
            d1 = min(total_pages, page + 5)
            d2 = min(total_pages, page + 6)
            parts.append(f"{a}-{b}, {c}, {d1}-{d2}")
            page = min(total_pages, page + 7)

        if page >= total_pages:
            page = 1

    return ";".join(parts)


def _poll_json(client: Client, url: str, *, timeout_s: int = 3600, interval_s: float = 0.5) -> dict:
    start = time.time()
    last = None
    while time.time() - start < timeout_s:
        resp = client.get(url)
        if resp.status_code == 200:
            payload = resp.json()
            last = payload
            status = payload.get("status")
            if status not in (None, "PENDING", "RUNNING"):
                return payload
            if status == "SUCCESS":
                return payload
        time.sleep(interval_s)
    raise TimeoutError(f"Timed out polling {url}. Last={last}")


class Command(BaseCommand):
    help = "Benchmark current split pipeline flow (preflight -> split) via Django endpoints."

    def add_arguments(self, parser):
        parser.add_argument(
            "--pdf",
            required=True,
            help="Absolute path to a PDF file to upload (e.g. D:/hyperlink_POC/Sample/Medical Records.pdf)",
        )
        parser.add_argument(
            "--outputs",
            nargs="+",
            type=int,
            default=[50, 100, 150],
            help="List of output counts to test (default: 50 100 150)",
        )
        parser.add_argument(
            "--patient",
            default="Bench_Patient",
            help="Patient name to send in the request",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=3600,
            help="Timeout in seconds per run (default 3600)",
        )

    def handle(self, *args, **options):
        pdf_path = Path(options["pdf"])
        if not pdf_path.exists():
            raise SystemExit(f"PDF not found: {pdf_path}")

        total_pages = get_pdf_page_count(str(pdf_path))
        self.stdout.write(f"PDF pages: {total_pages}")

        # Ensure we can hit login_required endpoints.
        User = get_user_model()
        user, _ = User.objects.get_or_create(
            username="benchmark_bot",
            defaults={"is_staff": True, "is_superuser": True, "email": "benchmark_bot@example.com"},
        )
        user.set_password("benchmark_bot_password")
        user.save()

        client = Client()
        if not client.login(username="benchmark_bot", password="benchmark_bot_password"):
            raise SystemExit("Failed to login benchmark user")

        results = {
            "started_at": datetime.utcnow().isoformat(),
            "pdf": str(pdf_path),
            "total_pages": total_pages,
            "outputs": [],
            "chunk_size": int(getattr(settings, "SPLIT_TASK_CHUNK_SIZE", 10) or 10),
        }

        for n in options["outputs"]:
            page_ranges = _make_mixed_ranges(n, total_pages)

            with open(pdf_path, "rb") as f:
                uploaded = SimpleUploadedFile(
                    name=pdf_path.name,
                    content=f.read(),
                    content_type="application/pdf",
                )

            # 1) preflight
            t0 = time.time()
            resp = client.post(
                "/preflight-split/",
                data={"page_ranges": page_ranges, "patient_name": options["patient"]},
                files={"file": uploaded},
            )
            if resp.status_code != 200:
                raise SystemExit(f"Preflight start failed ({resp.status_code}): {resp.content[:500]}")
            preflight = resp.json()
            if not preflight.get("success"):
                raise SystemExit(f"Preflight start returned failure: {preflight}")

            job_id = preflight["job_id"]
            preflight_status = _poll_json(
                client,
                f"/preflight-split-status/{job_id}/",
                timeout_s=options["timeout"],
            )
            t_preflight = time.time() - t0

            if preflight_status.get("status") != "SUCCESS":
                results["outputs"].append(
                    {
                        "n": n,
                        "job_id": job_id,
                        "preflight_s": round(t_preflight, 3),
                        "split_s": None,
                        "status": "PREFLIGHT_FAILED",
                        "preflight": preflight_status,
                    }
                )
                continue

            # 2) start split
            t1 = time.time()
            resp2 = client.post(f"/start-async-split/{job_id}/")
            if resp2.status_code != 200:
                raise SystemExit(f"Split start failed ({resp2.status_code}): {resp2.content[:500]}")

            split_status = _poll_json(
                client,
                f"/async-split-status/{job_id}/",
                timeout_s=options["timeout"],
            )
            t_split = time.time() - t1

            results["outputs"].append(
                {
                    "n": n,
                    "job_id": job_id,
                    "preflight_s": round(t_preflight, 3),
                    "split_s": round(t_split, 3),
                    "status": split_status.get("status"),
                    "counts": split_status.get("counts"),
                }
            )

            self.stdout.write(
                f"outputs={n} preflight_s={round(t_preflight,3)} split_s={round(t_split,3)} status={split_status.get('status')} counts={split_status.get('counts')}"
            )

        results["finished_at"] = datetime.utcnow().isoformat()

        out_dir = Path(settings.MEDIA_ROOT) / "benchmarks"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"split_benchmark_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

        self.stdout.write(f"\nSaved benchmark results: {out_path}")
        return ""
