#!/usr/bin/env python3
"""Prompt builder for kid-career-portrait-batch."""

import json
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent


def load_careers(career_map_path: Path = None) -> dict:
    """Load career mapping from JSON. Falls back to bundled data/career_map.json."""
    if career_map_path is None:
        career_map_path = SKILL_DIR / "data" / "career_map.json"
    if not career_map_path.exists():
        career_map_path = SKILL_DIR / "assets" / "careers.json"
    if career_map_path.exists():
        return json.loads(career_map_path.read_text(encoding="utf-8"))
    return {}


def load_prompt_template(template_path: Path = None) -> str:
    """Load prompt template. Falls back to bundled templates/career_portrait_prompt.txt."""
    if template_path is None:
        template_path = SKILL_DIR / "templates" / "career_portrait_prompt.txt"
    if not template_path.exists():
        template_path = SKILL_DIR / "assets" / "prompt_template.txt"
    if template_path.exists():
        return template_path.read_text(encoding="utf-8")

    return (
        "Use the provided child photo as the identity reference.\n"
        "Create a photorealistic professional portrait of the same person as an adult, "
        "approximately {age} years old, working as a {career}.\n"
        "Preserve facial identity, ethnicity, and natural features.\n"
        "{clothing}\n{scene}\n"
        "Constraints: clearly adult, no text, no watermark, realistic style.\n"
    )


def build_prompt(
    name: str,
    career: str,
    careers_map: dict,
    template: str,
    adult_age: str,
) -> str:
    """Build a professional adult career portrait prompt.

    If the template contains the literal placeholder ``{{职业}}``, only that
    placeholder is replaced. This is the preferred mode for fixed user-provided
    prompt templates.
    """
    if "{{职业}}" in template:
        return template.replace("{{职业}}", career)

    if "{{career}}" in template:
        return template.replace("{{career}}", career)

    info = careers_map.get(career)
    if info:
        career_en = info.get("en", career)
        scene = info.get("scene", "")
        clothing = info.get("clothing", "")
        career_desc = career_en
    else:
        career_desc = career
        scene = "Use a clean, tasteful, professional background related to the career."
        clothing = (
            f"Show the person wearing appropriate professional clothing and accessories "
            f"for a {career}."
        )

    scene_line = f"Background: {scene}." if scene else ""
    clothing_line = f"The person is {clothing}." if clothing else ""

    return template.format(
        age=adult_age,
        career=career_desc,
        clothing=clothing_line,
        scene=scene_line,
    )
