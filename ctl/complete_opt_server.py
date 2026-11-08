"""Run both frozen fleet experiments, validate outputs, analyze, and archive."""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tarfile
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "ctl"))
import run_extra as runner

WORKERS = 10
STATUS = ROOT / "optimizer_server.status"


def status(message):
    STATUS.write_text(message + "\n")
    print(time.strftime("%Y-%m-%d %H:%M:%S %z"), message, flush=True)


def validate(fleet):
    design = json.loads((ROOT / f'design_{"sens_opt8" if fleet == "fleet8" else "sens_opt"}.json').read_text())
    paths = []
    for seed in design["seeds"]:
        for case in design["cases"]:
            path = ROOT / "results" / "sens_opt" / f'{fleet}__{case["name"]}__optimizer__{seed}.json'
            result = json.loads(path.read_text())
            assert result["seed"] == seed and result["workflow"] == case, path
            assert result["fleet_size"] == int(fleet[5:]) and result["policy"] == "optimizer", path
            assert result["warmup_days"] == 7 and result["measurement_days"] == 7, path
            assert result["created"] == result["completed"] + result["incomplete"], path
            assert result["human_completed"] + result["robot_completed"] == result["completed"], path
            assert result["battery_infeasible_missions"] == 0, path
            paths.append(path)
    assert len(paths) == 48
    assert set(paths) == set((ROOT / "results" / "sens_opt").glob(f"{fleet}__*.json"))
    return paths


def phase(name):
    status("RUNNING " + name)
    subprocess.run(["bash", "ctl/pipeline_opt_server.sh", name, str(WORKERS)], check=True)
    assert (ROOT / f"pipeline_{name}.status").read_text().strip() == "DONE", name
    fleet = "fleet8" if name == "sens_opt8" else "fleet4"
    paths = validate(fleet)
    with (ROOT / f"analysis_{fleet}.log").open("w") as log:
        subprocess.run([sys.executable, "ctl/analyze_opt.py", fleet], stdout=log, stderr=subprocess.STDOUT, check=True)
    durations = [json.loads(p.read_text())["elapsed_seconds"] for p in paths]
    print(fleet, "validated", len(paths), "runs; mean seconds", sum(durations) / len(durations), flush=True)


def main():
    frozen = json.loads((ROOT / "design_sens_opt.json").read_text())
    for name, expected in frozen["code_hashes"].items():
        if name.startswith("src/"):
            assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, name
    allowed = {"decision_mean_ms", "decision_p95_ms", "elapsed_seconds", "decision_times", "optimizer_seconds"}
    for ref in (ROOT / "ref").glob("*.json"):
        actual = ROOT / "repro" / ref.name
        if actual.exists():
            old, new = json.loads(ref.read_text()), json.loads(actual.read_text())
            assert all(new.get(k) == v for k, v in old.items() if k not in allowed), ref
            assert old["weighted_tardiness_per_request"] == new["weighted_tardiness_per_request"], ref
    assert len(list((ROOT / "repro").glob("*.json"))) == 3
    metadata = dict(python=sys.version, platform=platform.platform(), workers=WORKERS,
                    cpu_affinity=sorted(os.sched_getaffinity(0)), started=time.strftime("%Y-%m-%d %H:%M:%S %z"),
                    code_hashes={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for folder in ("src", "ctl") for p in (ROOT / folder).rglob("*.py")},
                    imported_cloud_results=[p.name for p in (ROOT / "results" / "sens_opt").glob("fleet4__*.json")])
    metadata_path = ROOT / "optimizer_server_metadata.json"
    if not metadata_path.exists():
        metadata_path.write_text(json.dumps(metadata, indent=2))
    phase("sens_opt")
    # Measure one complete eight-robot run before starting its parallel batch.
    fleet = "fleet8"
    chosen = [c for c in runner.rw.cases() if c["mode"] in ("mobile", "local") and c["background_fraction"] in (.4, .8)]
    runner.freeze("sens_opt8", dict(phase="sens_opt8", scenarios={fleet: runner.SCENARIOS[fleet]},
                  seeds=list(range(103000, 103006)), warmup_days=7, measurement_days=7,
                  policies=["optimizer"], cases=chosen))
    sample = ROOT / "results" / "sens_opt" / f'{fleet}__{chosen[0]["name"]}__optimizer__103000.json'
    if not sample.exists():
        status("BENCHMARK sens_opt8, one full run")
        runner.base.initialize()
        runner.job((chosen[0], "optimizer", 103000, 7, 7, str(sample.parent), fleet, runner.SCENARIOS[fleet]))
    seconds = json.loads(sample.read_text())["elapsed_seconds"]
    (ROOT / "benchmark_fleet8.json").write_text(json.dumps(dict(file=sample.name, elapsed_seconds=seconds,
                                                            note="One full run; batch duration remains an estimate."), indent=2))
    print("fleet8 benchmark seconds", seconds, flush=True)
    phase("sens_opt8")
    status("PACKAGING")
    targets = [ROOT / "results" / "sens_opt", ROOT / "analysis_extra"]
    for pattern in ("design_sens_opt*.json", "sens_opt*.log", "analysis_fleet*.log", "pipeline_sens_opt*.status",
                    "repro_server.log", "requirements_server.lock", "optimizer_server_metadata.json", "benchmark_fleet8.json"):
        targets.extend(ROOT.glob(pattern))
    archive = ROOT / "optimizer_server_results.tar.gz"
    with tarfile.open(archive.with_suffix(".tmp"), "w:gz") as output:
        for path in targets:
            output.add(path, arcname=str(path.relative_to(ROOT)))
    archive.with_suffix(".tmp").replace(archive)
    status("DONE, both fleets validated and analyzed; archive ready")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        status("FAIL, see optimizer_server.log")
        traceback.print_exc()
        raise
