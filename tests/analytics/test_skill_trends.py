from roleradar.analytics.skill_matcher import extract_and_persist_job_skills
from roleradar.analytics.skill_trends import top_skills
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

