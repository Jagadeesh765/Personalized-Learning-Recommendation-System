"""Explainable recommendation engine with temporal mastery and append-only outcomes."""
from datetime import datetime
from database import connect

MASTERY_THRESHOLD = 70.0
MASTERED_THRESHOLD = 80.0


def _cutoff_text(as_of):
    if as_of is None:
        return None
    return as_of.isoformat() if isinstance(as_of, datetime) else str(as_of)


def calculate_mastery(learner_id, as_of=None):
    """Average only attempts at or before as_of; return {skill_id: mastery}."""
    cutoff = _cutoff_text(as_of)
    conn = connect()
    try:
        if not conn.execute(
            "SELECT 1 FROM learners WHERE learner_id=?", (learner_id,)
        ).fetchone():
            raise ValueError(f"Unknown learner: {learner_id}")

        if cutoff is None:
            rows = conn.execute("""
                SELECT skill_id, AVG(score) AS mastery
                FROM attempts
                WHERE learner_id=?
                GROUP BY skill_id
            """, (learner_id,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT skill_id, AVG(score) AS mastery
                FROM attempts
                WHERE learner_id=? AND attempt_time <= ?
                GROUP BY skill_id
            """, (learner_id, cutoff)).fetchall()
        return {r["skill_id"]: round(float(r["mastery"]), 2) for r in rows}
    finally:
        conn.close()


def get_recommendations(learner_id, as_of=None, limit=5):
    """Recommend eligible content using only mastery known at the requested cutoff."""
    cutoff = _cutoff_text(as_of)
    mastery = calculate_mastery(learner_id, cutoff)
    conn = connect()
    try:
        skills = conn.execute("""
            SELECT skill_id, skill_name
            FROM skills
            WHERE status='active'
            ORDER BY skill_id
        """).fetchall()

        effective_date = cutoff[:10] if cutoff else datetime.now().date().isoformat()
        prereq_rows = conn.execute("""
            SELECT skill_id, prerequisite_skill_id
            FROM skill_prerequisites
            WHERE effective_from <= ?
              AND (effective_to IS NULL OR effective_to='' OR effective_to >= ?)
        """, (effective_date, effective_date)).fetchall()
        prereqs = {}
        for row in prereq_rows:
            prereqs.setdefault(row["skill_id"], []).append(row["prerequisite_skill_id"])

        completed = set()
        # Historical offline evaluation intentionally ignores outcomes recorded
        # after its cutoff; live recommendations avoid already-rated content.
        if cutoff is None:
            completed_rows = conn.execute("""
                SELECT DISTINCT r.content_id
                FROM recommendations r
                WHERE r.learner_id=?
                  AND (
                    r.outcome_score IS NOT NULL
                    OR EXISTS (
                        SELECT 1 FROM recommendation_outcomes o
                        WHERE o.recommendation_id=r.recommendation_id
                    )
                  )
            """, (learner_id,)).fetchall()
            completed = {row["content_id"] for row in completed_rows}

        content_rows = conn.execute("""
            SELECT c.content_id, c.content_name, c.difficulty, c.content_type,
                   c.estimated_minutes, cs.skill_id
            FROM content_items c
            JOIN content_skills cs ON cs.content_id=c.content_id
            WHERE c.status='active'
            ORDER BY c.content_id
        """).fetchall()
        content_by_skill = {}
        for row in content_rows:
            content_by_skill.setdefault(row["skill_id"], []).append(row)

        output = []
        for skill in skills:
            sid = skill["skill_id"]
            current = mastery.get(sid, 0.0)
            if current >= MASTERED_THRESHOLD:
                continue

            required = prereqs.get(sid, [])
            if any(mastery.get(prereq, 0.0) < MASTERY_THRESHOLD for prereq in required):
                continue

            rows = [r for r in content_by_skill.get(sid, []) if r["content_id"] not in completed]
            if not rows:
                continue

            desired = "Easy" if current < 40 else ("Medium" if current < 70 else "Hard")
            chosen = next((r for r in rows if r["difficulty"] == desired), rows[0])

            if sid not in mastery:
                reason = "COLD_START"
                explanation = "No previous attempt for this skill; start with an introductory activity."
            elif current < 40:
                reason = "LOW_MASTERY"
                explanation = f"Current mastery is {current:.1f}%; foundational practice is recommended."
            elif current < 70:
                reason = "DEVELOPING_SKILL"
                explanation = f"Current mastery is {current:.1f}%; continue with medium-level practice."
            else:
                reason = "SKILL_IMPROVEMENT"
                explanation = f"Current mastery is {current:.1f}%; advanced practice can strengthen this skill."

            difficulty_score = {"Easy": 1, "Medium": 3, "Hard": 5}[chosen["difficulty"]]
            # Transparent priority score: lower mastery and harder suitable content
            # receive a higher rank; cold-start mastery is treated as zero.
            ranking = round((100 - current) * 0.7 + difficulty_score * 4, 2)
            output.append({
                "content_id": chosen["content_id"],
                "content_name": chosen["content_name"],
                "skill_id": sid,
                "skill_name": skill["skill_name"],
                "mastery": current,
                "difficulty": chosen["difficulty"],
                "content_type": chosen["content_type"],
                "estimated_minutes": chosen["estimated_minutes"],
                "reason_code": reason,
                "explanation": explanation,
                "ranking_score": ranking,
            })

        output.sort(key=lambda item: (-item["ranking_score"], item["content_id"]))
        return output[:max(1, min(int(limit), 100))]
    finally:
        conn.close()


def save_recommendations(learner_id, recommendations):
    """Persist recommendation decisions as immutable history records."""
    if not recommendations:
        return []
    conn = connect()
    ids = []
    try:
        now = datetime.now().isoformat()
        rows = []
        for item in recommendations:
            recommendation_id = conn.execute(
                "SELECT lower(hex(randomblob(16)))"
            ).fetchone()[0]
            ids.append(recommendation_id)
            rows.append((
                recommendation_id, learner_id, item["content_id"], item["skill_id"],
                item["reason_code"], item["explanation"], item["ranking_score"], now
            ))
        with conn:
            conn.executemany("""
                INSERT INTO recommendations
                (recommendation_id, learner_id, content_id, skill_id, reason_code,
                 explanation, ranking_score, recommendation_time)
                VALUES (?,?,?,?,?,?,?,?)
            """, rows)
        return ids
    finally:
        conn.close()


def record_outcome(recommendation_id, outcome_score, outcome_type="ASSESSMENT", notes=None):
    """Append a new outcome event; never overwrite earlier outcome records."""
    outcome_score = float(outcome_score)
    if not 0 <= outcome_score <= 100:
        raise ValueError("outcome_score must be between 0 and 100")
    if outcome_type not in {"ASSESSMENT", "COMPLETION", "FEEDBACK"}:
        raise ValueError("outcome_type must be ASSESSMENT, COMPLETION, or FEEDBACK")
    conn = connect()
    try:
        exists = conn.execute(
            "SELECT 1 FROM recommendations WHERE recommendation_id=?",
            (recommendation_id,)
        ).fetchone()
        if not exists:
            raise ValueError(f"Recommendation not found: {recommendation_id}")
        outcome_id = conn.execute(
            "SELECT lower(hex(randomblob(16)))"
        ).fetchone()[0]
        recorded_at = datetime.now().isoformat()
        with conn:
            conn.execute("""
                INSERT INTO recommendation_outcomes
                (outcome_id, recommendation_id, outcome_score, outcome_type, notes, recorded_at)
                VALUES (?,?,?,?,?,?)
            """, (outcome_id, recommendation_id, outcome_score,
                  outcome_type, notes, recorded_at))
        return {
            "outcome_id": outcome_id,
            "recommendation_id": recommendation_id,
            "outcome_score": outcome_score,
            "outcome_type": outcome_type,
            "recorded_at": recorded_at,
        }
    finally:
        conn.close()
