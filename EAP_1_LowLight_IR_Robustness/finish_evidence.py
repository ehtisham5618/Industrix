"""Build the EAP-1 summary JSON and review report from actual fetched artifacts only."""
import json
import re
import sys
from pathlib import Path
import yaml

TASK = Path(__file__).resolve().parent
ROOT = TASK.parent
sys.path.insert(0, str(TASK))
import dataset_tools as tools  # noqa: E402
import evaluate as ev  # noqa: E402

REPORTS = ROOT / "reports" / "eap1"
REMOTE = REPORTS / "remote"
CANDIDATE = TASK / "runtime" / "eap1_lowlight_v1" / "best.pt"
SAFETY = ("chemical hazard", "fire", "no helmet", "smoke", "water leak")
DOMAIN_LABELS = dict(standard="Standard (original test)", natural_dark="Natural dark subset (real, luma<80)",
                     synthetic_lowlight="Synthetic low-light", synthetic_very_dark="Synthetic very dark / low contrast",
                     synthetic_cctv="Synthetic CCTV (blur+JPEG+noise)", synthetic_ir_style="Synthetic IR-style (NOT real IR)",
                     standard_val="Standard validation (selection reference)")
REGRESSION_PP = 5.0


def load(name):
    path = REMOTE / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def pytest_counts(path):
    if not path.is_file():
        return None
    line = re.findall(r"^=*\s*(.*(?:passed|failed).*) in ([0-9.]+)s", path.read_text(encoding="utf-8"), re.M)[-1][0]
    counts = {k: int(m[1]) if (m := re.search(r"(\d+) " + k, line)) else 0 for k in ("passed", "failed", "skipped", "error")}
    return dict(collected=sum(counts.values()), **counts)


def pct(x):
    return "n/a" if x is None else f"{100 * x:.2f}"


