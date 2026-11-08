"""Opt-in real worker smoke: public news, isolated temporary plan, retained evidence.

No mock provider, artificial wait or fabricated progress. The optional API restart
is only for the named local Compose service. Never touch existing plans/tasks.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time
import urllib.request

from sqlalchemy import func, select

from src.infrastructure.config import ROOT
from src.jobs.celery_app import app
from src.persistence.business import BusinessRepository
from src.persistence.database import transaction
from src.persistence.jobs import JobRepository
from src.persistence.models import RunEvent


def request(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8123/research/" + path,
            data=data, method=method, headers={"Content-Type": "application/json"}), timeout=30) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", required=True)
    parser.add_argument("--restart-api", action="store_true")
    parser.add_argument("--stock", action="store_true", help="Also invokes configured model on public research evidence")
    args = parser.parse_args()
    name = "M0 worker verification " + datetime.now(timezone.utc).strftime("%H%M%S")
    body = {"name": name, "workflow": "stock" if args.stock else "news", "keyword": "港股", "window_hours": 24,
            "config": {"symbol": "1211.HK", "market": "HK", "as_of": datetime.now(timezone.utc).date().isoformat(),
                       "analysts": ["news"], "depth": "quick", "include_risk": False, "include_sentiment": False,
                       "peers": [], "question": "Summarize available dated company news. Identify data gaps and cite original evidence."},
            "repeat": "daily", "time": "09:00", "enabled": False}
    plan_id = request("schedules", "POST", body)["id"]
    result = {"plan_id": plan_id, "name": name, "workflow": body["workflow"], "temporary": True}
    artifact_dir = ROOT / "local-data/validation"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact = artifact_dir / (plan_id + ".json")
    restart = None
    try:
        started = time.monotonic()
        job_id = request(f"schedules/{plan_id}/run", "POST")["id"]
        result["job_id"] = job_id
        second = request(f"schedules/{plan_id}/run", "POST")
        result["run_now_deduplicated"] = second == {"id": job_id, "existing": True}
        assert result["run_now_deduplicated"]
        repository = JobRepository()
        states = []
        while time.monotonic() - started < 480:
            detail = repository.task_detail(job_id)
            state = detail["status"]
            if not states or states[-1] != state:
                states.append(state)
                print(json.dumps({"job_id": job_id, "status": state}), flush=True)
            if state == "running":
                result.setdefault("running_after_seconds", round(time.monotonic() - started, 3))
                if args.restart_api and restart is None:
                    result["status_at_api_restart"] = state
                    with (artifact_dir / (plan_id + "-restart.log")).open("w") as output:
                        restart = subprocess.Popen(["docker", "compose", "--env-file", "infra/.env", "-f", "infra/compose.yaml",
                            "--profile", "application", "restart", "api"], cwd=ROOT, stdout=output, stderr=output)
            if restart is not None and restart.poll() is None and state == "running":
                result["worker_running_during_restart"] = True
            if state in {"complete", "partial", "failed", "cancelled"}:
                break
            time.sleep(0.2)
        else:
            repository.cancel(job_id)
            raise TimeoutError("Real execution exceeded smoke time limit; cancellation requested")
        result["states"], result["status"] = states, state
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        report = BusinessRepository().get_report(job_id)
        result["source_count"] = len(report.get("evidence", {}).get("sources", [])) if report else 0
        result["gap_count"] = len(report.get("evidence", {}).get("gaps", [])) if report else 0
        assert report and report["status"] == state and state in {"complete", "partial"}
        assert result["source_count"] > 0, "No real evidence was collected"
        before = hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()
        with transaction() as db:
            count = db.scalar(select(func.count()).select_from(RunEvent).where(RunEvent.run_id == job_id))
        app.send_task("aperture.research", kwargs={"job_id": job_id}, queue="research")
        time.sleep(2)
        with transaction() as db:
            after_count = db.scalar(select(func.count()).select_from(RunEvent).where(RunEvent.run_id == job_id))
        after = hashlib.sha256(json.dumps(BusinessRepository().get_report(job_id), sort_keys=True).encode()).hexdigest()
        result["terminal_redelivery_unchanged"] = before == after and count == after_count
        assert result["terminal_redelivery_unchanged"]
        if restart is not None:
            result["api_restart_exit"] = restart.wait(timeout=60)
            assert result["api_restart_exit"] == 0
        # Archive the temporary plan and hide only this terminal execution. The
        # report and plan-specific execution history must survive these actions.
        repository.archive_schedule(plan_id)
        repository.hide_task(job_id)
        result["cleanup_preserved_report_and_history"] = bool(BusinessRepository().get_report(job_id)) and any(
            item["id"] == job_id for item in repository.list_tasks(schedule_id=plan_id))
        assert result["cleanup_preserved_report_and_history"]
        result["passed"] = True
    except Exception as error:
        result["passed"], result["error_type"] = False, type(error).__name__
        raise
    finally:
        artifact.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
