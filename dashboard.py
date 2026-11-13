"""Pandas-free Streamlit dashboard using SQLite queries and basic Streamlit widgets."""
from pathlib import Path
import streamlit as st

from database import connect, ensure_extensions
from recommendation import get_recommendations, save_recommendations, record_outcome
from validation import validate_database, evaluate_anomaly_fixtures

st.set_page_config(
    page_title="Personalized Learning",
    page_icon="📚",
    layout="wide"
)

DB = Path(__file__).resolve().parent / "learning.db"
st.title("📚 Personalized Learning Recommendation System")
st.caption("Recommendations based on learner mastery, prerequisites and content difficulty.")

if not DB.exists():
    st.error("Database not found. Run the setup commands from README.md.")
    st.stop()

try:
    ensure_extensions()
except Exception as exc:
    st.error(f"Database initialization issue: {exc}")
    st.stop()


def fetch_all(query, params=()):
    conn = connect()
    try:
        cursor = conn.execute(query, params)
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        conn.close()


def fetch_one(query, params=()):
    conn = connect()
    try:
        row = conn.execute(query, params).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


metrics = {
    "learners": fetch_one("SELECT COUNT(*) FROM learners"),
    "skills": fetch_one("SELECT COUNT(*) FROM skills"),
    "content": fetch_one("SELECT COUNT(*) FROM content_items"),
    "attempts": fetch_one("SELECT COUNT(*) FROM attempts"),
    "recommendations": fetch_one("SELECT COUNT(*) FROM recommendations"),
    "outcomes": fetch_one("SELECT COUNT(*) FROM recommendation_outcomes"),
}

columns = st.columns(6)
for column, label, key in zip(
    columns,
    ["Learners", "Skills", "Content", "Attempts", "Recommendations", "Recorded outcomes"],
    ["learners", "skills", "content", "attempts", "recommendations", "outcomes"],
):
    column.metric(label, f"{metrics[key]:,}")

tab1, tab2, tab3 = st.tabs([
    "Learner recommendations",
    "Administrator",
    "Data validation"
])

with tab1:
    learners = fetch_all("""
        SELECT learner_id, learner_name
        FROM learners
        ORDER BY learner_id
    """)
    if not learners:
        st.warning("No learners found.")
    else:
        options = {
            f"{row['learner_name']} ({row['learner_id']})": row["learner_id"]
            for row in learners
        }
        selected = st.selectbox("Select learner", list(options))
        learner_id = options[selected]

        if st.button("Analyze learner and recommend activities", type="primary"):
            try:
                recs = get_recommendations(learner_id, limit=5)
                saved_ids = save_recommendations(learner_id, recs)

                attempts = fetch_all("""
                    SELECT s.skill_name, ROUND(AVG(a.score), 2) AS mastery,
                           COUNT(*) AS attempts
                    FROM attempts a
                    JOIN skills s ON s.skill_id=a.skill_id
                    WHERE a.learner_id=?
                    GROUP BY s.skill_id
                    ORDER BY s.skill_name
                """, (learner_id,))

                st.subheader("Skill mastery")
                if not attempts:
                    st.info("Cold-start learner: no previous assessment attempts.")
                else:
                    for item in attempts:
                        score = max(0, min(100, float(item["mastery"] or 0)))
                        st.write(
                            f"**{item['skill_name']}** — {score:.1f}% mastery "
                            f"({item['attempts']} attempts)"
                        )
                        st.progress(int(score))

                st.subheader("Recommended next learning activities")
                if not recs:
                    st.warning("No eligible activities found.")
                else:
                    for index, rec in enumerate(recs, 1):
                        with st.expander(
                            f"{index}. {rec['content_name']} — {rec['reason_code']}"
                        ):
                            st.write("**Skill:**", rec["skill_name"])
                            st.write("**Explanation:**", rec["explanation"])
                            st.write("**Mastery:**", rec["mastery"], "%")
                            st.write("**Difficulty:**", rec["difficulty"])
                            st.write("**Format:**", rec["content_type"])
                            st.write("**Estimated time:**", rec["estimated_minutes"], "minutes")
                            st.write("**Ranking score:**", rec["ranking_score"])
                st.caption(
                    f"Saved {len(saved_ids)} recommendation history records. "
                    "The recommender uses transparent rules and reason codes."
                )
            except Exception as exc:
                st.error(f"Could not generate recommendations: {exc}")

with tab2:
    st.subheader("Platform overview")
    st.write("Mastery is calculated from historical assessment scores at the requested cutoff.")

    top_skills = fetch_all("""
        SELECT s.skill_name, ROUND(AVG(a.score), 2) AS average_score,
               COUNT(*) AS attempts
        FROM attempts a
        JOIN skills s ON s.skill_id=a.skill_id
        GROUP BY s.skill_id
        ORDER BY average_score DESC
        LIMIT 10
    """)
    st.subheader("Top 10 skills by average score")
    if top_skills:
        for item in top_skills:
            st.write(
                f"**{item['skill_name']}** — {item['average_score']}% "
                f"({item['attempts']} attempts)"
            )
            st.progress(max(0, min(100, int(item["average_score"] or 0))))
    else:
        st.info("No assessment data available.")

    st.subheader("Latest recommendation history")
    history = fetch_all("""
        SELECT r.recommendation_id, r.learner_id, r.content_id,
               r.reason_code, r.ranking_score, r.recommendation_time,
               COUNT(o.outcome_id) AS outcome_count,
               (SELECT o2.outcome_score FROM recommendation_outcomes o2
                WHERE o2.recommendation_id=r.recommendation_id
                ORDER BY o2.recorded_at DESC, o2.outcome_id DESC LIMIT 1)
                    AS latest_outcome_score
        FROM recommendations r
        LEFT JOIN recommendation_outcomes o
          ON o.recommendation_id=r.recommendation_id
        GROUP BY r.recommendation_id
        ORDER BY r.recommendation_time DESC
        LIMIT 100
    """)
    if history:
        st.json(history)
    else:
        st.info("No recommendation history available yet.")

    st.subheader("Record a learning outcome")
    outcome_options = {
        f"{row['recommendation_id']} | {row['learner_id']} | {row['content_id']}": row["recommendation_id"]
        for row in history
    }
    if outcome_options:
        selected_outcome = st.selectbox(
            "Recommendation to record an outcome for", list(outcome_options)
        )
        outcome_score = st.slider("Outcome assessment score", 0, 100, 75)
        outcome_type = st.selectbox(
            "Outcome type", ["ASSESSMENT", "COMPLETION", "FEEDBACK"]
        )
        outcome_notes = st.text_input("Optional outcome note", max_chars=500)
        if st.button("Save outcome as a new history event"):
            try:
                result = record_outcome(
                    outcome_options[selected_outcome], outcome_score,
                    outcome_type, outcome_notes or None
                )
                st.success(f"Outcome saved: {result['outcome_id']}")
                st.caption("Outcome history is append-only; earlier outcomes are preserved.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not record outcome: {exc}")
    else:
        st.info("Generate at least one recommendation before recording an outcome.")

with tab3:
    st.subheader("Database validation")
    if st.button("Run validation checks"):
        st.write("Database integrity results")
        st.json(validate_database())
        st.subheader("Known anomaly test fixtures and ground truth")
        st.json(evaluate_anomaly_fixtures())

st.caption("Personalized Learning Recommendation System")
