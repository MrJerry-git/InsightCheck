"""Prespecified numeric-feature baselines for one sample per subject, offline only."""

import argparse
import hashlib
import importlib.metadata
import json
import subprocess
from pathlib import Path
from typing import Literal

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.research.nlst import sha256


class TaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    status: Literal["DRAFT", "BLOCKED", "FROZEN"]
    source_kind: Literal["synthetic", "public_observational", "partner_observational"]
    features: list[str] = Field(min_length=1)
    forbidden_features: list[str]
    outcome_definition: str = Field(min_length=1)
    negative_definition: str = Field(min_length=1)
    availability_assumptions: str = Field(min_length=1)
    review_record: str = Field(min_length=1)
    data_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def check_features(self):
        if len(set(self.features)) != len(self.features):
            raise ValueError("duplicate features")
        prohibited = set(self.forbidden_features) | {"subject_id", "label"}
        if prohibited.intersection(self.features):
            raise ValueError("forbidden feature requested")
        return self


def validate_data(frame: pd.DataFrame, task: TaskSpec) -> pd.DataFrame:
    if task.status != "FROZEN":
        raise ValueError("task must be FROZEN after data and outcome review; no fitting performed")
    expected = {"subject_id", "label", *task.features}
    if set(frame.columns) != expected or frame.columns.duplicated().any():
        raise ValueError("dataset must contain exactly subject_id, label, and approved features")
    if frame.subject_id.isna().any() or frame.subject_id.astype(str).str.strip().eq("").any():
        raise ValueError("missing subject ID")
    frame = frame.copy()
    frame["subject_id"] = frame.subject_id.astype(str)
    if frame.subject_id.duplicated().any():
        raise ValueError(
            "v1 requires one sample per subject; repeated measures require grouped design"
        )
    if frame.label.isna().any() or not frame.label.isin([0, 1]).all():
        raise ValueError("labels must be known binary outcomes; unknown is not negative")
    if frame.label.nunique() != 2 or frame.label.value_counts().min() < 10:
        raise ValueError("need at least 10 subjects in each class for engineering splits")
    for col in task.features:
        frame[col] = pd.to_numeric(frame[col], errors="raise")
        if np.isinf(frame[col].to_numpy(dtype=float)).any():
            raise ValueError("infinite feature value")
    return frame.sort_values("subject_id").reset_index(drop=True)


def split_subjects(frame: pd.DataFrame, seed: int) -> dict[str, pd.DataFrame]:
    development, test = train_test_split(
        frame, test_size=0.2, stratify=frame.label, random_state=seed
    )
    train, validation = train_test_split(
        development, test_size=0.25, stratify=development.label, random_state=seed
    )
    return {"train": train, "validation": validation, "test": test}


def estimators(seed: int) -> dict[str, Pipeline]:
    models = {
        "logistic": LogisticRegression(max_iter=1000, random_state=seed),
        "random_forest": RandomForestClassifier(
            n_estimators=200, min_samples_leaf=5, n_jobs=1, random_state=seed
        ),
        "lightgbm": LGBMClassifier(
            n_estimators=100,
            learning_rate=0.05,
            num_leaves=15,
            n_jobs=1,
            random_state=seed,
            deterministic=True,
            force_col_wise=True,
            verbosity=-1,
        ),
    }
    return {
        name: Pipeline(
            [
                (
                    "impute",
                    SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True),
                ),
                ("scale", StandardScaler()),
                ("model", model),
            ]
        )
        for name, model in models.items()
    }


