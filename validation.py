"""Database integrity, anomaly fixture, and ground-truth separation checks."""
import csv
from pathlib import Path

from database import connect, ensure_extensions
from anomaly_checks import (
    check_prerequisite_eligibility, check_attempt_timestamps,
    check_content_skill_reference, check_no_future_attempts,
    check_learning_path_progress
)

BASE = Path(__file__).resolve().parent
REQUIRED_ANOMALIES = {
    "PREREQUISITE_VIOLATION": "REJECT",
    "INVALID_TIMESTAMP": "FLAG",
    "INVALID_SKILL_REFERENCE": "FLAG",
    "FUTURE_DATA_LEAKAGE": "REJECT",
    "NO_PROGRESS_LOOP": "FLAG",
}
ANOMALY_ID_TABLES = {
    "PREREQUISITE_VIOLATION": ("recommendations", "recommendation_id"),
    "INVALID_TIMESTAMP": ("attempts", "attempt_id"),
    "INVALID_SKILL_REFERENCE": ("content_items", "content_id"),
    "FUTURE_DATA_LEAKAGE": (None, None),
    "NO_PROGRESS_LOOP": ("learning_paths", "path_id"),
}


def validate_database():
    ensure_extensions()
    conn = connect()
    issues = []
    try:
        fk = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk:
            issues.append({"issue_type": "FOREIGN_KEY_VIOLATION", "count": len(fk)})

        primary_keys = [
            ("learners", "learner_id"), ("courses", "course_id"),
            ("skills", "skill_id"), ("skill_prerequisites", "prerequisite_id"),
            ("content_items", "content_id"), ("content_skills", "content_skill_id"),
            ("attempts", "attempt_id"), ("assessment_results", "assessment_result_id"),
            ("learning_paths", "path_id"), ("recommendations", "recommendation_id"),
            ("recommendation_outcomes", "outcome_id"),
        ]
        for table, key in primary_keys:
            dup = conn.execute(
                f"SELECT COUNT(*) FROM (SELECT {key} FROM {table} GROUP BY {key} HAVING COUNT(*)>1)"
            ).fetchone()[0]
            if dup:
                issues.append({"issue_type": "DUPLICATE_PRIMARY_KEY", "table": table, "count": dup})

        invalid_scores = conn.execute(
            "SELECT COUNT(*) FROM attempts WHERE score < 0 OR score > 100"
        ).fetchone()[0]
        if invalid_scores:
            issues.append({"issue_type": "INVALID_SCORE", "count": invalid_scores})

        bad_results = conn.execute("""
            SELECT COUNT(*) FROM assessment_results ar
            JOIN attempts a ON a.attempt_id=ar.attempt_id
            WHERE ar.score <> a.score OR ar.graded_at < a.attempt_time
        """).fetchone()[0]
        if bad_results:
            issues.append({"issue_type": "ASSESSMENT_RECONCILIATION", "count": bad_results})

        missing_results = conn.execute("""
            SELECT COUNT(*) FROM attempts a
            LEFT JOIN assessment_results ar ON ar.attempt_id=a.attempt_id
            WHERE ar.attempt_id IS NULL
        """).fetchone()[0]
        if missing_results:
            issues.append({"issue_type": "MISSING_ASSESSMENT_RESULT", "count": missing_results})

        time_inversions = conn.execute("""
            SELECT COUNT(*) FROM (
                SELECT learner_id, attempt_time,
                       LAG(attempt_time) OVER (
                           PARTITION BY learner_id ORDER BY attempt_number
                       ) AS previous_time
                FROM attempts
            )
            WHERE previous_time IS NOT NULL AND attempt_time < previous_time
        """).fetchone()[0]
        if time_inversions:
            issues.append({"issue_type": "ATTEMPT_TIME_ORDER", "count": time_inversions})

        invalid_outcomes = conn.execute("""
            SELECT COUNT(*) FROM recommendation_outcomes
            WHERE outcome_score < 0 OR outcome_score > 100
        """).fetchone()[0]
        if invalid_outcomes:
            issues.append({"issue_type": "INVALID_OUTCOME_SCORE", "count": invalid_outcomes})

        counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in [
                "learners", "courses", "skills", "skill_prerequisites",
                "content_items", "content_skills", "attempts",
                "assessment_results", "learning_paths", "recommendations",
                "recommendation_outcomes",
            ]
        }
        return {"status": "PASS" if not issues else "FAIL",
                "issues": issues, "counts": counts}
    finally:
        conn.close()


