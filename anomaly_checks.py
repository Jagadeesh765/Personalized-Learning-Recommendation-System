"""Executable validators for the five required negative scenarios."""

def check_prerequisite_eligibility(prerequisite_mastery, threshold=70):
    """Return (accepted, reason); every prerequisite must meet threshold."""
    failed = [skill for skill, score in prerequisite_mastery.items() if score < threshold]
    if failed:
        return False, f"PREREQUISITE_NOT_MET:{','.join(failed)}"
    return True, "PREREQUISITES_SATISFIED"


def check_attempt_timestamps(start_time, end_time):
    if end_time < start_time:
        return False, "INVALID_TIMESTAMP"
    return True, "VALID_TIMESTAMP"


def check_content_skill_reference(skill_id, known_skill_ids):
    if skill_id not in set(known_skill_ids):
        return False, "INVALID_SKILL_REFERENCE"
    return True, "VALID_SKILL_REFERENCE"


def check_no_future_attempts(attempt_times, as_of):
    future = [stamp for stamp in attempt_times if stamp > as_of]
    if future:
        return False, "FUTURE_DATA_LEAKAGE"
    return True, "TEMPORAL_CUTOFF_VALID"


def check_learning_path_progress(events):
    """Flag a repeated activity when no progress event separates repetitions."""
    seen_since_progress = set()
    for event in events:
        if event.get("event_type") == "progress":
            seen_since_progress.clear()
            continue
        activity = event.get("activity_id")
        if activity in seen_since_progress:
            return False, "NO_PROGRESS_LOOP"
        seen_since_progress.add(activity)
    return True, "PATH_PROGRESS_VALID"
