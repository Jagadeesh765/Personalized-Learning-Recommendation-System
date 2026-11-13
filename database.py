"""SQLite schema, safe connections, migrations, and CSV loading."""
import argparse
import csv
import sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "learning.db"
DATA = BASE / "data"
BUSY_TIMEOUT_MS = 30_000

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS courses (
 course_id TEXT PRIMARY KEY, course_name TEXT NOT NULL, status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS learners (
 learner_id TEXT PRIMARY KEY, learner_name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
 created_at TEXT NOT NULL, status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS skills (
 skill_id TEXT PRIMARY KEY, course_id TEXT NOT NULL, skill_name TEXT NOT NULL,
 description TEXT, status TEXT NOT NULL,
 FOREIGN KEY(course_id) REFERENCES courses(course_id)
);
CREATE TABLE IF NOT EXISTS skill_prerequisites (
 prerequisite_id TEXT PRIMARY KEY, skill_id TEXT NOT NULL,
 prerequisite_skill_id TEXT NOT NULL, effective_from TEXT NOT NULL, effective_to TEXT,
 FOREIGN KEY(skill_id) REFERENCES skills(skill_id),
 FOREIGN KEY(prerequisite_skill_id) REFERENCES skills(skill_id),
 UNIQUE(skill_id, prerequisite_skill_id), CHECK(skill_id <> prerequisite_skill_id)
);
CREATE TABLE IF NOT EXISTS content_items (
 content_id TEXT PRIMARY KEY, content_name TEXT NOT NULL, difficulty TEXT NOT NULL
 CHECK(difficulty IN ('Easy','Medium','Hard')),
 content_type TEXT NOT NULL CHECK(content_type IN ('Video','Quiz','Exercise','Article')),
 estimated_minutes INTEGER NOT NULL CHECK(estimated_minutes > 0), status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS content_skills (
 content_skill_id TEXT PRIMARY KEY, content_id TEXT NOT NULL, skill_id TEXT NOT NULL,
 weight REAL NOT NULL CHECK(weight >= 0 AND weight <= 1),
 FOREIGN KEY(content_id) REFERENCES content_items(content_id),
 FOREIGN KEY(skill_id) REFERENCES skills(skill_id),
 UNIQUE(content_id, skill_id)
);
CREATE TABLE IF NOT EXISTS attempts (
 attempt_id TEXT PRIMARY KEY, learner_id TEXT NOT NULL, skill_id TEXT NOT NULL,
 score REAL NOT NULL CHECK(score >= 0 AND score <= 100), attempt_time TEXT NOT NULL,
 attempt_number INTEGER NOT NULL, duration_minutes INTEGER NOT NULL,
 FOREIGN KEY(learner_id) REFERENCES learners(learner_id),
 FOREIGN KEY(skill_id) REFERENCES skills(skill_id),
 UNIQUE(learner_id, attempt_number)
);
CREATE TABLE IF NOT EXISTS assessment_results (
 assessment_result_id TEXT PRIMARY KEY, attempt_id TEXT UNIQUE NOT NULL,
 score REAL NOT NULL CHECK(score >= 0 AND score <= 100),
 result_status TEXT NOT NULL, graded_at TEXT NOT NULL,
 FOREIGN KEY(attempt_id) REFERENCES attempts(attempt_id)
);
CREATE TABLE IF NOT EXISTS learning_paths (
 path_id TEXT PRIMARY KEY, learner_id TEXT NOT NULL, course_id TEXT NOT NULL,
 created_at TEXT NOT NULL, status TEXT NOT NULL
 CHECK(status IN ('active','completed','paused')),
 FOREIGN KEY(learner_id) REFERENCES learners(learner_id),
 FOREIGN KEY(course_id) REFERENCES courses(course_id)
);
CREATE TABLE IF NOT EXISTS recommendations (
 recommendation_id TEXT PRIMARY KEY, learner_id TEXT NOT NULL,
 content_id TEXT NOT NULL, skill_id TEXT NOT NULL, reason_code TEXT NOT NULL,
 explanation TEXT NOT NULL, ranking_score REAL NOT NULL,
 recommendation_time TEXT NOT NULL, outcome_score REAL,
 outcome_recorded_at TEXT,
 FOREIGN KEY(learner_id) REFERENCES learners(learner_id),
 FOREIGN KEY(content_id) REFERENCES content_items(content_id),
 FOREIGN KEY(skill_id) REFERENCES skills(skill_id)
);
-- Append-only outcomes: every subsequent outcome is a new event row.
CREATE TABLE IF NOT EXISTS recommendation_outcomes (
 outcome_id TEXT PRIMARY KEY,
 recommendation_id TEXT NOT NULL,
 outcome_score REAL NOT NULL CHECK(outcome_score >= 0 AND outcome_score <= 100),
 outcome_type TEXT NOT NULL DEFAULT 'ASSESSMENT',
 notes TEXT,
 recorded_at TEXT NOT NULL,
 FOREIGN KEY(recommendation_id) REFERENCES recommendations(recommendation_id)
);

CREATE INDEX IF NOT EXISTS idx_attempt_learner_time ON attempts(learner_id, attempt_time);
CREATE INDEX IF NOT EXISTS idx_attempt_skill ON attempts(skill_id);
CREATE INDEX IF NOT EXISTS idx_recommendation_learner ON recommendations(learner_id);
CREATE INDEX IF NOT EXISTS idx_outcome_recommendation_time
 ON recommendation_outcomes(recommendation_id, recorded_at);
"""

IMPORTS = {
    "courses": "course_id,course_name,status",
    "learners": "learner_id,learner_name,email,created_at,status",
    "skills": "skill_id,course_id,skill_name,description,status",
    "skill_prerequisites": "prerequisite_id,skill_id,prerequisite_skill_id,effective_from,effective_to",
    "content_items": "content_id,content_name,difficulty,content_type,estimated_minutes,status",
    "content_skills": "content_skill_id,content_id,skill_id,weight",
    "attempts": "attempt_id,learner_id,skill_id,score,attempt_time,attempt_number,duration_minutes",
    "assessment_results": "assessment_result_id,attempt_id,score,result_status,graded_at",
    "learning_paths": "path_id,learner_id,course_id,created_at,status",
}


def connect():
    """Open a connection with foreign keys and a generous lock wait."""
    conn = sqlite3.connect(DB_PATH, timeout=BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    return conn


def ensure_extensions():
    """Apply additive migrations to an existing database without deleting data."""
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"{DB_PATH} does not exist. Generate data and initialize the database first."
        )
    conn = connect()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS recommendation_outcomes (
                outcome_id TEXT PRIMARY KEY,
                recommendation_id TEXT NOT NULL,
                outcome_score REAL NOT NULL CHECK(outcome_score >= 0 AND outcome_score <= 100),
                outcome_type TEXT NOT NULL DEFAULT 'ASSESSMENT',
                notes TEXT,
                recorded_at TEXT NOT NULL,
                FOREIGN KEY(recommendation_id) REFERENCES recommendations(recommendation_id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_outcome_recommendation_time
            ON recommendation_outcomes(recommendation_id, recorded_at)
        """)
        conn.commit()
    finally:
        conn.close()


def initialize_database(reset=False):
    """Create schema and load generated CSVs; reset is explicit and destructive."""
    if reset:
        for suffix in ("", "-wal", "-shm"):
            path = Path(str(DB_PATH) + suffix)
            if path.exists():
                path.unlink()

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = connect()
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.executescript(SCHEMA)

        for table, columns in IMPORTS.items():
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if count:
                continue
            path = DATA / f"{table}.csv"
            if not path.exists():
                raise FileNotFoundError(
                    f"Missing {path}. Run python generate_data.py --scale full first."
                )
            col_names = columns.split(",")
            placeholders = ",".join(["?"] * len(col_names))
            sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
            with path.open("r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                batch = []
                for row in reader:
                    batch.append(tuple(row[c] for c in col_names))
                    if len(batch) >= 5000:
                        conn.executemany(sql, batch)
                        batch.clear()
                if batch:
                    conn.executemany(sql, batch)

        conn.commit()
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"Foreign-key violations found: {len(violations)}")
        return {"database": str(DB_PATH), "status": "initialized"}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Initialize the learning SQLite database.")
    parser.add_argument(
        "--reset", action="store_true",
        help="Delete and rebuild the database from generated CSV files (destructive)."
    )
    args = parser.parse_args()
    print(initialize_database(reset=args.reset))
