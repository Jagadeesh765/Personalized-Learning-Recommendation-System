-- Generated schema reference. The executable source of truth is database.py:SCHEMA.
-- Run python database.py --reset only when rebuilding from data/*.csv.

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
