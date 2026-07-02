from sqlalchemy import select

from roleradar.analytics.skill_matcher import (
    extract_and_persist_job_skills,
    find_skill_matches,
)
from roleradar.storage.database import (
    create_database_engine,
    create_session_factory,
    init_database,
)
from roleradar.storage.models import JobSkill
from roleradar.storage.repositories import JobRepository, SkillRepository


def test_skill_matcher_handles_special_terms_and_ambiguous_go(tmp_path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'skills.sqlite3'}")
    init_database(engine=engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        skill_repo = SkillRepository(session)
        for name, alias, case_sensitive in [
            ("Go", "Go", True),
            ("C++", "C++", True),
            ("C#", "C#", True),
            (".NET", ".NET", False),
            ("Node.js", "Node.js", False),
            ("SQL Server", "SQL Server", False),
            ("R", "R", True),
        ]:
            skill = skill_repo.get_or_create_skill(name=name, category="Tech")
            skill_repo.get_or_create_alias(
                skill=skill,
                alias=alias,
                case_sensitive=case_sensitive,
            )
        session.commit()

        ordinary_go_matches = find_skill_matches(
            session,
            "We need someone to go live with the release.",
        )
        technical_matches = find_skill_matches(
            session,
            "Build services with Go, C++, C#, .NET, Node.js, SQL Server, and R.",
        )

    assert "Go" not in {match.skill_name for match in ordinary_go_matches}
    assert {
        "Go",
        "C++",
        "C#",
        ".NET",
        "Node.js",
        "SQL Server",
        "R",
    }.issubset({match.skill_name for match in technical_matches})


def test_extract_and_persist_job_skills_is_idempotent(tmp_path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'extract.sqlite3'}")
    init_database(engine=engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        skill_repo = SkillRepository(session)
        python = skill_repo.get_or_create_skill(name="Python", category="Tech")
        skill_repo.get_or_create_alias(skill=python, alias="Python")

        job_repo = JobRepository(session)
        company = job_repo.get_or_create_company(name="Example")
        job = job_repo.get_or_create_job(
            title="Data Analyst",
            company=company,
            canonical_url="https://example.test/jobs/1",
            description_text="Python role with Python pipelines.",
        )

        first_count = extract_and_persist_job_skills(session, job)
        second_count = extract_and_persist_job_skills(session, job)
        session.commit()

        job_skills = session.scalars(select(JobSkill)).all()

    assert first_count == 1
    assert second_count == 1
    assert len(job_skills) == 1

