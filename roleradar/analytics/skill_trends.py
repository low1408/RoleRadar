"""Current-snapshot skill reporting queries."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from roleradar.storage.models import Job, JobSkill, Skill


@dataclass(frozen=True)
class SkillCount:
    """Count of active jobs requiring one skill."""

    skill_name: str
    job_count: int


def top_skills(session: Session, *, limit: int = 10) -> list[SkillCount]:
    """Return top skills by active canonical job count."""
    rows = session.execute(
        select(Skill.name, func.count(func.distinct(JobSkill.job_id)).label("job_count"))
        .join(JobSkill, JobSkill.skill_id == Skill.id)
        .join(Job, Job.id == JobSkill.job_id)
        .where(Job.closed_at.is_(None))
        .group_by(Skill.id)
        .order_by(desc("job_count"), Skill.name)
        .limit(limit)
    ).all()

    return [SkillCount(skill_name=row[0], job_count=row[1]) for row in rows]

