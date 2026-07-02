import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from roleradar.sources.ssg_wsg import (
    SsgWsgTaxonomyClient,
    SsgWsgTaxonomyRecord,
    parse_taxonomy_response,
    sync_taxonomy_from_ssg_wsg,
)
from roleradar.storage.database import (
    create_database_engine,
    create_session_factory,
    init_database,
)
from roleradar.storage.models import Skill, SkillAlias
from roleradar.storage.repositories import SkillRepository


def test_parse_taxonomy_response_contract_fixture() -> None:
    payload = json.loads(
        Path("tests/fixtures/ssg_wsg_taxonomy_response.json").read_text(
            encoding="utf-8"
        )
    )

    records = parse_taxonomy_response(payload)

    assert [record.skill_name for record in records] == ["Python", "SQL"]
    assert records[0].aliases == ("Python", "py")
    assert records[0].category == "Programming"
    assert records[0].taxonomy_version == "2026.01"
    assert records[0].source_updated_at == datetime(2026, 1, 20, 8, tzinfo=UTC)
    assert records[1].aliases == ("SQL", "Structured Query Language")
    assert records[1].source_updated_at == datetime(2026, 1, 15, 8, tzinfo=UTC)


def test_sync_taxonomy_skips_when_credentials_missing(tmp_path) -> None:
    session_factory = _session_factory(tmp_path)

    with session_factory() as session:
        result = sync_taxonomy_from_ssg_wsg(
            session,
            client_id=None,
            client_secret=None,
        )

    assert result.status == "skipped"
    assert "ROLERADAR_SSG_WSG_CLIENT_ID" in (result.message or "")
    assert "seed-taxonomy" in (result.message or "")


def test_sync_taxonomy_upserts_without_replacing_local_aliases(tmp_path) -> None:
    session_factory = _session_factory(tmp_path)
    client = StubTaxonomyClient(
        [
            SsgWsgTaxonomyRecord(
                skill_name="Python",
                category="Programming",
                aliases=("Python", "py"),
                taxonomy_version="2026.01",
                source_updated_at=datetime(2026, 1, 20, 8, tzinfo=UTC),
            )
        ]
    )

    with session_factory() as session:
        repository = SkillRepository(session)
        local_python = repository.get_or_create_skill(
            name="Python",
            category="Programming",
            source_taxonomy="local",
        )
        repository.get_or_create_alias(skill=local_python, alias="local py")

        first_result = sync_taxonomy_from_ssg_wsg(
            session,
            client_id="client-id",
            client_secret="client-secret",
            client=client,
        )
        second_result = sync_taxonomy_from_ssg_wsg(
            session,
            client_id="client-id",
            client_secret="client-secret",
            client=client,
        )
        session.commit()

        skills = session.scalars(select(Skill)).all()
        aliases = session.scalars(select(SkillAlias)).all()
        ssg_python = session.scalar(
            select(Skill).where(
                Skill.normalized_name == "python",
                Skill.source_taxonomy == "ssg-wsg",
            )
        )

    assert first_result.status == "completed"
    assert first_result.skills_seen == 1
    assert first_result.aliases_seen == 2
    assert second_result.skills_seen == 1
    assert len(skills) == 2
    assert len(aliases) == 3
    assert ssg_python is not None
    assert ssg_python.taxonomy_version == "2026.01"
    assert ssg_python.source_updated_at == datetime(2026, 1, 20, 8)


def test_client_fetches_taxonomy_with_credentials() -> None:
    http_session = StubHttpSession(
        {
            "items": [
                {
                    "name": "Data Analysis",
                    "category": "Data",
                    "aliases": ["Data Analysis"],
                }
            ]
        }
    )
    client = SsgWsgTaxonomyClient(
        client_id="client-id",
        client_secret="client-secret",
        taxonomy_url="https://example.test/taxonomy",
        session=http_session,
        timeout_seconds=3.0,
    )

    records = client.fetch_taxonomy()

    assert records[0].skill_name == "Data Analysis"
    assert http_session.request["url"] == "https://example.test/taxonomy"
    assert http_session.request["headers"]["X-IBM-Client-Id"] == "client-id"
    assert http_session.request["headers"]["X-IBM-Client-Secret"] == "client-secret"
    assert http_session.request["timeout"] == 3.0


class StubTaxonomyClient:
    def __init__(self, records: list[SsgWsgTaxonomyRecord]) -> None:
        self.records = records

    def fetch_taxonomy(self) -> list[SsgWsgTaxonomyRecord]:
        return self.records


class StubHttpSession:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.request: dict = {}

    def get(self, url: str, *, headers: dict, timeout: float) -> "StubResponse":
        self.request = {"url": url, "headers": headers, "timeout": timeout}
        return StubResponse(self.payload)


class StubResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


def _session_factory(tmp_path):
    engine = create_database_engine(f"sqlite:///{tmp_path / 'taxonomy.sqlite3'}")
    init_database(engine=engine)
    return create_session_factory(engine)