def metrics(labels: np.ndarray, probabilities: np.ndarray) -> dict:
    prediction = probabilities >= 0.5
    tn, fp, fn, tp = confusion_matrix(labels, prediction, labels=[0, 1]).ravel()
    return {
        "roc_auc": float(roc_auc_score(labels, probabilities)),
        "average_precision": float(average_precision_score(labels, probabilities)),
        "brier": float(brier_score_loss(labels, probabilities)),
        "f1": float(f1_score(labels, prediction, zero_division=0)),
        "sensitivity": float(tp / (tp + fn)),
        "specificity": float(tn / (tn + fp)),
        "prevalence": float(np.mean(labels)),
        "threshold": 0.5,
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


def uncertainty(labels: np.ndarray, probabilities: np.ndarray, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(200):
        indexes = rng.integers(0, len(labels), size=len(labels))
        if len(np.unique(labels[indexes])) == 2:
            draws.append(metrics(labels[indexes], probabilities[indexes]))
    return {
        "method": "subject bootstrap percentile; 200 draws; one sample per subject",
        "valid_draws": len(draws),
        "intervals_95": {
            key: np.quantile([row[key] for row in draws], [0.025, 0.975]).tolist()
            for key in ("roc_auc", "average_precision", "brier", "f1", "sensitivity", "specificity")
        }
        if draws
        else {},
    }


def calibration_bins(labels: np.ndarray, probabilities: np.ndarray) -> list[dict]:
    buckets = np.minimum((probabilities * 10).astype(int), 9)
    return [
        {
            "bin": index,
            "count": int((buckets == index).sum()),
            "mean_probability": float(probabilities[buckets == index].mean()),
            "observed_fraction": float(labels[buckets == index].mean()),
        }
        for index in range(10)
        if (buckets == index).any()
    ]


def run(frame: pd.DataFrame, task: TaskSpec, output: Path, seed: int = 20260916) -> dict:
    frame = validate_data(frame, task)
    if output.exists():
        raise ValueError("output already exists; preserve the previous experiment")
    splits = split_subjects(frame, seed)
    if splits["train"][task.features].isna().all().any():
        raise ValueError("a feature is entirely missing in training; revise task before fitting")
    report = {
        "task": task.model_dump(),
        "seed": seed,
        "clinical_use": False,
        "protocol": "60/20/20 stratified subject split; fixed parameters; no model selection",
        "calibration": "uncalibrated; bins and Brier reported; no clinical threshold",
        "temporal_validation": False,
        "small_sample_note": "minimum class count is an engineering guard, not sample adequacy",
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in ("pandas", "numpy", "scikit-learn", "lightgbm", "joblib")
        },
        "splits": {
            name: {"subjects": len(part), "positives": int(part.label.sum())}
            for name, part in splits.items()
        },
        "models": {},
    }
    predictions = []
    fitted = {}
    for name, model in estimators(seed).items():
        model.fit(splits["train"][task.features], splits["train"].label)
        fitted[name] = model
        report["models"][name] = {}
        for partition in ("validation", "test"):
            part = splits[partition]
            p = model.predict_proba(part[task.features])[:, 1]
            y = part.label.to_numpy(dtype=int)
            report["models"][name][partition] = {
                **metrics(y, p),
                "uncertainty": uncertainty(y, p, seed),
                "calibration_bins": calibration_bins(y, p),
            }
            predictions.extend(
                {
                    "subject_id": subject,
                    "split": partition,
                    "model": name,
                    "label": int(label),
                    "probability": float(probability),
                }
                for subject, label, probability in zip(part.subject_id, y, p, strict=True)
            )
    output.mkdir(parents=True)
    manifest = pd.concat([part[["subject_id"]].assign(split=name) for name, part in splits.items()])
    manifest.sort_values("subject_id").to_csv(output / "splits.csv", index=False)
    report["split_sha256"] = sha256(output / "splits.csv")
    normalized = frame.to_json(orient="records", double_precision=15).encode()
    report["normalized_dataset_sha256"] = hashlib.sha256(normalized).hexdigest()
    report["code_commit"] = (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
        ).stdout.strip()
        or "unknown"
    )
    report["code_dirty"] = bool(
        subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, check=False
        ).stdout.strip()
    )
    pd.DataFrame(predictions).to_csv(output / "predictions.csv", index=False)
    for name, model in fitted.items():
        joblib.dump(
            {"pipeline": model, "task": task.model_dump(), "seed": seed}, output / f"{name}.joblib"
        )
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    task = TaskSpec.model_validate_json(args.task.read_text(encoding="utf-8"))
    if sha256(args.manifest) != task.data_manifest_sha256:
        raise ValueError("source manifest differs from the reviewed task")
    if sha256(args.data) != task.dataset_sha256:
        raise ValueError("cohort dataset differs from the reviewed task")
    run(pd.read_parquet(args.data), task, args.output)
    print("Offline experiment complete; not a clinical model. See report.json.")


if __name__ == "__main__":
    main()
