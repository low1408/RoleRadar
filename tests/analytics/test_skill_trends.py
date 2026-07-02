from roleradar.analytics.skill_matcher import extract_and_persist_job_skills
from roleradar.analytics.skill_trends import (
    skills_by_company,
    skills_by_role_keyword,
    skills_by_source,
    top_skills,
)
from roleradar.storage.database import (
    create_database_engine,
    create_session_factory,
    init_database,
)
from roleradar.storage.repositories import JobRepository, SkillRepository


def test_top_skills_counts_active_jobs(tmp_path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'trends.sqlite3'}")
    init_database(engine=engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        skill_repo = SkillRepository(session)
        python = skill_repo.get_or_create_skill(name="Python")
        sql = skill_repo.get_or_create_skill(name="SQL")
        skill_repo.get_or_create_alias(skill=python, alias="Python")
        skill_repo.get_or_create_alias(skill=sql, alias="SQL")

        job_repo = JobRepository(session)
        company = job_repo.get_or_create_company(name="Example")
        first_job = job_repo.get_or_create_job(
            title="Data Analyst",
            company=company,
            canonical_url="https://example.test/jobs/1",
            description_text="Python and SQL",
        )
        second_job = job_repo.get_or_create_job(
            title="Analytics Engineer",
            company=company,
            canonical_url="https://example.test/jobs/2",
            description_text="SQL pipelines",
        )
        extract_and_persist_job_skills(session, first_job)
        extract_and_persist_job_skills(session, second_job)
        session.commit()

        rows = top_skills(session, limit=10)

    assert rows[0].skill_name == "SQL"
    assert rows[0].job_count == 2
    assert rows[1].skill_name == "Python"
    assert rows[1].job_count == 1


def test_skill_report_dimensions_use_active_recent_postings(tmp_path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'dimensions.sqlite3'}")
    init_database(engine=engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        skill_repo = SkillRepository(session)
        python = skill_repo.get_or_create_skill(name="Python")
        sql = skill_repo.get_or_create_skill(name="SQL")
        skill_repo.get_or_create_alias(skill=python, alias="Python")
        skill_repo.get_or_create_alias(skill=sql, alias="SQL")

        job_repo = JobRepository(session)
        alpha = job_repo.get_or_create_company(name="Alpha")
        beta = job_repo.get_or_create_company(name="Beta")
        data_job = job_repo.get_or_create_job(
            title="Data Analyst",
            company=alpha,
            canonical_url="https://example.test/jobs/data",
            description_text="Python and SQL",
        )
        software_job = job_repo.get_or_create_job(
            title="Software Engineer",
            company=beta,
            canonical_url="https://example.test/jobs/software",
            description_text="Python",
        )
        job_repo.upsert_source_listing(
            source="lever",
            source_job_id="lever:data",
            job=data_job,
            source_title=data_job.title,
        )
        job_repo.upsert_source_listing(
            source="greenhouse",
            source_job_id="greenhouse:software",
            job=software_job,
            source_title=software_job.title,
        )
        extract_and_persist_job_skills(session, data_job)
        extract_and_persist_job_skills(session, software_job)
        session.commit()

        source_rows = skills_by_source(session, days=30, limit=10)
        company_rows = skills_by_company(session, days=30, limit=10)
        role_rows = skills_by_role_keyword(
            session,
            days=30,
            role_keywords=("data", "software"),
            limit_per_keyword=10,
        )

    assert ("lever", "Python", 1) in [
        (row.source, row.skill_name, row.posting_count) for row in source_rows
    ]
    assert ("Alpha", "SQL", 1) in [
        (row.company_name, row.skill_name, row.job_count) for row in company_rows
    ]
    assert ("software", "Python", 1) in [
        (row.role_keyword, row.skill_name, row.job_count) for row in role_rows
    ]
