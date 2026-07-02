from sqlalchemy import select

from roleradar.sources.seed_loader import load_taxonomy_seed
from roleradar.storage.database import (
    create_database_engine,
    create_session_factory,
    init_database,
)
from roleradar.storage.models import Skill, SkillAlias


def test_load_taxonomy_seed_is_idempotent(tmp_path) -> None:
    seed_file = tmp_path / "skills.csv"
    seed_file.write_text(
        "\n".join(
            [
                "skill_name,category,source_taxonomy,alias,match_type,case_sensitive",
                "Python,Programming,local,Python,literal,false",
                "Python,Programming,local,py,literal,false",
                "SQL,Data,local,SQL,literal,false",
            ]
        ),
        encoding="utf-8",
    )
    engine = create_database_engine(f"sqlite:///{tmp_path / 'taxonomy.sqlite3'}")
    init_database(engine=engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        first_result = load_taxonomy_seed(session, seed_file)
        second_result = load_taxonomy_seed(session, seed_file)
        session.commit()

        skills = session.scalars(select(Skill)).all()
        aliases = session.scalars(select(SkillAlias)).all()

    assert first_result.rows_read == 3
    assert second_result.rows_read == 3
    assert len(skills) == 2
    assert len(aliases) == 3

