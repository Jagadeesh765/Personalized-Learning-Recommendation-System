# Personalized Learning Recommendation System

## 1. Overview

An explainable, rule-based learning recommendation application. It recommends the next learning activities using learner assessment history, skill mastery, prerequisite eligibility, and content difficulty. It records recommendations and subsequent outcome events without overwriting history.

**This project uses a transparent rule-based recommender, not a trained machine-learning model.** The supplied problem statement asks for a working recommendation workflow and business rules; it does not explicitly require model training.

## 2. Technology

- Python
- FastAPI + Uvicorn (REST API)
- SQLite (relational persistence, foreign keys, WAL mode)
- Streamlit (dashboard)
- Pytest (automated tests)

The dashboard does not import Pandas or Plotly and does not use `st.dataframe`, `st.bar_chart`, or dataframe-based chart APIs. It uses SQLite query results, `st.write`, `st.json`, `st.metric`, and `st.progress` to avoid the Windows Pandas-DLL issue encountered on some machines. Streamlit may install Pandas as a transitive package dependency, but this project does not call it directly.

## 3. Project structure

```text
personalized-learning-recommendation-system/
  anomaly_checks.py
  dashboard.py
  database.py
  evaluate_recommendations.py
  generate_data.py
  main.py
  recommendation.py
  reproducibility.py
  schema.sql
  validation.py
  requirements.txt
  README.md
  tests/
    conftest.py
    test_project.py
  outputs/
    anomaly_cases.csv
    ground_truth.csv
    data_dictionary.json
    source_manifest.json
    evaluation_metrics.json       # temporal holdout metrics
    reproducibility_report.json   # two-run full-scale checksum comparison
    validation_summary.json       # full database and anomaly validation
    test_summary.txt              # automated test run summary
  data/                           # generated CSV input files (not committed)
  learning.db                     # SQLite database
```

## 4. Windows PowerShell setup

Run commands from the project root.

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

The supplied project archive includes an initialized SQLite database. If `learning.db` is present, you can start the application directly.

If you are building the database from scratch, generate the requested full dataset and then initialize it:

```powershell
python generate_data.py --scale full
python database.py --reset
```

`--reset` is destructive: it rebuilds the database from `data/*.csv`. Do not use it when you want to preserve recommendation or outcome history.

## 5. Start the application

Use two VS Code terminals. `python -m` is used to avoid direct Windows executable-launch restrictions.

**Terminal 1 — API**

```powershell
python -m uvicorn main:app --reload
```

API: http://127.0.0.1:8000  
Swagger docs: http://127.0.0.1:8000/docs

**Terminal 2 — Dashboard**

```powershell
python -m streamlit run dashboard.py
```

Dashboard: http://localhost:8501

Keep both terminals running while using the application.

## 6. Full synthetic dataset

The generator uses fixed seed `20261022` and deterministic IDs. Full scale creates:

| Entity | Rows |
|---|---:|
| Learners | 10,000 |
| Courses | 1 |
| Skills | 500 |
| Skill prerequisites | 166 |
| Content items | 2,000 |
| Content-skill mappings | 2,000 |
| Attempts | 500,000 |
| Assessment results | 500,000 |
| Learning paths | 10,000 |

It includes cold-start learners, repeated attempts, prerequisite gaps, multiple content formats, and chronological attempts per learner. Synthetic data is generated locally; no external personal data is used.

```powershell
python generate_data.py --scale full
```

The generator writes:
- `data/*.csv`
- `outputs/anomaly_cases.csv`
- `outputs/ground_truth.csv`
- `outputs/data_dictionary.json`
- `outputs/source_manifest.json`

The manifest records row counts, file sizes, SHA-256 checksums, seed, scale, and synthetic-data provenance.

## 7. Business rules and recommendation traceability

- Mastery is the arithmetic mean of a learner's attempt scores for a skill.
- `calculate_mastery(learner_id, as_of=...)` excludes attempts after the cutoff.
- A skill is eligible only when every direct prerequisite has mastery of at least 70%.
- Skills at or above 80% mastery are not recommended for ordinary progression.
- Difficulty selection: Easy below 40%; Medium from 40% to below 70%; Hard from 70% to below 80%.
- Each recommendation includes a reason code, explanation, ranking score, skill, content format, and estimated duration. Ranking uses `(100 - mastery) * 0.7 + difficulty_weight * 4`, with difficulty weights Easy=1, Medium=3, Hard=5.
- Recommendation records are immutable history events.
- Each subsequent learning outcome is inserted into `recommendation_outcomes` as a new event. Multiple outcomes for the same recommendation are retained; earlier events are not overwritten.

