import pytest

from roleradar.ingestion.fetch_jobs import ingest_jobs
from roleradar.sources.jobstreet import (
    JobStreetAccessBlockedError,
    jobstreet_blocked_message,
    require_jobstreet_access_approval,
)


def test_jobstreet_policy_message_names_required_access_and_forbidden_methods() -> None:
    message = jobstreet_blocked_message()

    assert "written SEEK/JobStreet permission" in message
    assert "documented API/licensed data access" in message
    assert "docs/jobstreet_access_requirements.md" in message
    assert "HTML scraping" in message
    assert "private GraphQL" in message


def test_jobstreet_access_gate_fails_closed() -> None:
    with pytest.raises(JobStreetAccessBlockedError):
        require_jobstreet_access_approval()


def test_jobstreet_ingestion_fails_before_database_or_network_setup(tmp_path) -> None:
    db_url = f"sqlite:///{tmp_path / 'jobstreet.sqlite3'}"

    with pytest.raises(JobStreetAccessBlockedError):
        ingest_jobs(database_url=db_url, source="jobstreet")
