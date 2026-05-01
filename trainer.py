"""
Daily logistic regression trainer.

Reads labels from feedback_store, trains a LogisticRegression,
saves weights back to data/model.json.

Minimum labels to train: 10 (ideally ≥5 per class).
"""

from __future__ import annotations

from feedback_store import (
    get_labels, save_model, feature_vector,
    FEATURE_NAMES, label_counts,
)

MIN_LABELS     = 2000   # total (2000 = 1000 pos + 1000 neg minimum)
MIN_PER_CLASS  = 1000


def train() -> dict:
    """
    Train the model and return a status dict.
    """
    labels = get_labels()
    counts = label_counts()

    if counts["total"] < MIN_LABELS:
        return {
            "status":  "skipped",
            "reason":  f"Need ≥{MIN_LABELS} labels, have {counts['total']}",
            "counts":  counts,
        }
    if counts["positive"] < MIN_PER_CLASS or counts["negative"] < MIN_PER_CLASS:
        return {
            "status": "skipped",
            "reason": f"Need ≥{MIN_PER_CLASS} per class — pos={counts['positive']} neg={counts['negative']}",
            "counts": counts,
        }

    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_score
    import numpy as np

    X = np.array([feature_vector(l["features"]) for l in labels])
    y = np.array([l["label"] for l in labels])

    model = LogisticRegression(max_iter=500, class_weight="balanced")
    model.fit(X, y)

    # Cross-val accuracy (3-fold, gracefully handles small datasets)
    n_folds = min(3, counts["positive"], counts["negative"])
    if n_folds >= 2:
        cv_scores = cross_val_score(model, X, y, cv=n_folds, scoring="accuracy")
        accuracy  = float(cv_scores.mean())
    else:
        accuracy = float((model.predict(X) == y).mean())

    weights   = model.coef_[0].tolist()
    intercept = float(model.intercept_[0])

    save_model(
        weights=weights,
        intercept=intercept,
        accuracy=accuracy,
        trained_on=len(labels),
    )

    # Feature importance report
    importance = sorted(
        zip(FEATURE_NAMES, weights),
        key=lambda x: abs(x[1]),
        reverse=True,
    )

    print(f"[Trainer] Model trained on {len(labels)} labels | accuracy={accuracy:.2%}")
    print("[Trainer] Feature importance:")
    for name, w in importance:
        bar = "█" * int(abs(w) * 10)
        sign = "+" if w > 0 else "-"
        print(f"  {sign}{bar:<12} {name} ({w:+.3f})")

    return {
        "status":     "trained",
        "accuracy":   accuracy,
        "trained_on": len(labels),
        "counts":     counts,
        "importance": [{"feature": n, "weight": w} for n, w in importance],
    }


if __name__ == "__main__":
    result = train()
    print(result)
