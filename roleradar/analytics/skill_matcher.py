"""Deterministic skill extraction from job text."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from roleradar.storage.models import Job, Skill, SkillAlias
from roleradar.storage.repositories import SkillRepository


@dataclass(frozen=True)
class SkillMatch:
    """One skill match found in text."""

    skill_id: int
    skill_name: str
    matched_text: str
    extraction_method: str
    confidence: float


AMBIGUOUS_GO_NEXT_WORDS = {"live", "to", "faster", "forward", "back", "ahead"}


def find_skill_matches(session: Session, text: str) -> list[SkillMatch]:
    """Find deterministic skill matches using configured aliases."""
    aliases = session.scalars(
        select(SkillAlias).join(SkillAlias.skill).order_by(SkillAlias.id)
    ).all()
    matches: dict[int, SkillMatch] = {}

    for alias in aliases:
        matched_text = _find_alias(alias, text)
        if matched_text is None:
            continue

        matches.setdefault(
            alias.skill_id,
            SkillMatch(
                skill_id=alias.skill_id,
                skill_name=alias.skill.name,
                matched_text=matched_text,
                extraction_method=f"alias:{alias.match_type}",
                confidence=1.0,
            ),
        )

    return list(matches.values())


def persist_job_skill_matches(session: Session, job: Job, matches: list[SkillMatch]) -> int:
    """Persist extracted skill matches for a job."""
    repository = SkillRepository(session)
    for match in matches:
        skill = session.get(Skill, match.skill_id)
        if skill is None:
            continue
        repository.add_job_skill(
            job=job,
            skill=skill,
            extraction_method=match.extraction_method,
            confidence=match.confidence,
            matched_text=match.matched_text,
        )
    return len(matches)


def extract_and_persist_job_skills(session: Session, job: Job) -> int:
    """Extract and persist skill matches for a job."""
    if not job.description_text:
        return 0

    return persist_job_skill_matches(
        session,
        job,
        find_skill_matches(session, job.description_text),
    )


def _find_alias(alias: SkillAlias, text: str) -> str | None:
    flags = 0 if alias.case_sensitive else re.IGNORECASE
    pattern = re.compile(_alias_pattern(alias.alias), flags)

    for match in pattern.finditer(text):
        matched_text = match.group(0)
        if alias.normalized_alias == "go" and _is_ordinary_go_usage(text, match):
            continue
        return matched_text

    return None


def _alias_pattern(alias: str) -> str:
    escaped = re.escape(alias.strip())
    return rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])"


def _is_ordinary_go_usage(text: str, match: re.Match[str]) -> bool:
    after = text[match.end() :]
    next_word_match = re.search(r"[A-Za-z]+", after)
    if next_word_match and next_word_match.group(0).casefold() in AMBIGUOUS_GO_NEXT_WORDS:
        return True
    return False