def validate_ground_truth():
    """Confirm labels match and anomaly-only IDs never enter baseline input tables."""
    anomaly_path = BASE / "outputs" / "anomaly_cases.csv"
    truth_path = BASE / "outputs" / "ground_truth.csv"
    if not anomaly_path.exists() or not truth_path.exists():
        return {"status": "FAIL", "issues": ["anomaly_cases.csv or ground_truth.csv is missing"]}

    def read_rows(path):
        with path.open(newline="", encoding="utf-8") as stream:
            return list(csv.DictReader(stream))

    cases = read_rows(anomaly_path)
    truth = read_rows(truth_path)
    issues = []
    case_map = {row.get("issue_type"): row for row in cases}
    truth_map = {row.get("issue_type"): row for row in truth}

    if set(case_map) != set(REQUIRED_ANOMALIES):
        issues.append("anomaly_cases.csv does not contain exactly the five required issue types")
    if set(truth_map) != set(REQUIRED_ANOMALIES):
        issues.append("ground_truth.csv does not contain exactly the five required issue types")

    for issue_type, expected in REQUIRED_ANOMALIES.items():
        case = case_map.get(issue_type)
        label = truth_map.get(issue_type)
        if not case or not label:
            continue
        if case.get("expected_result") != expected or label.get("expected_result") != expected:
            issues.append(f"Incorrect expected_result for {issue_type}")
        for key in ("case_id", "record_id", "expected_result"):
            if case.get(key) != label.get(key):
                issues.append(f"anomaly_cases.csv and ground_truth.csv disagree for {issue_type}:{key}")

        table, column = ANOMALY_ID_TABLES[issue_type]
        if table and column:
            conn = connect()
            try:
                found = conn.execute(
                    f"SELECT 1 FROM {table} WHERE {column}=? LIMIT 1",
                    (case.get("record_id"),)
                ).fetchone()
            finally:
                conn.close()
            if found:
                issues.append(f"Anomaly-only record {case.get('record_id')} leaked into {table}")

    return {
        "status": "PASS" if not issues else "FAIL",
        "case_count": len(cases),
        "ground_truth_count": len(truth),
        "issues": issues,
    }


def evaluate_anomaly_fixtures():
    """Run concrete positive/negative examples for each required exception."""
    examples = [
        ("PREREQUISITE_VIOLATION",
         check_prerequisite_eligibility({"SKL-000002": 45})[0] is False),
        ("INVALID_TIMESTAMP",
         check_attempt_timestamps("2026-01-02T10:00:00", "2026-01-01T10:00:00")[0] is False),
        ("INVALID_SKILL_REFERENCE",
         check_content_skill_reference("SKL-MISSING", {"SKL-000001"})[0] is False),
        ("FUTURE_DATA_LEAKAGE",
         check_no_future_attempts(["2026-01-02T00:00:00"], "2026-01-01T00:00:00")[0] is False),
        ("NO_PROGRESS_LOOP",
         check_learning_path_progress([
             {"event_type": "activity", "activity_id": "CNT-1"},
             {"event_type": "activity", "activity_id": "CNT-1"}
         ])[0] is False),
    ]
    labels = validate_ground_truth()
    results = []
    for issue_type, detected in examples:
        expected = REQUIRED_ANOMALIES[issue_type]
        results.append({
            "issue_type": issue_type,
            "expected": expected,
            "detected": detected,
            "pass": detected,
        })
    passed = all(row["pass"] for row in results) and labels["status"] == "PASS"
    return {
        "status": "PASS" if passed else "FAIL",
        "cases": results,
        "ground_truth": labels,
    }
