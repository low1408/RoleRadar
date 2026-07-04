from roleradar.analytics.role_intelligence import (
    canonical_role_family,
    canonical_role_family_by_id,
    custom_role_family_id,
    role_family_detail,
    role_family_summaries,
    top_hiring_companies,
)
from roleradar.storage.database import (
    create_database_engine,
    create_session_factory,
    init_database,
)
from roleradar.storage.repositories import JobRepository, SkillRepository


def test_canonical_role_family_classifies_ai_title() -> None:
    role = canonical_role_family("Senior GenAI / LLM Engineer")

    assert role.id == "ai_ml_engineer"
    assert role.label == "AI / ML Engineer"
    assert role.confidence > 0


def test_canonical_role_family_classifies_robotics_title() -> None:
    role = canonical_role_family("Senior Robotics Software Engineer")

    assert role.id == "robotics"
    assert role.label == "Robotics"
    assert role.confidence > 0


def test_custom_role_family_id_is_canonical_role() -> None:
    family_id = custom_role_family_id("AI Platform")
    role = canonical_role_family_by_id(family_id)

    assert family_id == "custom:ai_platform"
    assert role is not None
    assert role.id == "custom:ai_platform"
    assert role.label == "AI Platform"


def test_role_family_summaries_group_messy_titles(tmp_path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'roles.sqlite3'}")
    init_database(engine=engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        skill_repo = SkillRepository(session)
        python = skill_repo.get_or_create_skill(name="Python")
        pytorch = skill_repo.get_or_create_skill(name="PyTorch")
        sql = skill_repo.get_or_create_skill(name="SQL")

        job_repo = JobRepository(session)
        alpha = job_repo.get_or_create_company(name="Alpha AI")
        beta = job_repo.get_or_create_company(name="Beta Labs")
        gamma = job_repo.get_or_create_company(name="Gamma")
        first_job = job_repo.get_or_create_job(
            title="AI Engineer",
            company=alpha,
            canonical_url="https://example.test/jobs/ai",
        )
        second_job = job_repo.get_or_create_job(
            title="Machine Learning Engineer",
            company=beta,
            canonical_url="https://example.test/jobs/ml",
        )
        data_job = job_repo.get_or_create_job(
            title="Data Analyst",
            company=gamma,
            canonical_url="https://example.test/jobs/data",
        )

        skill_repo.add_job_skill(
            job=first_job,
            skill=python,
            extraction_method="test",
            confidence=1.0,
            matched_text="Python",
        )
        skill_repo.add_job_skill(
            job=first_job,
            skill=pytorch,
            extraction_method="test",
            confidence=1.0,
            matched_text="PyTorch",
        )
        skill_repo.add_job_skill(
            job=second_job,
            skill=python,
            extraction_method="test",
            confidence=1.0,
            matched_text="Python",
        )
        skill_repo.add_job_skill(
            job=data_job,
            skill=sql,
            extraction_method="test",
            confidence=1.0,
            matched_text="SQL",
        )

        job_repo.upsert_source_listing(
            source="careers_gov",
            source_job_id="mcf:ai",
            job=first_job,
            source_title=first_job.title,
            salary_min=7000,
            salary_max=9000,
            salary_currency="SGD",
            salary_interval="monthly",
        )
        job_repo.upsert_source_listing(
            source="jobstreet",
            source_job_id="jobstreet:ml",
            job=second_job,
            source_title=second_job.title,
        )
        job_repo.upsert_source_listing(
            source="careers_gov",
            source_job_id="mcf:data",
            job=data_job,
            source_title=data_job.title,
        )
        session.commit()

        summaries = role_family_summaries(session, days=30, limit=10)
        ai_detail = role_family_detail(
            session,
            family_id="ai_ml_engineer",
            days=30,
        )
        companies = top_hiring_companies(session, days=30, limit=10)

    assert summaries[0].id == "ai_ml_engineer"
    assert summaries[0].job_count == 2
    assert ai_detail is not None
    assert ai_detail.company_count == 2
    assert ai_detail.source_listing_count == 2
    assert ai_detail.average_annualized_salary == 96000
    assert ("Python", 2) in ai_detail.top_skills
    assert ("careers_gov", 1) in ai_detail.top_sources
    assert companies[0].company_name == "Alpha AI"
    assert companies[0].job_count == 1
    assert companies[0].source_listing_count == 1
    assert ("AI / ML Engineer", 1) in companies[0].top_role_families


def test_role_family_summaries_use_custom_selected_family(tmp_path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'custom_roles.sqlite3'}")
    init_database(engine=engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        job_repo = JobRepository(session)
        company = job_repo.get_or_create_company(name="Platform Co")
        job = job_repo.get_or_create_job(
            title="Backend Engineer",
            company=company,
            canonical_url="https://example.test/jobs/backend",
            role_family_id="custom:data_platform",
        )
        job_repo.upsert_source_listing(
            source="careers_gov",
            source_job_id="mcf:backend",
            job=job,
            source_title=job.title,
        )
        session.commit()

        summaries = role_family_summaries(session, days=30, limit=10)
        detail = role_family_detail(
            session,
            family_id="custom:data_platform",
            days=30,
        )

    assert summaries[0].id == "custom:data_platform"
    assert summaries[0].label == "Data Platform"
    assert detail is not None
    assert detail.job_count == 1
