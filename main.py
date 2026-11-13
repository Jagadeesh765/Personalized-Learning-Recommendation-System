"""FastAPI application for learner recommendations and outcome events."""
from datetime import datetime
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Literal

from database import connect, ensure_extensions
from recommendation import (
    get_recommendations, save_recommendations, calculate_mastery, record_outcome
)
from validation import validate_database, evaluate_anomaly_fixtures

app = FastAPI(
    title="Personalized Learning Recommendation System",
    version="1.1.0",
    description="Skill, prerequisite and assessment-driven learning recommendations."
)


class AttemptInput(BaseModel):
    learner_id: str
    skill_id: str
    score: float = Field(ge=0, le=100)
    attempt_time: datetime
    duration_minutes: int = Field(gt=0, le=600)


class OutcomeInput(BaseModel):
    recommendation_id: str
    outcome_score: float = Field(ge=0, le=100)
    outcome_type: Literal["ASSESSMENT", "COMPLETION", "FEEDBACK"] = "ASSESSMENT"
    notes: str | None = Field(default=None, max_length=500)


@app.on_event("startup")
def startup_migration():
    ensure_extensions()


@app.get("/")
def home():
    return {
        "message": "Personalized Learning Recommendation API is running",
        "docs": "/docs",
    }


@app.get("/learners")
def list_learners(limit: int = 100):
    conn = connect()
    try:
        rows = conn.execute("""
            SELECT learner_id, learner_name, status
            FROM learners ORDER BY learner_id LIMIT ?
        """, (min(max(limit, 1), 1000),)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


@app.get("/learners/{learner_id}/mastery")
def learner_mastery(learner_id: str, as_of: str | None = None):
    try:
        mastery = calculate_mastery(learner_id, as_of)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    conn = connect()
    try:
        names = {
            row["skill_id"]: row["skill_name"]
            for row in conn.execute("SELECT skill_id, skill_name FROM skills")
        }
        return [
            {"skill_id": skill_id, "skill_name": names.get(skill_id, skill_id),
             "mastery": score}
            for skill_id, score in mastery.items()
        ]
    finally:
        conn.close()


@app.get("/learners/{learner_id}/recommendations")
def learner_recommendations(learner_id: str, limit: int = 5, as_of: str | None = None):
    try:
        items = get_recommendations(
            learner_id, as_of=as_of, limit=min(max(limit, 1), 20)
        )
        saved_ids = save_recommendations(learner_id, items)
        return {
            "learner_id": learner_id,
            "recommendations": items,
            "saved_recommendation_ids": saved_ids,
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/attempts")
def add_attempt(data: AttemptInput):
    conn = connect()
    try:
        if not conn.execute(
            "SELECT 1 FROM learners WHERE learner_id=?", (data.learner_id,)
        ).fetchone():
            raise HTTPException(status_code=404, detail="Learner not found")
        if not conn.execute(
            "SELECT 1 FROM skills WHERE skill_id=?", (data.skill_id,)
        ).fetchone():
            raise HTTPException(status_code=404, detail="Skill not found")

        stamp = data.attempt_time.isoformat()
        last = conn.execute(
            "SELECT MAX(attempt_time) FROM attempts WHERE learner_id=?",
            (data.learner_id,)
        ).fetchone()[0]
        if last and stamp < last:
            raise HTTPException(
                status_code=400,
                detail="Attempt timestamp must not precede the learner's latest attempt"
            )

        number = conn.execute(
            "SELECT COALESCE(MAX(attempt_number),0)+1 FROM attempts WHERE learner_id=?",
            (data.learner_id,)
        ).fetchone()[0]
        attempt_id = f"ATT-{data.learner_id}-{number:06d}"
        result_id = f"RES-NEW-{attempt_id}"
        result_status = "Passed" if data.score >= 70 else "Needs Improvement"

        with conn:
            conn.execute("""
                INSERT INTO attempts
                (attempt_id, learner_id, skill_id, score, attempt_time, attempt_number, duration_minutes)
                VALUES (?,?,?,?,?,?,?)
            """, (
                attempt_id, data.learner_id, data.skill_id, data.score,
                stamp, number, data.duration_minutes
            ))
            conn.execute("""
                INSERT INTO assessment_results
                (assessment_result_id, attempt_id, score, result_status, graded_at)
                VALUES (?,?,?,?,?)
            """, (result_id, attempt_id, data.score, result_status, stamp))

        return {
            "status": "recorded",
            "attempt_id": attempt_id,
            "assessment_result_id": result_id,
            "result_status": result_status,
        }
    finally:
        conn.close()


@app.post("/outcomes")
def add_outcome(data: OutcomeInput):
    try:
        return {
            "status": "outcome appended",
            **record_outcome(
                data.recommendation_id, data.outcome_score,
                data.outcome_type, data.notes
            )
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/recommendations/{recommendation_id}/outcomes")
def recommendation_outcomes(recommendation_id: str):
    conn = connect()
    try:
        exists = conn.execute(
            "SELECT 1 FROM recommendations WHERE recommendation_id=?",
            (recommendation_id,)
        ).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        rows = conn.execute("""
            SELECT outcome_id, recommendation_id, outcome_score,
                   outcome_type, notes, recorded_at
            FROM recommendation_outcomes
            WHERE recommendation_id=?
            ORDER BY recorded_at, outcome_id
        """, (recommendation_id,)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


@app.get("/metrics")
def metrics():
    conn = connect()
    try:
        counts = {}
        for table in [
            "learners", "courses", "skills", "content_items", "attempts",
            "assessment_results", "learning_paths", "recommendations",
            "recommendation_outcomes",
        ]:
            counts[table] = conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]

        counts["recorded_outcomes"] = counts["recommendation_outcomes"]
        counts["learners_with_recommendations"] = conn.execute(
            "SELECT COUNT(DISTINCT learner_id) FROM recommendations"
        ).fetchone()[0]
        counts["recommendation_coverage_pct"] = round(
            100 * counts["learners_with_recommendations"] / max(counts["learners"], 1), 2
        )
        counts["recommendations_with_outcomes"] = conn.execute("""
            SELECT COUNT(DISTINCT recommendation_id)
            FROM recommendation_outcomes
        """).fetchone()[0]
        return counts
    finally:
        conn.close()


@app.get("/validation")
def validation():
    return {
        "database": validate_database(),
        "anomaly_fixtures": evaluate_anomaly_fixtures(),
    }


@app.get("/recommendation-history/{learner_id}")
def recommendation_history(learner_id: str):
    conn = connect()
    try:
        rows = conn.execute("""
            SELECT r.recommendation_id, r.content_id, r.skill_id, r.reason_code,
                   r.explanation, r.ranking_score, r.recommendation_time,
                   COUNT(o.outcome_id) AS outcome_count,
                   (SELECT o2.outcome_score FROM recommendation_outcomes o2
                    WHERE o2.recommendation_id=r.recommendation_id
                    ORDER BY o2.recorded_at DESC, o2.outcome_id DESC LIMIT 1)
                       AS latest_outcome_score,
                   (SELECT o2.recorded_at FROM recommendation_outcomes o2
                    WHERE o2.recommendation_id=r.recommendation_id
                    ORDER BY o2.recorded_at DESC, o2.outcome_id DESC LIMIT 1)
                       AS latest_outcome_at
            FROM recommendations r
            LEFT JOIN recommendation_outcomes o
              ON o.recommendation_id=r.recommendation_id
            WHERE r.learner_id=?
            GROUP BY r.recommendation_id
            ORDER BY r.recommendation_time DESC
        """, (learner_id,)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
