"""Deterministic synthetic-data generator for the learning recommendation demo."""
import argparse
import csv
import json
import random
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

SEED = 20261022
BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
OUTPUTS = BASE / "outputs"

SKILL_NAMES = [
    "Python Basics", "Variables", "Data Types", "Operators", "Conditions",
    "Loops", "Functions", "Lists", "Tuples", "Dictionaries", "Sets",
    "Strings", "File Handling", "Exceptions", "Modules", "OOP",
    "Inheritance", "Polymorphism", "Libraries", "Mini Projects"
]
FORMATS = ["Video", "Quiz", "Exercise", "Article"]
DIFFICULTIES = ["Easy", "Medium", "Hard"]


def write_csv(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def generate(scale="starter", output_dir=None):
    """Generate deterministic CSVs and documentation under output_dir or project root."""
    rng = random.Random(SEED)
    root = Path(output_dir).resolve() if output_dir else BASE
    data_dir = root / "data"
    outputs_dir = root / "outputs"
    if scale == "full":
        n_learners, n_skills, n_content, n_attempts = 10_000, 500, 2_000, 500_000
    else:
        n_learners, n_skills, n_content, n_attempts = 100, 20, 50, 1_000

    data_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    courses = [{"course_id": "CRS-000001", "course_name": "Python Programming",
                "status": "active"}]

    skills = []
    for i in range(1, n_skills + 1):
        name = SKILL_NAMES[i - 1] if i <= len(SKILL_NAMES) else f"Programming Skill {i}"
        skills.append({"skill_id": f"SKL-{i:06d}", "course_id": "CRS-000001",
                       "skill_name": name, "description": f"Learning objective: {name}",
                       "status": "active"})

    learners = []
    for i in range(1, n_learners + 1):
        learners.append({"learner_id": f"LRN-{i:06d}",
                         "learner_name": f"Learner {i:06d}",
                         "email": f"learner{i:06d}@example.test",
                         "created_at": "2026-01-01T00:00:00",
                         "status": "active"})

    # A directed acyclic prerequisite graph: each third skill depends on its predecessor.
    prereqs = []
    for i in range(3, n_skills + 1, 3):
        prereqs.append({"prerequisite_id": f"PRQ-{len(prereqs)+1:06d}",
                        "skill_id": f"SKL-{i:06d}",
                        "prerequisite_skill_id": f"SKL-{i-1:06d}",
                        "effective_from": "2026-01-01",
                        "effective_to": ""})

    content = []
    content_skills = []
    for i in range(1, n_content + 1):
        skill_num = ((i - 1) % n_skills) + 1
        content.append({"content_id": f"CNT-{i:06d}",
                        "content_name": f"{skills[skill_num-1]['skill_name']} Activity {i}",
                        "difficulty": DIFFICULTIES[(i - 1) % 3],
                        "content_type": FORMATS[(i - 1) % len(FORMATS)],
                        "estimated_minutes": 10 + (i % 5) * 5,
                        "status": "active"})
        content_skills.append({"content_skill_id": f"CSM-{i:06d}",
                               "content_id": f"CNT-{i:06d}",
                               "skill_id": f"SKL-{skill_num:06d}",
                               "weight": 1.0})

    # Ten deliberately cold-start learners; remaining attempts are chronologically ordered
    # within each learner. Scores are generated from a learner/skill tendency plus noise.
    attempts = []
    counts = {}
    learner_ability = {f"LRN-{i:06d}": rng.uniform(0.42, 0.86)
                       for i in range(1, n_learners + 1)}
    eligible_learners = list(range(11, n_learners + 1)) if n_learners > 10 else []
    if not eligible_learners:
        eligible_learners = [1]

    for j in range(n_attempts):
        learner_num = rng.choice(eligible_learners)
        learner_id = f"LRN-{learner_num:06d}"
        skill_num = rng.randint(1, n_skills)
        skill_id = f"SKL-{skill_num:06d}"
        counts[learner_id] = counts.get(learner_id, 0) + 1
        ability = learner_ability[learner_id]
        score = round(max(0, min(100, (ability + rng.uniform(-0.28, 0.28)) * 100)), 2)
        # A monotonically increasing event time per learner avoids accidental time inversions.
        day_offset = counts[learner_id] - 1
        event_time = datetime(2026, 1, 1) + timedelta(days=day_offset,
                                                       minutes=rng.randint(0, 600))
        attempts.append({"attempt_id": f"ATT-{learner_id}-{counts[learner_id]:06d}",
                         "learner_id": learner_id, "skill_id": skill_id,
                         "score": score, "attempt_time": event_time.isoformat(),
                         "attempt_number": counts[learner_id],
                         "duration_minutes": rng.randint(3, 45)})

    assessment_results = []
    for i, a in enumerate(attempts, 1):
        assessment_results.append({"assessment_result_id": f"RES-{i:07d}",
                                    "attempt_id": a["attempt_id"],
                                    "score": a["score"],
                                    "result_status": "Passed" if a["score"] >= 70 else "Needs Improvement",
                                    "graded_at": a["attempt_time"]})

    learning_paths = [{"path_id": f"PATH-2026-{i:06d}",
                       "learner_id": learner["learner_id"],
                       "course_id": "CRS-000001", "created_at": "2026-01-01T00:00:00",
                       "status": "active"} for i, learner in enumerate(learners, 1)]

    tables = {
        "learners": learners, "courses": courses, "skills": skills,
        "skill_prerequisites": prereqs, "content_items": content,
        "content_skills": content_skills, "attempts": attempts,
        "assessment_results": assessment_results, "learning_paths": learning_paths
    }
    for name, rows in tables.items():
        write_csv(data_dir / f"{name}.csv", rows)

    # Separate anomaly fixtures and ground truth; these are never loaded as model features.
    anomaly_cases = [
        {"case_id": "ANOM-001", "issue_type": "PREREQUISITE_VIOLATION",
         "record_id": "REC-ANOM-001", "expected_result": "REJECT",
         "description": "Proposed advanced content while prerequisite mastery is below threshold."},
        {"case_id": "ANOM-002", "issue_type": "INVALID_TIMESTAMP",
         "record_id": "ATT-ANOM-002", "expected_result": "FLAG",
         "description": "Attempt end timestamp occurs before start timestamp."},
        {"case_id": "ANOM-003", "issue_type": "INVALID_SKILL_REFERENCE",
         "record_id": "CNT-ANOM-003", "expected_result": "FLAG",
         "description": "Content-to-skill mapping points to a missing skill ID."},
        {"case_id": "ANOM-004", "issue_type": "FUTURE_DATA_LEAKAGE",
         "record_id": "MASTERY-ANOM-004", "expected_result": "REJECT",
         "description": "Mastery calculation includes an attempt later than its as-of time."},
        {"case_id": "ANOM-005", "issue_type": "NO_PROGRESS_LOOP",
         "record_id": "PATH-ANOM-005", "expected_result": "FLAG",
         "description": "Learning path repeats the same activity without a progress event."}
    ]
    write_csv(outputs_dir / "anomaly_cases.csv", anomaly_cases)
    write_csv(outputs_dir / "ground_truth.csv", anomaly_cases)

    # Field-level data dictionary: type, requiredness, domain/units, uniqueness and validation.
    dictionary = {
        "Learner": {
            "learner_id": {"type": "string", "required": True, "unique": True, "rule": "PK; LRN-000001 format"},
            "learner_name": {"type": "string", "required": True, "unique": False, "rule": "Non-empty display name"},
            "email": {"type": "string", "required": True, "unique": True, "rule": "Synthetic example.test email"},
            "created_at": {"type": "ISO-8601 datetime", "required": True, "unique": False, "rule": "Valid datetime"},
            "status": {"type": "enum", "required": True, "allowed": ["active", "inactive"], "rule": "Lifecycle state"}
        },
        "Course": {
            "course_id": {"type": "string", "required": True, "unique": True, "rule": "PK; CRS-000001 format"},
            "course_name": {"type": "string", "required": True, "unique": False, "rule": "Non-empty name"},
            "status": {"type": "enum", "required": True, "allowed": ["active", "inactive"], "rule": "Lifecycle state"}
        },
        "Skill": {
            "skill_id": {"type": "string", "required": True, "unique": True, "rule": "PK; SKL-000001 format"},
            "course_id": {"type": "string", "required": True, "unique": False, "rule": "FK to Course.course_id"},
            "skill_name": {"type": "string", "required": True, "unique": False, "rule": "Non-empty skill name"},
            "description": {"type": "string", "required": False, "unique": False, "rule": "Optional description"},
            "status": {"type": "enum", "required": True, "allowed": ["active", "inactive"], "rule": "Lifecycle state"}
        },
        "SkillPrerequisite": {
            "prerequisite_id": {"type": "string", "required": True, "unique": True, "rule": "PK; PRQ-000001 format"},
            "skill_id": {"type": "string", "required": True, "unique": False, "rule": "FK to Skill.skill_id"},
            "prerequisite_skill_id": {"type": "string", "required": True, "unique": False, "rule": "FK to Skill.skill_id; cannot equal skill_id"},
            "effective_from": {"type": "date", "required": True, "unique": False, "rule": "ISO date"},
            "effective_to": {"type": "date", "required": False, "unique": False, "rule": "Null/blank means open-ended; must not precede effective_from"}
        },
        "ContentItem": {
            "content_id": {"type": "string", "required": True, "unique": True, "rule": "PK; CNT-000001 format"},
            "content_name": {"type": "string", "required": True, "unique": False, "rule": "Non-empty name"},
            "difficulty": {"type": "enum", "required": True, "allowed": ["Easy", "Medium", "Hard"], "rule": "Controlled vocabulary"},
            "content_type": {"type": "enum", "required": True, "allowed": FORMATS, "rule": "Controlled vocabulary"},
            "estimated_minutes": {"type": "integer", "required": True, "unique": False, "units": "minutes", "rule": "Positive integer"},
            "status": {"type": "enum", "required": True, "allowed": ["active", "inactive"], "rule": "Lifecycle state"}
        },
        "ContentSkill": {
            "content_skill_id": {"type": "string", "required": True, "unique": True, "rule": "PK; CSM-000001 format"},
            "content_id": {"type": "string", "required": True, "unique": False, "rule": "FK to ContentItem.content_id"},
            "skill_id": {"type": "string", "required": True, "unique": False, "rule": "FK to Skill.skill_id"},
            "weight": {"type": "number", "required": True, "unique": False, "units": "0..1", "rule": "Inclusive range 0 to 1"}
        },
        "Attempt": {
            "attempt_id": {"type": "string", "required": True, "unique": True, "rule": "PK; ATT-<learner-id>-000001 format"},
            "learner_id": {"type": "string", "required": True, "unique": False, "rule": "FK to Learner.learner_id"},
            "skill_id": {"type": "string", "required": True, "unique": False, "rule": "FK to Skill.skill_id"},
            "score": {"type": "number", "required": True, "unique": False, "units": "percentage points", "rule": "Inclusive range 0 to 100"},
            "attempt_time": {"type": "ISO-8601 datetime", "required": True, "unique": False, "rule": "Chronological per learner"},
            "attempt_number": {"type": "integer", "required": True, "unique": False, "rule": "Positive and unique per learner"},
            "duration_minutes": {"type": "integer", "required": True, "unique": False, "units": "minutes", "rule": "Positive integer"}
        },
        "AssessmentResult": {
            "assessment_result_id": {"type": "string", "required": True, "unique": True, "rule": "PK; RES-0000001 format"},
            "attempt_id": {"type": "string", "required": True, "unique": True, "rule": "FK to Attempt.attempt_id; one result per attempt"},
            "score": {"type": "number", "required": True, "unique": False, "units": "percentage points", "rule": "Copied from source attempt"},
            "result_status": {"type": "enum", "required": True, "allowed": ["Passed", "Needs Improvement"], "rule": "Derived: Passed at score >= 70"},
            "graded_at": {"type": "ISO-8601 datetime", "required": True, "unique": False, "rule": "Must not precede attempt"}
        },
        "LearningPath": {
            "path_id": {"type": "string", "required": True, "unique": True, "rule": "PK; PATH-2026-000001 format"},
            "learner_id": {"type": "string", "required": True, "unique": False, "rule": "FK to Learner.learner_id"},
            "course_id": {"type": "string", "required": True, "unique": False, "rule": "FK to Course.course_id"},
            "created_at": {"type": "ISO-8601 datetime", "required": True, "unique": False, "rule": "Valid datetime"},
            "status": {"type": "enum", "required": True, "allowed": ["active", "completed", "paused"], "rule": "Lifecycle state"}
        },
        "Recommendation": {
            "recommendation_id": {"type": "string", "required": True, "unique": True, "rule": "PK; generated immutable ID"},
            "learner_id": {"type": "string", "required": True, "unique": False, "rule": "FK to Learner.learner_id"},
            "content_id": {"type": "string", "required": True, "unique": False, "rule": "FK to ContentItem.content_id"},
            "skill_id": {"type": "string", "required": True, "unique": False, "rule": "FK to Skill.skill_id"},
            "reason_code": {"type": "enum", "required": True, "allowed": ["COLD_START", "LOW_MASTERY", "DEVELOPING_SKILL", "SKILL_IMPROVEMENT"], "rule": "Decision traceability"},
            "explanation": {"type": "string", "required": True, "unique": False, "rule": "Human-readable rationale"},
            "ranking_score": {"type": "number", "required": True, "unique": False, "rule": "Derived ranking score"},
            "recommendation_time": {"type": "ISO-8601 datetime", "required": True, "unique": False, "rule": "Event timestamp"},
            "outcome_score": {"type": "number", "required": False, "unique": False, "rule": "Legacy compatibility column; append-only outcomes table is authoritative"},
            "outcome_recorded_at": {"type": "ISO-8601 datetime", "required": False, "unique": False, "rule": "Legacy compatibility column; not updated by the application"}
        },
        "RecommendationOutcome": {
            "outcome_id": {"type": "string", "required": True, "unique": True, "rule": "PK; generated immutable event ID"},
            "recommendation_id": {"type": "string", "required": True, "unique": False, "rule": "FK to Recommendation.recommendation_id"},
            "outcome_score": {"type": "number", "required": True, "unique": False, "units": "percentage points", "rule": "Inclusive range 0 to 100"},
            "outcome_type": {"type": "enum", "required": True, "allowed": ["ASSESSMENT", "COMPLETION", "FEEDBACK"], "rule": "Outcome event category"},
            "notes": {"type": "string", "required": False, "unique": False, "rule": "Optional note up to 500 characters"},
            "recorded_at": {"type": "ISO-8601 datetime", "required": True, "unique": False, "rule": "Append-only event timestamp"}
        },
        "relationships": [
            {"parent": "Course", "child": "Skill", "cardinality": "1:N", "optional": False, "rule": "Each skill belongs to one course."},
            {"parent": "Skill", "child": "SkillPrerequisite", "cardinality": "1:N (dependent and prerequisite roles)", "optional": True, "rule": "Self-referencing skill edges; effective_from required, effective_to optional."},
            {"parent": "ContentItem", "child": "ContentSkill", "cardinality": "1:N", "optional": False, "rule": "Bridge-table side of ContentItem N:M Skill."},
            {"parent": "Skill", "child": "ContentSkill", "cardinality": "1:N", "optional": False, "rule": "Bridge-table side of Skill N:M ContentItem."},
            {"parent": "Learner", "child": "Attempt", "cardinality": "1:N", "optional": True, "rule": "Cold-start learners may have zero attempts."},
            {"parent": "Skill", "child": "Attempt", "cardinality": "1:N", "optional": False, "rule": "Every attempt assesses one skill."},
            {"parent": "Attempt", "child": "AssessmentResult", "cardinality": "1:1", "optional": False, "rule": "One derived result per baseline attempt."},
            {"parent": "Learner", "child": "LearningPath", "cardinality": "1:N", "optional": True, "rule": "A learner may have zero or more paths."},
            {"parent": "Course", "child": "LearningPath", "cardinality": "1:N", "optional": False, "rule": "Each learning path belongs to one course."},
            {"parent": "Learner", "child": "Recommendation", "cardinality": "1:N", "optional": True, "rule": "A learner may have zero or more recommendation events."},
            {"parent": "Recommendation", "child": "RecommendationOutcome", "cardinality": "1:N", "optional": True, "rule": "Zero or more append-only outcome events per recommendation."},
            {"parent": "ContentItem", "child": "Recommendation", "cardinality": "1:N", "optional": False, "rule": "Each recommendation selects one content item."},
            {"parent": "Skill", "child": "Recommendation", "cardinality": "1:N", "optional": False, "rule": "Each recommendation targets one skill."}
        ]
    }
    (outputs_dir / "data_dictionary.json").write_text(
        json.dumps(dictionary, indent=2), encoding="utf-8"
    )

    def file_sha256(path):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    file_manifest = {}
    for table_name, rows in tables.items():
        csv_path = data_dir / f"{table_name}.csv"
        file_manifest[csv_path.name] = {
            "rows": len(rows),
            "bytes": csv_path.stat().st_size,
            "sha256": file_sha256(csv_path)
        }

    manifest = {
        "seed": SEED,
        "scale": scale,
        "row_counts": {k: len(v) for k, v in tables.items()},
        "files": file_manifest,
        "provenance": "Fully synthetic data generated locally; no personal or external data.",
        "determinism": "Python random.Random with fixed seed; stable entity ordering and IDs."
    }
    (outputs_dir / "source_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    print(f"Generated {scale} dataset with seed {SEED}")
    for name, rows in tables.items():
        print(f"{name}: {len(rows):,}")
    print("Ground truth, anomaly cases, data dictionary and manifest written to outputs/.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scale", choices=["starter", "full"], default="starter")
    parser.add_argument("--output-dir", default=None,
                        help="Optional directory for isolated generation/reproducibility checks.")
    args = parser.parse_args()
    generate(args.scale, output_dir=args.output_dir)
