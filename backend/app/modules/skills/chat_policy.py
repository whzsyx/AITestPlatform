"""Chat-side skill visibility policy.

Some system skills keep their backend/tool implementations for non-chat flows
but must not be exposed to the AI chat router.
"""

from __future__ import annotations

from typing import Iterable, TypeVar

from app.modules.skills.models import Skill

CHAT_DISABLED_SKILL_SLUGS: frozenset[str] = frozenset({
    "system_ui_automation",
})

_SkillT = TypeVar("_SkillT", bound=Skill)


def is_chat_enabled_skill(skill: Skill) -> bool:
    return skill.slug not in CHAT_DISABLED_SKILL_SLUGS


def filter_chat_enabled_skills(skills: Iterable[_SkillT]) -> list[_SkillT]:
    return [skill for skill in skills if is_chat_enabled_skill(skill)]
