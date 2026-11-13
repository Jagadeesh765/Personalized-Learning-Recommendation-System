"""Temporal holdout evaluation for the rule-based recommender.

The future holdout is used only to derive relevance labels, never as recommendation input.
A skill is relevant when its mean future assessment score is below 80 and it was
not already mastered at the cutoff and all direct prerequisites were mastered.
"""
import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

from database import connect
from recommendation import get_recommendations

BASE = Path(__file__).resolve().parent


def evaluate_recommendations(k=5, holdout_fraction=0.2, limit_learners=250):
    if not 0 < holdout_fraction < 0.5:
        raise ValueError("holdout_fraction must be greater than 0 and less than 0.5")
    if k < 1:
        raise ValueError("k must be at least 1")

    conn = connect()
    try:
        learner_rows = conn.execute("""
            SELECT learner_id, COUNT(*) AS attempt_count
            FROM attempts
            GROUP BY learner_id
            HAVING COUNT(*) >= 5
            ORDER BY learner_id
            LIMIT ?
        """, (limit_learners,)).fetchall()
        prereq_rows = conn.execute("""
            SELECT skill_id, prerequisite_skill_id, effective_from, effective_to
            FROM skill_prerequisites
        """).fetchall()
    finally:
        conn.close()

    per_learner = []
    skipped_no_relevance = 0
    for learner in learner_rows:
        learner_id = learner["learner_id"]
        conn = connect()
        try:
            attempts = conn.execute("""
                SELECT skill_id, score, attempt_time, attempt_number
                FROM attempts
                WHERE learner_id=?
                ORDER BY attempt_time, attempt_number
            """, (learner_id,)).fetchall()
        finally:
            conn.close()

        n = len(attempts)
        split_at = max(1, min(n - 1, math.floor(n * (1 - holdout_fraction))))
        train_rows = attempts[:split_at]
        test_rows = attempts[split_at:]
        if not train_rows or not test_rows:
            continue

        cutoff = train_rows[-1]["attempt_time"]
        cutoff_date = cutoff[:10]
        train_scores = defaultdict(list)
        for row in train_rows:
            train_scores[row["skill_id"]].append(float(row["score"]))
        train_mastery = {
            skill_id: sum(scores) / len(scores)
            for skill_id, scores in train_scores.items()
        }

        prereqs = defaultdict(list)
        for row in prereq_rows:
            if row["effective_from"] <= cutoff_date and (
                not row["effective_to"] or row["effective_to"] >= cutoff_date
            ):
                prereqs[row["skill_id"]].append(row["prerequisite_skill_id"])

        future_scores = defaultdict(list)
        for row in test_rows:
            future_scores[row["skill_id"]].append(float(row["score"]))

        relevant = set()
        for skill_id, scores in future_scores.items():
            past_mastery = train_mastery.get(skill_id, 0.0)
            future_mean = sum(scores) / len(scores)
            prerequisites_met = all(
                train_mastery.get(prereq_id, 0.0) >= 70.0
                for prereq_id in prereqs.get(skill_id, [])
            )
            if past_mastery < 80.0 and future_mean < 80.0 and prerequisites_met:
                relevant.add(skill_id)

        if not relevant:
            skipped_no_relevance += 1
            continue

        recs = get_recommendations(learner_id, as_of=cutoff, limit=k)
        recommended = [item["skill_id"] for item in recs[:k]]
        hits = len(set(recommended) & relevant)
        precision = hits / k
        recall = hits / len(relevant)
        hit_rate = 1.0 if hits else 0.0
        per_learner.append({
            "learner_id": learner_id,
            "cutoff": cutoff,
            "train_attempts": len(train_rows),
            "holdout_attempts": len(test_rows),
            "relevant_skill_count": len(relevant),
            "recommended_skill_count": len(recommended),
            "hits": hits,
            "precision_at_k": precision,
            "recall_at_k": recall,
            "hit_rate_at_k": hit_rate,
        })

    if per_learner:
        count = len(per_learner)
        metrics = {
            f"precision@{k}": round(sum(x["precision_at_k"] for x in per_learner) / count, 4),
            f"recall@{k}": round(sum(x["recall_at_k"] for x in per_learner) / count, 4),
            f"hit_rate@{k}": round(sum(x["hit_rate_at_k"] for x in per_learner) / count, 4),
        }
    else:
        metrics = {
            f"precision@{k}": 0.0,
            f"recall@{k}": 0.0,
            f"hit_rate@{k}": 0.0,
        }

    result = {
        "status": "PASS" if per_learner else "NO_EVALUABLE_COHORT",
        "method": "Per-learner chronological split; first 80% train, final 20% holdout by default.",
        "relevance_definition": (
            "A held-out skill is relevant when its future mean assessment score is below 80, "
            "its mastery at cutoff is below 80, and all direct prerequisites were mastered "
            "at >=70 using training-period attempts only."
        ),
        "holdout_fraction": holdout_fraction,
        "k": k,
        "candidate_learners": len(learner_rows),
        "evaluated_learners": len(per_learner),
        "skipped_without_relevant_holdout_skill": skipped_no_relevance,
        "metrics": metrics,
        "per_learner_sample": per_learner[:25],
    }

    output_dir = BASE / "outputs"
    output_dir.mkdir(exist_ok=True)
    (output_dir / "evaluation_metrics.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--holdout", type=float, default=0.2)
    parser.add_argument("--limit-learners", type=int, default=250)
    args = parser.parse_args()
    result = evaluate_recommendations(
        k=args.k, holdout_fraction=args.holdout,
        limit_learners=args.limit_learners
    )
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "PASS" else 1)