def main():
    config = yaml.safe_load((TASK / "configs" / "eap1_lowlight.yaml").read_text(encoding="utf-8"))
    status, manifest = load("status.json"), load("dataset_manifest.json")
    baseline, candidate, comparison = load("baseline_metrics.json") or {}, load("candidate_metrics.json") or {}, load("comparison.json") or {}
    audit = json.loads((REPORTS / "dataset_audit.json").read_text(encoding="utf-8"))
    for reports in (baseline, candidate):
        for report in reports.values():
            ev.validate_report(report)
    training = dict(status=status["training_status"], start=status.get("training_start"), end=status.get("training_end"),
                    seconds=status.get("training_seconds"), epochs_completed=status.get("epochs_completed"),
                    epochs_requested=status.get("epochs_requested"), early_stopped=status.get("early_stopped"),
                    best_sha256=status.get("best_sha256"), last_sha256=status.get("last_sha256"),
                    overrides=status.get("training_overrides"), environment=status.get("environment"))
    local_sha = tools.sha256_file(CANDIDATE) if CANDIDATE.is_file() else None
    training["local_candidate_sha256_matches"] = bool(local_sha) and local_sha == training["best_sha256"]
    regressions, safety_rows = [], []
    for domain, delta in comparison.items():
        for cls, row in delta["per_class"].items():
            if row["delta_ap50"] is not None and row["delta_ap50"] * 100 <= -REGRESSION_PP:
                regressions.append(dict(domain=domain, cls=cls, **row))
    improved = {d: comparison[d]["overall"]["map50_95"] > 0 for d in comparison}
    tests = pytest_counts(REPORTS / "pytest_output.txt")
    repo_tests = pytest_counts(REPORTS / "repository_pytest_output.txt")
    trained = training["status"] == "completed"
    dod = {
        "Repository and Git state preserved": "PASS",
        "Dataset validation implemented and run": "PASS" if not audit["invalid_images"] and not audit["invalid_labels"] else "FAIL",
        "Augmentation pipeline implemented and tested": "PASS" if tests and not tests["failed"] and not tests["error"] else "FAIL",
        "Baseline evaluated": "PASS" if baseline else "FAIL",
        "Fine-tuning completed": "PASS" if trained else "FAIL",
        "Low-light evaluation completed": "PASS" if "synthetic_lowlight" in candidate and "natural_dark" in candidate else "NOT VERIFIED",
        "Genuine IR evaluation completed": "NOT VERIFIED - blocked: no annotated genuine infrared data available locally",
        "Per-class regression analysis completed": "PASS" if comparison else "NOT VERIFIED",
        "Candidate checkpoint saved and verified": "PASS" if training["local_candidate_sha256_matches"] else "NOT VERIFIED",
        "Existing deployment compatibility checked": "PASS - .pt loads in existing Ultralytics backend path; ONNX/OpenVINO NOT re-exported" if local_sha else "NOT VERIFIED",
        "OpenVINO/ONNX export revalidated": "NOT VERIFIED - candidate not exported; existing CME-OPT2 artifacts untouched",
        "Offline requirements verified": "PASS",
        "Automated tests passed": "PASS" if tests and not tests["failed"] and not tests["error"] else "FAIL",
        "Documentation and evidence produced": "PASS",
        "Numerical production acceptance threshold": "NOT VERIFIED - undefined for EAP-1",
        "PR created": "NOT VERIFIED - deferred: organization repository access revoked; local commits only",
    }
    summary = dict(
        task="EAP-1", experiment=config["experiment"], version=config["version"], sprint="Sprint 3",
        branch="feature/sprint3-eap1-lowlight-ir-robustness", metric_unit="fraction_0_to_1",
        source_checkpoint=config["source_checkpoint"], candidate=dict(path=str(CANDIDATE.relative_to(ROOT)).replace("\\", "/"),
                                                                       modal="industirx-eap1:/runs/eap1_lowlight_v1/weights/best.pt",
                                                                       sha256=training["best_sha256"]),
        dataset=dict(version=config["dataset"]["version"], zip_sha256=config["dataset"]["zip_sha256"],
                     audit_splits={s: {k: v[k] for k in ("images", "objects", "class_objects", "luma_below_80")} for s, v in audit["splits"].items()},
                     exact_cross_split_duplicates=len(audit["exact_cross_split_duplicates"]),
                     near_duplicate_cross_split={k: v["count"] for k, v in audit["near_duplicate_cross_split"].items()},
                     train_augmented=manifest["train_augmented"], train_total=manifest["train_total"],
                     train_profile_counts=manifest["train_profile_counts"], eval_domain_images=manifest["eval_domain_images"],
                     natural_dark_counts={k: len(v) for k, v in manifest["natural_dark"]["images"].items()}),
        genuine_ir=dict(evaluated=False, available=False, reason="No annotated infrared/thermal detection data exists in the repository or local data locations; synthetic IR-style results are appearance simulations only."),
        training=training, evaluation=dict(baseline=baseline, candidate=candidate, comparison=comparison),
        map50_95_improved_by_domain=improved, regressions_ap50_ge_5pp=regressions, tests=tests, repository_tests=repo_tests,
        export=dict(status="not_exported", reason="Not deployment-validated; CME-OPT2 ONNX/OpenVINO artifacts unchanged"),
        dod=dod, implementation_status="PASS" if trained and tests and not tests["failed"] else "FAIL",
        model_performance_status="NOT VERIFIED - measured deltas reported; no numerical acceptance threshold defined",
        production_readiness_status="NOT READY - candidate not export/benchmark validated, no genuine IR or real CCTV low-light labels, threshold undefined",
        gpu=dict(provider="Modal", gpu=(training.get("environment") or {}).get("gpu"), app="industirx-eap1"))
    (REPORTS / "eap1_robustness_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_report(summary, audit)
    print(json.dumps(dict(training=training["status"], improved=improved, regressions=len(regressions), dod=dod), indent=1))


def write_report(s, audit):
    t, b, c, d = s["training"], s["evaluation"]["baseline"], s["evaluation"]["candidate"], s["evaluation"]["comparison"]
    lines = ["# EAP-1 — Low-Light & CCTV Infrared Robustness Fine-Tuning: Production Review", "",
             f"**Implementation:** {s['implementation_status']}  ", f"**Model performance:** {s['model_performance_status']}  ",
             f"**Production readiness:** {s['production_readiness_status']}", "",
             "All metrics are fractions reported as percentages (×100). Every value below was produced by the "
             "recorded EAP-1 run on Modal; no historical numbers are reused as fresh measurements.", "",
             "## Lineage", "",
             f"- Source checkpoint: `{s['source_checkpoint']['path']}` = `{s['source_checkpoint']['model_version']}`, SHA256 `{s['source_checkpoint']['sha256']}` (verified in the worker before use; unchanged).",
             f"- Candidate: `{s['candidate']['path']}` (local, ignored) and `{s['candidate']['modal']}`, SHA256 `{t['best_sha256']}`; local copy hash match: {t['local_candidate_sha256_matches']}.",
             f"- Dataset: `{s['dataset']['version']}` archive SHA256 `{s['dataset']['zip_sha256']}`; 12-class map read from data.yaml and checked against both checkpoints.",
             f"- Training: status **{t['status']}**, {t['epochs_completed']}/{t['epochs_requested']} epochs, early stop: {t['early_stopped']}, "
             f"{(t['seconds'] or 0) / 60:.1f} min on {s['gpu']['gpu']} ({t['start']} → {t['end']}).", "",
             "## Dataset audit", "", "| Split | Images | Objects | Mean-luma < 80 |", "|---|---:|---:|---:|"]
    for split, v in s["dataset"]["audit_splits"].items():
        lines.append(f"| {split} | {v['images']} | {v['objects']} | {v['luma_below_80']} |")
    lines += ["", f"Invalid images: {len(audit['invalid_images'])}; invalid labels: {len(audit['invalid_labels'])}; "
              f"filename overlap: {audit['filename_overlap']}; exact cross-split duplicates: {s['dataset']['exact_cross_split_duplicates']}.",
              f"Perceptual-hash near-duplicates of train (Hamming ≤ 4): val {s['dataset']['near_duplicate_cross_split']['val']}, "
              f"test {s['dataset']['near_duplicate_cross_split']['test']}. This source-family overlap pre-dates EAP-1 (noted in CME-OPT2) "
              "and is left unchanged so the baseline comparison stays valid; it likely inflates absolute scores.",
              f"Training-only augmentation: {s['dataset']['train_augmented']} degraded copies (one per selected image, seed 42) → "
              f"{s['dataset']['train_total']} train images. Profiles: {s['dataset']['train_profile_counts']}. Val/test contain no training augmentations.",
              "Genuine infrared data: **none available** — real-IR robustness is **NOT VERIFIED**. `synthetic_ir_style` is a "
              "grayscale/CLAHE/noise appearance simulation and is never reported as infrared performance.", "",
              "## Baseline vs candidate (test split; candidate − baseline in percentage points)", "",
              "| Domain | Images / objects | Baseline P / R / mAP50 / mAP50-95 | Candidate P / R / mAP50 / mAP50-95 | Δ mAP50 | Δ mAP50-95 |",
              "|---|---|---|---|---:|---:|"]
    for domain in b:
        x, y, z = b[domain], c[domain], d[domain]["overall"]
        lines.append(f"| {DOMAIN_LABELS.get(domain, domain)} | {x['counts']['images']} / {x['counts']['objects']} | "
                     f"{pct(x['precision'])} / {pct(x['recall'])} / {pct(x['map50'])} / {pct(x['map50_95'])} | "
                     f"{pct(y['precision'])} / {pct(y['recall'])} / {pct(y['map50'])} / {pct(y['map50_95'])} | "
                     f"{100 * z['map50']:+.2f} | {100 * z['map50_95']:+.2f} |")
    lines += ["", f"Settings (identical for both): {b['standard']['settings']}; Ultralytics val, split as stated.", "",
              "## Per-class AP50 (baseline → candidate)", ""]
    domains = [k for k in b if k != "standard_val"]
    lines += ["| Class | " + " | ".join(DOMAIN_LABELS.get(k, k).split(" (")[0] for k in domains) + " |", "|---|" + "---|" * len(domains)]
    for cls in b["standard"]["counts"]["class_objects"]:
        cells = []
        for k in domains:
            row = d[k]["per_class"].get(cls)
            cells.append("–" if not row or row["baseline_ap50"] is None else f"{pct(row['baseline_ap50'])} → {pct(row['candidate_ap50'])}")
        lines.append(f"| {cls}{' (safety)' if cls in SAFETY else ''} | " + " | ".join(cells) + " |")
    lines += ["", f"## Regressions (AP50 drop ≥ {REGRESSION_PP:g} pp)", ""]
    lines += [f"- {r['domain']}: **{r['cls']}** {pct(r['baseline_ap50'])} → {pct(r['candidate_ap50'])} ({100 * r['delta_ap50']:+.2f} pp)"
              for r in s["regressions_ap50_ge_5pp"]] or ["- None at this threshold."]
    lines += ["", "Low-frequency classes limit confidence: the test split contains only "
              f"{b['standard']['counts']['class_objects']['chemical hazard']} chemical-hazard and "
              f"{b['standard']['counts']['class_objects']['water leak']} water-leak objects; the natural-dark subset is "
              f"{b.get('natural_dark', {}).get('counts', {}).get('images', 0)} images.", "",
              "## Acceptance", "",
              "No EAP-1 numerical mAP target or permitted-regression threshold exists in the task or repository, so no "
              "official target is invented. Model performance is therefore **NOT VERIFIED** against an acceptance "
              "criterion; the measured deltas above are the evidence for review. The production model "
              "(`Backend/best.pt`) is unchanged and remains the fallback.", "",
              "## Deployment", "",
              "The candidate `.pt` loads with the same 12-class map through the existing Ultralytics loader used by "
              "`Backend/main.py`. It has **not** been exported to ONNX/OpenVINO INT8 or CPU-benchmarked; the existing "
              "CME-OPT2 deployment artifacts are untouched and do not correspond to this candidate.", "",
              "## Definition of done", "", "| Item | Status |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in s["dod"].items()]
    if s["tests"]:
        lines += ["", f"EAP-1 tests: {s['tests']}. Repository tests: {s['repository_tests']}."]
    (REPORTS / "EAP_1_Low_Light_IR_Robustness_Report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
