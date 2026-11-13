import pytest

import database
import generate_data
import validation
import evaluate_recommendations


@pytest.fixture
def sample_project(tmp_path, monkeypatch):
    generate_data.generate("starter", output_dir=tmp_path)
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "learning.db")
    monkeypatch.setattr(database, "DATA", tmp_path / "data")
    monkeypatch.setattr(validation, "BASE", tmp_path)
    monkeypatch.setattr(evaluate_recommendations, "BASE", tmp_path)
    database.initialize_database(reset=True)
    database.ensure_extensions()
    return tmp_path
