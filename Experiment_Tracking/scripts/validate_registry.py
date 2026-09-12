from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


VALID_SPRINTS = {"Pre-Sprint-4", "Sprint 2", "Sprint 3", "Sprint 4", "Sprint 5"}
VALID_TASKS = {"Baseline", "QCI-2", "QCI-3", "QCI-4", "QCI-5", "CME-1", "CME-2", "CME-3", "CME-OPT1", "CME-OPT2", "CME-OPT3", "EAP-1", "ESE-CPU1", "ESE-CPU2", "ESE-CPU3", "IFE-UI1", "IFE-UI2", "IFE-UI3", "SED-1", "SED-2", "SED-3"}
MODEL_EXPERIMENT_TYPES = {"model_training", "model_finetuning"}
CALIBRATION_EXPERIMENT_TYPES = {"calibration"}
STREAM_BENCHMARK_TYPES = {"stream_benchmark", "async_video_ingestion"}
ESCALATION_TEST_TYPES = {"alert_escalation"}
STRESS_TEST_TYPES = {"stress_test", "cpu_soak_test"}
TEMPORAL_TRACKING_TYPES = {"temporal_tracking"}
DATASET_EXPERIMENT_TYPES = {"dataset_augmentation"}
FRONTEND_INTEGRATION_TYPES = {"frontend_integration", "incident_logging_and_reporting", "end_to_end_demo", "edge_telemetry_failover", "local_incident_pdf"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def is_missing(value: str | None) -> bool:
    return value in (None, "", "unknown", "not recorded", "missing")


def check_unique(rows: list[dict[str, str]], field: str, errors: list[str], path: Path) -> None:
    seen: set[str] = set()
    for row in rows:
        value = row.get(field, "")
        if value in seen:
            errors.append(f"{path}: duplicate {field}: {value}")
        seen.add(value)


def check_file_reference(root: Path, value: str, errors: list[str], context: str) -> None:
    if is_missing(value) or value.startswith("Google Drive") or value.startswith("Drive "):
        return
    first = value.split(";", 1)[0].strip()
    if first.startswith("/content") or first.startswith("/home/"):
        return
    if not (root / first).exists():
        errors.append(f"{context}: referenced file does not exist: {first}")


def validate(root: Path) -> int:
    errors: list[str] = []
    warnings: list[str] = []
    tracking = root / "Experiment_Tracking"
    experiments_path = tracking / "experiments.csv"
    model_registry_path = tracking / "model_registry.csv"
    alert_registry_path = tracking / "alert_policy_registry.csv"

    experiments = read_csv(experiments_path)
    models = read_csv(model_registry_path)
    policies = read_csv(alert_registry_path)

    check_unique(experiments, "run_id", errors, experiments_path)
    check_unique(models, "model_version", errors, model_registry_path)
    check_unique(policies, "policy_version", errors, alert_registry_path)

    model_versions = {row["model_version"] for row in models}
    policy_versions = {row["policy_version"] for row in policies}

    deployment_path = tracking / 'deployment_registry.csv'
    if deployment_path.exists():
        deployments=read_csv(deployment_path)
        check_unique(deployments,'deployment_version',errors,deployment_path)
        for row in deployments:
            if row['source_model_version'] not in model_versions:
                errors.append(f"{row['deployment_version']}: source detector missing from registry")
            for field in ('artifact_manifest','benchmark_report','calibration_manifest'):
                check_file_reference(root,row[field],errors,row['deployment_version'])

    for row in experiments:
        run_id = row["run_id"]
        if row["sprint"] not in VALID_SPRINTS:
            errors.append(f"{run_id}: invalid sprint {row['sprint']}")
        if row["task"] not in VALID_TASKS:
            errors.append(f"{run_id}: invalid task {row['task']}")
        if row['experiment_type']=='quantization':
            if row['model_version'] not in model_versions:
                errors.append(f'{run_id}: quantization source model missing from registry')
            for field in ('source_script','exported_weight_uri','map50','status'):
                if is_missing(row.get(field)):
                    errors.append(f'{run_id}: quantization run missing {field}')
            check_file_reference(root,row.get('source_script',''),errors,run_id)
        if row["experiment_type"] in MODEL_EXPERIMENT_TYPES:
            if row["model_version"] not in model_versions:
                errors.append(f"{run_id}: model_version missing from model registry")
            if is_missing(row["map50"]):
                warnings.append(f"{run_id}: mAP@50 not recorded in available artifacts")
            if is_missing(row["best_weight_uri"]):
                errors.append(f"{run_id}: model run missing best_weight_uri")
        if row['experiment_type']=='classifier_training':
            if row['model_version'] not in model_versions:
                errors.append(f'{run_id}: classifier missing from model registry')
            for field in ('best_weight_uri','dataset_version','git_commit','source_script','status'):
                if is_missing(row.get(field)):errors.append(f'{run_id}: classifier run missing {field}')
            check_file_reference(root,row.get('best_weight_uri',''),errors,run_id)
            check_file_reference(root,row.get('source_script',''),errors,run_id)
        if row["experiment_type"] in CALIBRATION_EXPERIMENT_TYPES:
            if row["model_version"] not in model_versions:
                errors.append(f"{run_id}: calibration detector model_version missing from model registry")
            if row["alert_policy_version"] not in policy_versions:
                errors.append(f"{run_id}: alert_policy_version missing from alert policy registry")
            for field in ("false_alerts", "missed_violations", "confidence_config"):
                if is_missing(row.get(field)):
                    errors.append(f"{run_id}: calibration run missing {field}")
        if row["experiment_type"] in STREAM_BENCHMARK_TYPES:
            if row["model_version"] not in model_versions:
                errors.append(f"{run_id}: stream benchmark detector model_version missing from model registry")
            if row["alert_policy_version"] not in policy_versions:
                errors.append(f"{run_id}: stream benchmark alert_policy_version missing from alert policy registry")
            if is_missing(row.get("source_script")):
                errors.append(f"{run_id}: stream benchmark missing source_script")
        if row['experiment_type'] in FRONTEND_INTEGRATION_TYPES:
            if row['model_version'] not in model_versions or row['alert_policy_version'] not in policy_versions:
                errors.append(f'{run_id}: frontend integration model/policy lineage missing from registry')
            for field in ('source_script','git_commit','status'):
                if is_missing(row.get(field)):
                    errors.append(f'{run_id}: frontend integration missing {field}')
            check_file_reference(root,row.get('source_script',''),errors,run_id)
        if row['experiment_type'] in TEMPORAL_TRACKING_TYPES:
            if row['model_version'] not in model_versions or row['alert_policy_version'] not in policy_versions:
                errors.append(f'{run_id}: temporal tracking model/policy lineage missing from registry')
            for field in ('source_script','confidence_config','sampling_fps','required_frames','false_alerts','missed_violations','status'):
                if is_missing(row.get(field)):
                    errors.append(f'{run_id}: temporal tracking run missing {field}')
            check_file_reference(root,row.get('source_script',''),errors,run_id)
            check_file_reference(root,row.get('confidence_config',''),errors,run_id)
        if row["experiment_type"] in ESCALATION_TEST_TYPES:
            if row["model_version"] not in model_versions:
                errors.append(f"{run_id}: escalation detector model_version missing from model registry")
            if row["alert_policy_version"] not in policy_versions:
                errors.append(f"{run_id}: escalation alert_policy_version missing from alert policy registry")
            if is_missing(row.get("confidence_config")):
                errors.append(f"{run_id}: escalation run missing severity config reference")
            if is_missing(row.get("source_script")):
                errors.append(f"{run_id}: escalation run missing source_script")
        if row["experiment_type"] in DATASET_EXPERIMENT_TYPES:
            if row["model_version"] not in model_versions:
                errors.append(f"{run_id}: dataset mining model missing from registry")
            for field in ("dataset_version", "seed", "source_script", "status"):
                if is_missing(row.get(field)):
                    errors.append(f"{run_id}: dataset experiment missing {field}")
            check_file_reference(root, row.get("source_script", ""), errors, run_id)
        if row["experiment_type"] in STRESS_TEST_TYPES:
            if row["model_version"] not in model_versions:
                errors.append(f"{run_id}: stress test detector model_version missing from model registry")
            if row["alert_policy_version"] not in policy_versions:
                errors.append(f"{run_id}: stress test alert_policy_version missing from alert policy registry")
            if is_missing(row.get("source_script")):
                errors.append(f"{run_id}: stress test missing source_script")

    for row in policies:
        version = row["policy_version"]
        if row["detector_model_version"] not in model_versions:
            errors.append(f"{version}: detector_model_version missing from model registry")
        check_file_reference(root, row["threshold_config"], errors, version)

    for cfg in (tracking / "configs").glob("*.yaml"):
        if cfg.stat().st_size == 0:
            errors.append(f"{cfg}: empty config file")

    print("Registry validation")
    print(f"- experiments: {len(experiments)}")
    print(f"- model versions: {len(models)}")
    print(f"- alert policies: {len(policies)}")
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")
    print("Result:", "PASS" if not errors else "FAIL")
    return 1 if errors else 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    sys.exit(validate(Path(args.root).resolve()))


if __name__ == "__main__":
    main()
