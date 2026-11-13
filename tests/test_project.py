from collections import defaultdict
import json

import database
import generate_data
import validation
from recommendation import (
    calculate_mastery, get_recommendations, save_recommendations, record_outcome
)
from evaluate_recommendations import evaluate_recommendations
from anomaly_checks import (
    check_prerequisite_eligibility, check_attempt_timestamps,
    check_content_skill_reference, check_no_future_attempts,
    check_learning_path_progress
)


def test_database_integrity_and_full_relationships(sample_project):
    result = validation.validate_database()
    assert result["status"] == "PASS"
    assert result["counts"]["learners"] == 100
    assert result["counts"]["attempts"] == 1000
    assert result["counts"]["assessment_results"] == 1000


def test_mastery_cutoff_excludes_future_attempts(sample_project):
    conn = database.connect()
    try:
        rows = conn.execute("""
            SELECT skill_id, score, attempt_time
            FROM attempts
            WHERE learner_id=?
            ORDER BY attempt_time, attempt_number
        """, ("LRN-000011",)).fetchall()
    finally:
        conn.close()
    assert len(rows) >= 2
    first = rows[0]
    mastery = calculate_mastery("LRN-000011", as_of=first["attempt_time"])
    assert mastery[first["skill_id"]] == float(first["score"])


def test_recommendations_include_explanations_and_reason_codes(sample_project):
    recommendations = get_recommendations("LRN-000001", limit=5)
    assert recommendations
    assert all(item["reason_code"] for item in recommendations)
    assert all(item["explanation"] for item in recommendations)
    assert all(item["ranking_score"] >= 0 for item in recommendations)


def test_append_only_outcomes_preserve_every_event(sample_project):
    recommendations = get_recommendations("LRN-000001", limit=1)
    ids = save_recommendations("LRN-000001", recommendations)
    assert len(ids) == 1

    first = record_outcome(ids[0], 72, "ASSESSMENT", "First attempt")
    second = record_outcome(ids[0], 88, "ASSESSMENT", "Retake")
    assert first["outcome_id"] != second["outcome_id"]

    conn = database.connect()
    try:
        rows = conn.execute("""
            SELECT outcome_score, notes
            FROM recommendation_outcomes
            WHERE recommendation_id=?
            ORDER BY recorded_at, outcome_id
        """, (ids[0],)).fetchall()
        legacy = conn.execute(
            "SELECT outcome_score FROM recommendations WHERE recommendation_id=?",
            (ids[0],)
        ).fetchone()[0]
    finally:
        conn.close()

    assert [row["outcome_score"] for row in rows] == [72, 88]
    assert [row["notes"] for row in rows] == ["First attempt", "Retake"]
    assert legacy is None


def test_temporal_evaluation_produces_metrics(sample_project):
    result = evaluate_recommendations(k=3, holdout_fraction=0.2, limit_learners=60)
    assert result["status"] == "PASS"
    assert result["evaluated_learners"] > 0
    assert "precision@3" in result["metrics"]
    assert "recall@3" in result["metrics"]
    assert "hit_rate@3" in result["metrics"]
    assert 0 <= result["metrics"]["precision@3"] <= 1
    assert 0 <= result["metrics"]["recall@3"] <= 1


def test_ground_truth_matches_anomaly_labels_and_is_separate(sample_project):
    result = validation.validate_ground_truth()
    assert result["status"] == "PASS"
    assert result["case_count"] == 5
    assert result["ground_truth_count"] == 5


def test_all_five_anomaly_scenarios_pass(sample_project):
    result = validation.evaluate_anomaly_fixtures()
    assert result["status"] == "PASS"
    assert len(result["cases"]) == 5
    assert all(case["pass"] for case in result["cases"])


def test_prerequisite_violation_is_rejected():
    accepted, reason = check_prerequisite_eligibility({"SKL-000002": 45})
    assert not accepted
    assert reason.startswith("PREREQUISITE_NOT_MET")


def test_invalid_timestamp_is_flagged():
    accepted, reason = check_attempt_timestamps(
        "2026-01-02T10:00:00", "2026-01-01T10:00:00"
    )
    assert not accepted
    assert reason == "INVALID_TIMESTAMP"


def test_nonexistent_skill_mapping_is_flagged():
    accepted, reason = check_content_skill_reference("SKL-MISSING", {"SKL-000001"})
    assert not accepted
    assert reason == "INVALID_SKILL_REFERENCE"


def test_future_attempt_is_excluded():
    accepted, reason = check_no_future_attempts(
        ["2026-01-02T00:00:00"], "2026-01-01T00:00:00"
    )
    assert not accepted
    assert reason == "FUTURE_DATA_LEAKAGE"


def test_repeated_path_without_progress_is_flagged():
    accepted, reason = check_learning_path_progress([
        {"event_type": "activity", "activity_id": "CNT-1"},
        {"event_type": "activity", "activity_id": "CNT-1"},
    ])
    assert not accepted
    assert reason == "NO_PROGRESS_LOOP"


def test_regeneration_checksums_are_deterministic(sample_project, tmp_path):
    first = tmp_path / "run-one"
    second = tmp_path / "run-two"
    generate_data.generate("starter", output_dir=first)
    generate_data.generate("starter", output_dir=second)
    one = json.loads((first / "outputs" / "source_manifest.json").read_text())
    two = json.loads((second / "outputs" / "source_manifest.json").read_text())
    assert one["row_counts"] == two["row_counts"]
    assert one["files"] == two["files"]


def test_database_uses_wal_and_busy_timeout(sample_project):
    conn = database.connect()
    try:
        timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert timeout >= 1000
    finally:
        conn.close()


def test_outcome_rejects_invalid_score(sample_project):
    recommendations = get_recommendations("LRN-000001", limit=1)
    recommendation_id = save_recommendations("LRN-000001", recommendations)[0]
    import pytest
    with pytest.raises(ValueError):
        record_outcome(recommendation_id, 101)
