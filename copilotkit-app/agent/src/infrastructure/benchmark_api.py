"""Read-only API baseline. Future in-app benchmarks must reuse recorded samples."""
import argparse
from datetime import datetime, timezone
import json
import math
import time
from urllib.request import urlopen

from src.infrastructure.config import ROOT


def summarize(samples):
    ordered = sorted(samples)
    def percentile(fraction):
        return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]
    return {"samples": len(ordered), "p50_ms": round(percentile(0.5), 3), "p95_ms": round(percentile(0.95), 3),
            "min_ms": round(ordered[0], 3), "max_ms": round(ordered[-1], 3), "method": "nearest_rank"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=30)
    args = parser.parse_args()
    if not 30 <= args.repeats <= 100:
        raise ValueError("Baseline requires 30 to 100 sequential read-only requests")
    report = {"observed_at": datetime.now(timezone.utc).isoformat(), "model_calls": 0,
              "scope": "local sequential metadata API requests including loopback HTTP and JSON parsing; not cold-start or retrieval/model benchmark", "routes": {}}
    for endpoint, collection in (("reports", "reports"), ("tasks?kind=manual&limit=3", "tasks"), ("schedules", "schedules")):
        for service, base in (("api", "http://127.0.0.1:8123/research/"), ("web_proxy", "http://127.0.0.1:3000/api/research/")):
            samples, statuses, count = [], [], None
            for _ in range(args.repeats):
                start = time.perf_counter()
                try:
                    with urlopen(base + endpoint, timeout=20) as response:
                        payload = json.load(response)
                        count = len(payload[collection])
                        statuses.append(response.status)
                except Exception as error:
                    statuses.append(type(error).__name__)
                samples.append((time.perf_counter() - start) * 1000)
            key = service + ":" + endpoint
            report["routes"][key] = {**summarize(samples), "records_returned": count,
                                     "successes": statuses.count(200), "statuses": statuses, "raw_ms": samples}
    directory = ROOT / "local-data/validation"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "api-baseline.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: {field: value for field, value in result.items() if field not in {"raw_ms", "statuses"}}
                      for key, result in report["routes"].items()}))
    if any(result["successes"] != args.repeats for result in report["routes"].values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