## 8. Temporal holdout evaluation

The evaluation script performs a chronological split **per learner**:
- First 80% of attempts: training/history window.
- Final 20%: future holdout window.
- Recommendations are generated with `as_of` set to the last training attempt.
- Future holdout attempts are used only to derive relevance labels, never as recommender input.

A held-out skill is labelled relevant when:
1. Its mean future assessment score is below 80.
2. Its mastery at the training cutoff is below 80.
3. All direct prerequisites were mastered to at least 70% using training-period attempts.

Metrics are macro-averaged over the evaluated learner cohort:
- Precision@K = relevant recommended skills in top K divided by K.
- Recall@K = relevant recommended skills in top K divided by all relevant held-out skills for that learner.
- HitRate@K = fraction of evaluated learners with at least one relevant hit in top K.

Run:

```powershell
python evaluate_recommendations.py --k 5 --holdout 0.2 --limit-learners 250
```

The result is saved to `outputs/evaluation_metrics.json`. The default evaluates up to 250 learners with at least five attempts; increase `--limit-learners` for a larger evaluation cohort. The checked-in full-data baseline (250 candidates, 249 evaluated, K=5) is Precision@5=0.0177, Recall@5=0.0175, HitRate@5=0.0843. These scores are low because synthetic attempts assign skills randomly rather than encoding a strong next-skill sequence; treat them as a transparent baseline, not a claim of real-world learning effectiveness.

## 9. Reproducibility verification

This command generates the selected scale twice in isolated temporary folders, then compares row counts and SHA-256 checksums for every generated CSV.

```powershell
python reproducibility.py --scale full
```

The report is saved to `outputs/reproducibility_report.json`. Use `--scale starter` for a quicker check.

## 10. Validation and anomaly cases

The five deliberate anomaly scenarios are kept in `outputs/anomaly_cases.csv` and `outputs/ground_truth.csv`; they are not inserted into normal baseline input tables.

The validation workflow checks:
- Primary-key uniqueness and foreign-key integrity.
- Score range and assessment-result reconciliation.
- Missing assessment results and per-learner timestamp ordering.
- Append-only outcome score ranges.
- Ground-truth label consistency and anomaly-record separation.
- The five executable negative scenarios: prerequisite violation, invalid timestamp, invalid skill reference, future-data leakage, and no-progress loop.

API validation: `GET /validation`.

## 11. API endpoints

- `GET /`
- `GET /learners`
- `GET /learners/{learner_id}/mastery`
- `GET /learners/{learner_id}/recommendations`
- `POST /attempts`
- `POST /outcomes` — appends a new outcome event
- `GET /recommendations/{recommendation_id}/outcomes`
- `GET /metrics`
- `GET /validation`
- `GET /recommendation-history/{learner_id}`

Example outcome payload:

```json
{
  "recommendation_id": "PASTE_A_REAL_RECOMMENDATION_ID",
  "outcome_score": 82,
  "outcome_type": "ASSESSMENT",
  "notes": "Completed the recommended activity"
}
```

Use a real `recommendation_id` returned by the recommendation endpoint or dashboard history.

## 12. Tests

```powershell
python -m pytest -v
```

The tests cover time cutoffs, recommendation reason codes, append-only outcome history, temporal evaluation, deterministic generation, ground-truth separation, database integrity, and all five anomaly scenarios.

## 13. Windows / Pandas and SQLite troubleshooting

- Start Streamlit with `python -m streamlit run dashboard.py`, not `streamlit run dashboard.py`.
- Install packages with `python -m pip install -r requirements.txt`.
- The dashboard uses SQLite and basic Streamlit widgets; it does not import Pandas or call dataframe/chart components.
- SQLite connections use a 30-second busy timeout. Database initialization enables WAL mode and normal synchronous mode.
- Do not run `database.py --reset` while the API or dashboard is running.
- If a Windows Application Control policy blocks a compiled package DLL, do not disable or bypass the policy. The application avoids direct Pandas use, but a machine-level policy may still restrict transitive packages.

## 14. Limitations

- Recommendation ranking is deterministic and rule-based; no model is trained.
- The offline evaluation uses synthetic future assessment outcomes as relevance labels. It demonstrates measurable evaluation logic, not proven improvement in real learner outcomes.
- External data is not used. All generated records are synthetic and use a fixed seed.
