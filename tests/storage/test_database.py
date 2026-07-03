from sqlalchemy import inspect, text

from roleradar.storage.database import (
    create_database_engine,
    create_session_factory,
    init_database,
)


def test_init_database_creates_phase_1_tables(tmp_path) -> None:
    db_path = tmp_path / "roleradar.sqlite3"
    engine = create_database_engine(f"sqlite:///{db_path}")

    init_database(engine=engine)

    table_names = set(inspect(engine).get_table_names())
    assert {
        "ingestion_runs",
        "source_listings",
        "jobs",
        "companies",
        "skills",
        "skill_aliases",
        "job_skills",
        "posting_observations",
        "duplicate_job_candidates",
    }.issubset(table_names)
    source_listing_columns = {
        column["name"] for column in inspect(engine).get_columns("source_listings")
    }
    assert "text_quality" in source_listing_columns


def test_init_database_adds_phase_8_skill_metadata_columns(tmp_path) -> None:
    db_path = tmp_path / "legacy.sqlite3"
    engine = create_database_engine(f"sqlite:///{db_path}")

    with engine.begin() as connection:
        connection.execute(text("""
                CREATE TABLE skills (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    normalized_name VARCHAR(255) NOT NULL,
                    category VARCHAR(255),
                    source_taxonomy VARCHAR(255) NOT NULL,
                    created_at DATETIME NOT NULL
                )
                """))

    init_database(engine=engine)

    columns = {column["name"] for column in inspect(engine).get_columns("skills")}
    assert {"taxonomy_version", "source_updated_at", "updated_at"}.issubset(columns)


def test_init_database_adds_source_listing_text_quality_column(tmp_path) -> None:
    db_path = tmp_path / "legacy-source-listings.sqlite3"
    engine = create_database_engine(f"sqlite:///{db_path}")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE source_listings (
                    id INTEGER PRIMARY KEY,
                    source VARCHAR(64) NOT NULL,
                    source_job_id VARCHAR(255) NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO source_listings (id, source, source_job_id)
                VALUES (1, 'lever', 'job-1')
                """
            )
        )

    init_database(engine=engine)

    columns = {
        column["name"] for column in inspect(engine).get_columns("source_listings")
    }
    with engine.connect() as connection:
        text_quality = connection.execute(
            text("SELECT text_quality FROM source_listings WHERE id = 1")
        ).scalar_one()

    assert "text_quality" in columns
    assert text_quality == "full_text"


def test_file_backed_sqlite_uses_wal_and_busy_timeout(tmp_path) -> None:
    db_path = tmp_path / "roleradar.sqlite3"
    engine = create_database_engine(
        f"sqlite:///{db_path}",
        sqlite_wal=True,
        sqlite_busy_timeout_ms=7500,
    )

    with engine.connect() as connection:
        journal_mode = connection.execute(text("PRAGMA journal_mode")).scalar_one()
        busy_timeout = connection.execute(text("PRAGMA busy_timeout")).scalar_one()

    assert journal_mode == "wal"
    assert busy_timeout == 7500


def test_session_factory_commits_records(tmp_path) -> None:
    from roleradar.storage.models import IngestionRun

    db_path = tmp_path / "roleradar.sqlite3"
    engine = create_database_engine(f"sqlite:///{db_path}")
    init_database(engine=engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        session.add(IngestionRun(source="test-source", status="completed"))
        session.commit()

    with session_factory() as session:
        run = session.query(IngestionRun).one()

    assert run.source == "test-source"
