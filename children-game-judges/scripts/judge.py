#!/usr/bin/env python3
"""Children's game project judge helper (single-page award ceremony).

Usage:
    python judge.py --input <zip_or_folder> --output <dir> [--awards a,b,c]

First run discovers projects and prints summaries in the new scores.json format.
The caller (agent) should write scores.json into the output directory.
Second run reads scores.json, standardizes data, assigns every project to exactly
one award, and generates a single index.html. Winners are revealed by flipping an
award card; clicking a specific winner opens that project's detail view.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from PIL import Image

DIMENSIONS = [
    "创意想象力",
    "完成度/质量",
    "技术探索",
    "视觉/听觉表现",
    "趣味性/可玩性",
]

DEFAULT_AWARD_TITLES = ["驭AI大师奖", "创意造梦师奖", "未来探索家奖"]

DEFAULT_AWARDS = [
    {"id": "ai-master", "title": "驭AI大师奖", "icon": "robot", "theme": "purple"},
    {"id": "creative-dreamer", "title": "创意造梦师奖", "icon": "planet", "theme": "coral"},
    {"id": "future-explorer", "title": "未来探索家奖", "icon": "rocket", "theme": "teal"},
]

FALLBACK_STRENGTHS = [
    ["作品构思完整", "认真完成了自己的创意", "展现了很好的探索精神"],
    ["游戏目标清晰", "操作体验顺畅", "整体完成度值得肯定"],
    ["创意很有特点", "愿意尝试新技术", "对游戏世界有自己的理解"],
]

FALLBACK_SUGGESTIONS = [
    "继续保持这份好奇心，下一次一定会创造出更精彩的作品！",
    "勇敢尝试新的玩法，让自己的创意继续成长！",
    "期待你下一次加入更多惊喜，把作品变得更加丰富！",
]

TEXT_EXTENSIONS = {
    ".html", ".htm", ".js", ".css", ".py", ".txt", ".md", ".json",
    ".xml", ".yaml", ".yml",
}

MAX_SUMMARY_CHARS = 16000


LOGO_PATHS = [
    (Path(r"F:\Edge\透明底人工智能加速中心logo.png"), "人工智能加速中心"),
    (Path(r"F:\Edge\摩力创境透明底logo.png"), "摩力创境"),
]

COVER_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")


def find_cover(project_dir: Path) -> Path | None:
    """Return the project's cover image (cover.png/jpg/...) if one exists."""
    try:
        for entry in sorted(project_dir.iterdir()):
            if entry.is_file() and entry.stem.lower() == "cover" and entry.suffix.lower() in COVER_EXTENSIONS:
                return entry
    except OSError:
        pass
    return None


def load_cover_data(path: Path, max_width: int = 960) -> str | None:
    """Load a cover image, downscale it, and return a JPEG base64 data URI."""
    try:
        img = Image.open(path).convert("RGB")
        w, h = img.size
        if w > max_width:
            ratio = max_width / w
            img = img.resize((max_width, int(h * ratio)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=82)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
    except Exception as exc:
        print(f"Warning: could not load cover {path}: {exc}", file=sys.stderr)
        return None


def remove_white_background(img: Image.Image) -> Image.Image:
    """Make near-white pixels transparent; keeps saturated logos like orange text."""
    img = img.convert("RGBA")
    w, h = img.size
    out = Image.new("RGBA", (w, h))
    src = img.load()
    dst = out.load()
    threshold = 12000  # distance squared from white
    for y in range(h):
        for x in range(w):
            r, g, b, a = src[x, y]
            dist_sq = (255 - r) ** 2 + (255 - g) ** 2 + (255 - b) ** 2
            if dist_sq < threshold:
                dst[x, y] = (255, 255, 255, 0)
            else:
                dst[x, y] = (r, g, b, a)
    return out


def load_logo_data(path: Path, max_height: int = 120) -> str | None:
    """Load a logo image, resize it for display, and return a base64 data URI."""
    if not path.exists():
        return None
    try:
        img = Image.open(path)
        had_alpha = img.mode in ("RGBA", "LA", "P")
        # Convert palette-with-transparency to RGBA without removing colors
        if img.mode == "P":
            img = img.convert("RGBA")
        elif img.mode not in ("RGBA", "LA"):
            img = img.convert("RGBA")

        # Resize first so background removal works on fewer pixels.
        w, h = img.size
        if h > max_height:
            ratio = max_height / h
            img = img.resize((int(w * ratio), max_height), Image.LANCZOS)

        # If the source had no alpha channel, it is likely a white-background
        # logo saved as RGB. Remove the white background so it blends in.
        if not had_alpha:
            img = remove_white_background(img)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{b64}"
    except Exception as exc:
        print(f"Warning: could not load logo {path}: {exc}", file=sys.stderr)
        return None


def build_site_logos_html() -> str:
    """Build the top-left logo strip for the home page."""
    imgs = []
    for path, alt in LOGO_PATHS:
        data_uri = load_logo_data(path)
        if data_uri:
            imgs.append(f'<img src="{data_uri}" alt="{alt}" class="site-logo">')
    if not imgs:
        return ""
    return '<div class="site-logos">' + "".join(imgs) + '</div>'


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Judge children's game projects and generate a single-page award HTML site."
    )
    parser.add_argument("--input", required=True, help="Path to zip archive or project folder")
    parser.add_argument("--output", required=True, help="Output directory for generated HTML files")
    parser.add_argument(
        "--awards",
        default=",".join(DEFAULT_AWARD_TITLES),
        help="Exactly three comma-separated award names",
    )
    parser.add_argument(
        "--event",
        default="摩力AI亲子公益沙龙 · 第二期",
        help="Event label shown in the badge at the top of the home page",
    )
    return parser.parse_args()


def extract_zip(zip_path: Path) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="children-judge-"))
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(temp_dir)
    return temp_dir


def find_project_root(input_path: Path) -> Path:
    """Resolve an optional archive wrapper without mistaking one project for it."""
    if input_path.is_dir():
        entries = [e for e in input_path.iterdir() if e.is_dir()]
        files = [e for e in input_path.iterdir() if e.is_file()]
        if len(entries) == 1 and not files:
            sole = entries[0]
            nested_projects = [e for e in sole.iterdir() if e.is_dir() and "-" in e.name]
            if "-" not in sole.name and nested_projects:
                return sole
        return input_path
    raise ValueError(f"Input path is not a directory: {input_path}")


def discover_projects(input_path: Path) -> list[dict[str, Any]]:
    root = find_project_root(input_path)
    projects: list[dict[str, Any]] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        name = entry.name.strip()
        if not name:
            continue
        if "-" in name:
            author, _, project = name.partition("-")
            author = author.strip() or "神秘小作者"
            project = project.strip() or name
        else:
            author = "神秘小作者"
            project = name
        projects.append({
            "key": name,
            "dir": str(entry),
            "author": author,
            "project": project,
        })
    return projects


def collect_files(project_dir: Path, depth: int = 2) -> list[Path]:
    files: list[Path] = []
    for root, _dirs, filenames in os.walk(project_dir):
        current_depth = len(Path(root).relative_to(project_dir).parts)
        if current_depth > depth:
            continue
        for filename in filenames:
            files.append(Path(root) / filename)
    return sorted(files)


def summarize_project(project: dict[str, Any]) -> str:
    project_dir = Path(project["dir"])
    files = collect_files(project_dir)
    text_parts: list[str] = []
    binary_files: list[str] = []
    chars_used = 0

    for file in files:
        rel = file.relative_to(project_dir).as_posix()
        if file.suffix.lower() in TEXT_EXTENSIONS:
            try:
                content = file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if not content.strip():
                continue
            snippet = f"--- {rel} ---\n{content}\n"
            if chars_used + len(snippet) > MAX_SUMMARY_CHARS:
                remaining = MAX_SUMMARY_CHARS - chars_used
                if remaining > 200:
                    text_parts.append(snippet[:remaining])
                    chars_used += remaining
                break
            text_parts.append(snippet)
            chars_used += len(snippet)
        else:
            binary_files.append(rel)

    summary = f"作者：{project['author']}\n作品：{project['project']}\n路径：{project['dir']}\n\n"
    summary += "文件列表：\n" + "\n".join(f.relative_to(project_dir).as_posix() for f in files) + "\n\n"
    if text_parts:
        summary += "文本内容：\n" + "".join(text_parts) + "\n"
    if binary_files:
        summary += f"其他文件（未读取内容）：{', '.join(binary_files)}\n"
    return summary


def print_discovery(projects: list[dict[str, Any]]) -> None:
    print("=== DISCOVERED PROJECTS ===")
    print(json.dumps(
        [{"key": p["key"], "author": p["author"], "project": p["project"]} for p in projects],
        ensure_ascii=False,
        indent=2,
    ))
    print("\n=== PROJECT SUMMARIES ===")
    for p in projects:
        print(summarize_project(p))
        print("\n" + "=" * 60 + "\n")


def load_scores(output_dir: Path) -> dict[str, Any] | None:
    scores_path = output_dir / "scores.json"
    if not scores_path.exists():
        return None
    with open(scores_path, "r", encoding="utf-8") as f:
        return json.load(f)


def is_legacy_scores(scores: dict[str, Any]) -> bool:
    return "version" not in scores and "participants" not in scores


def resolve_winner_ids(
    raw_ids: Any,
    key_to_id: dict[str, str],
    id_to_participant: dict[str, dict[str, Any]],
) -> list[str]:
    """Resolve participant keys/IDs and keep each winner once per award."""
    if raw_ids is None:
        return []
    if not isinstance(raw_ids, (list, tuple, set)):
        raw_ids = [raw_ids]

    resolved: list[str] = []
    for raw_id in raw_ids:
        if not raw_id:
            continue
        candidate = key_to_id.get(str(raw_id), str(raw_id))
        if candidate in id_to_participant and candidate not in resolved:
            resolved.append(candidate)
    return resolved


def normalize_scores(
    scores: dict[str, Any] | None,
    projects: list[dict[str, Any]],
    award_titles: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Convert legacy or new-format scores into stable participants/awards arrays."""

    if scores is None:
        scores = {}

    participants: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    if is_legacy_scores(scores):
        score_map = scores
    else:
        score_map = {}
        for p in scores.get("participants", []):
            key = p.get("author", "") + "-" + p.get("project", "")
            if "key" in p:
                key = p["key"]
            score_map[key] = p

    for i, project in enumerate(projects):
        key = project["key"]
        data = score_map.get(key, {})
        author = data.get("author", project["author"])
        project_name = data.get("project", project["project"])
        pid = f"child-{i+1:03d}"
        while pid in seen_ids:
            pid = f"child-{i+1:03d}-{len(seen_ids)}"
        seen_ids.add(pid)

        raw_scores = data.get("scores", {})
        if isinstance(raw_scores, dict):
            merged_scores = {d: raw_scores.get(d, 0) for d in DIMENSIONS}
        else:
            merged_scores = {d: 0 for d in DIMENSIONS}

        comment = data.get("comment", "")
        strengths = data.get("strengths")
        suggestion = data.get("suggestion")
        if not strengths and comment:
            strengths = extract_strengths(comment)
        if not suggestion and comment:
            suggestion = extract_suggestion(comment) or FALLBACK_SUGGESTIONS[i % len(FALLBACK_SUGGESTIONS)]
        if not strengths:
            strengths = FALLBACK_STRENGTHS[i % len(FALLBACK_STRENGTHS)]
        if not suggestion:
            suggestion = FALLBACK_SUGGESTIONS[i % len(FALLBACK_SUGGESTIONS)]

        participants.append({
            "id": pid,
            "key": key,
            "dir": project["dir"],
            "author": author,
            "project": project_name,
            "scores": merged_scores,
            "strengths": strengths[:3] if isinstance(strengths, list) else [str(strengths)],
            "suggestion": suggestion,
            "comment": comment,
        })

    key_to_id = {p["key"]: p["id"] for p in participants}
    id_to_participant = {p["id"]: p for p in participants}

    input_awards: list[Any] = []
    if not is_legacy_scores(scores):
        raw_awards = scores.get("awards", [])
        if isinstance(raw_awards, list):
            input_awards = raw_awards

    normalized_awards: list[dict[str, Any]] = []
    for i, title in enumerate(award_titles):
        base = DEFAULT_AWARDS[i % len(DEFAULT_AWARDS)].copy()
        user_award: dict[str, Any] = {}
        if i < len(input_awards):
            if isinstance(input_awards[i], dict):
                user_award = input_awards[i]
                base.update({k: v for k, v in user_award.items() if v is not None})

        if "title" not in user_award:
            base["title"] = title
        base.setdefault("id", base.get("id") or f"award-{i+1:03d}")
        base.setdefault("icon", DEFAULT_AWARDS[i % len(DEFAULT_AWARDS)]["icon"])
        base.setdefault("theme", DEFAULT_AWARDS[i % len(DEFAULT_AWARDS)]["theme"])

        raw_winner_ids = base.get("winnerIds")
        if raw_winner_ids is None:
            raw_winner_ids = base.pop("winner_ids", None)
        if raw_winner_ids is None:
            raw_winner_ids = base.get("winnerId")
        if raw_winner_ids is None:
            raw_winner_ids = base.pop("winner_id", None)
        base.pop("winnerId", None)
        base["winnerIds"] = resolve_winner_ids(raw_winner_ids, key_to_id, id_to_participant)

        normalized_awards.append(base)

    claimed_ids: set[str] = set()
    for award in normalized_awards:
        unique_winner_ids = []
        for winner_id in award["winnerIds"]:
            if winner_id in claimed_ids:
                continue
            unique_winner_ids.append(winner_id)
            claimed_ids.add(winner_id)
        award["winnerIds"] = unique_winner_ids

    if not any(award["winnerIds"] for award in normalized_awards):
        ranked = sorted(
            participants,
            key=lambda p: (
                sum(p["scores"].get(d, 0) for d in DIMENSIONS),
                p["id"],
            ),
            reverse=True,
        )
        num_awards = len(normalized_awards)
        for rank_idx, participant in enumerate(ranked):
            round_idx, pos_in_round = divmod(rank_idx, num_awards)
            award_pos = pos_in_round if round_idx % 2 == 0 else num_awards - 1 - pos_in_round
            normalized_awards[award_pos]["winnerIds"].append(participant["id"])
        return participants, normalized_awards

    assigned_ids = {
        winner_id
        for award in normalized_awards
        for winner_id in award["winnerIds"]
    }
    for award in normalized_awards:
        if award["winnerIds"]:
            continue
        candidates = [participant for participant in participants if participant["id"] not in assigned_ids]
        if not candidates:
            break
        best = select_best_for_award(candidates, award)
        award["winnerIds"].append(best["id"])
        assigned_ids.add(best["id"])

    for participant in participants:
        if participant["id"] in assigned_ids or not normalized_awards:
            continue
        award_index = select_award_for_participant(participant, normalized_awards)
        normalized_awards[award_index]["winnerIds"].append(participant["id"])
        assigned_ids.add(participant["id"])

    return participants, normalized_awards


def award_priority(award: dict[str, Any]) -> list[str]:
    """Return the dimension priority for an award title."""
    title = award.get("title", "")
    if "AI" in title or "大师" in title:
        return ["完成度/质量", "技术探索", "视觉/听觉表现", "趣味性/可玩性", "创意想象力"]
    if "创意" in title or "造梦" in title:
        return ["创意想象力", "完成度/质量", "趣味性/可玩性", "视觉/听觉表现", "技术探索"]
    if "未来" in title or "探索" in title:
        return ["技术探索", "创意想象力", "完成度/质量", "趣味性/可玩性", "视觉/听觉表现"]
    return DIMENSIONS.copy()


def award_fit_key(participant: dict[str, Any], award: dict[str, Any]) -> tuple[float, ...]:
    """Build the deterministic score tuple used to match a project to an award."""
    scores = participant["scores"]
    total = sum(scores.get(dim, 0) for dim in DIMENSIONS)
    return (total, *(scores.get(dim, 0) for dim in award_priority(award)))


def select_award_for_participant(
    participant: dict[str, Any],
    awards: list[dict[str, Any]],
) -> int:
    """Choose the best award, balancing exact ties across award groups."""
    return max(
        range(len(awards)),
        key=lambda index: (
            award_fit_key(participant, awards[index]),
            -len(awards[index]["winnerIds"]),
            -index,
        ),
    )


def select_best_for_award(
    candidates: list[dict[str, Any]],
    award: dict[str, Any],
) -> dict[str, Any]:
    """Pick the best candidate for an award using award priorities and total score."""

    return max(candidates, key=lambda participant: (*award_fit_key(participant, award), participant["id"]))


def extract_strengths(comment: str) -> list[str]:
    """Heuristically split a comment into up to 3 positive bullets."""
    sentences = [s.strip() for s in comment.replace("！", "。").replace("!", "。").split("。") if s.strip()]
    positives: list[str] = []
    suggestion_markers = ("建议", "如果", "下次", "期待", "希望", "可以", "试试", "尝试")
    for s in sentences:
        if any(s.startswith(w) for w in suggestion_markers):
            continue
        if any(m in s for m in suggestion_markers):
            continue
        if len(s) > 120:
            s = s[:118] + "…"
        positives.append(s)
        if len(positives) >= 3:
            break
    if not positives:
        positives = ["作品构思完整", "认真完成了自己的创意", "展现了很好的探索精神"]
    return positives[:3]


def extract_suggestion(comment: str) -> str | None:
    """Try to extract a single growth suggestion from the comment."""
    suggestion_markers = ["如果", "下次", "期待", "希望", "可以", "试试", "尝试"]
    sentences = [s.strip() for s in comment.replace("！", "。").replace("!", "。").split("。") if s.strip()]
    for s in sentences:
        marker_pos = -1
        chosen_marker = ""
        for m in suggestion_markers:
            pos = s.find(m)
            if pos != -1 and (marker_pos == -1 or pos < marker_pos):
                marker_pos = pos
                chosen_marker = m
        if marker_pos == -1:
            continue

        suggestion = s[marker_pos:].lstrip()
        if chosen_marker == "可以":
            suggestion = suggestion[2:].lstrip("，,:： ")
        elif chosen_marker in ("如果", "下次", "期待", "希望", "试试", "尝试"):
            suggestion = suggestion[len(chosen_marker):].lstrip("，,:： ")

        for split_word in ("，", ",", "。", "！"):
            if split_word in suggestion:
                suggestion = suggestion.split(split_word, 1)[0]
                break

        if suggestion:
            if not suggestion.endswith(("！", "!", "。", "~", "?", "？")):
                suggestion += "~"
            return suggestion
    return None


def compute_total(scores: dict[str, int | float]) -> float:
    return sum(scores.get(d, 0) for d in DIMENSIONS)


def compute_average(scores: dict[str, int | float]) -> float:
    if not scores:
        return 0.0
    return compute_total(scores) / len(DIMENSIONS)


def qualitative_label(score: float) -> str:
    if score >= 18.5:
        return "表现出色"
    if score >= 17.5:
        return "非常优秀"
    if score >= 16.0:
        return "亮点突出"
    return "很有潜力"


def escape_html(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


COMMON_CSS = r"""
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { height: 100%; }
body {
  background-color: #F4EFE6;
  background-image:
    radial-gradient(circle at 50% 0%, rgba(115, 87, 255, 0.14) 0%, transparent 42%),
    radial-gradient(circle at 12% 86%, rgba(255, 128, 102, 0.12) 0%, transparent 46%),
    radial-gradient(circle at 88% 84%, rgba(46, 196, 182, 0.12) 0%, transparent 46%),
    radial-gradient(circle at 50% 48%, rgba(214, 168, 60, 0.10) 0%, transparent 58%),
    linear-gradient(180deg, #FBF7F0 0%, #EDE5D7 100%);
  color: #3A335A;
  font-family: "Microsoft YaHei", "PingFang SC", system-ui, -apple-system, sans-serif;
  -webkit-font-smoothing: antialiased;
  overflow-x: hidden;
}
#bg-particles {
  position: fixed; inset: 0; pointer-events: none; z-index: 0;
}

.stage {
  position: absolute; top: 0; left: 0; width: 100%; height: 100%;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  opacity: 0; pointer-events: none; transform: scale(0.96);
  transition: opacity 0.6s cubic-bezier(0.22, 1, 0.36, 1), transform 0.6s cubic-bezier(0.22, 1, 0.36, 1);
  z-index: 1;
  padding: clamp(10px, 1.5vh, 18px) clamp(14px, 2.5vw, 32px);
}
.stage.active { opacity: 1; pointer-events: auto; transform: scale(1); }

.stage-header {
  text-align: center;
  z-index: 2;
  margin-bottom: clamp(6px, 1.2vh, 14px);
  flex-shrink: 0;
}
.site-logos {
  position: absolute;
  top: clamp(14px, 2.5vh, 28px);
  left: clamp(16px, 3vw, 40px);
  display: flex; align-items: center; gap: clamp(0.6rem, 1.2vw, 1rem);
  z-index: 10;
  pointer-events: none;
}
.site-logo {
  height: clamp(36px, 5.5vh, 56px);
  width: auto;
  max-width: 180px;
  object-fit: contain;
  filter: drop-shadow(0 2px 6px rgba(58,51,90,0.18));
}
/* 摩力创境是方形 logo，单独放大以与横向的加速中心 logo 视觉平衡（LOGO_PATHS 第二个） */
.site-logos img:nth-child(2) { height: clamp(56px, 8.5vh, 88px); }
.event-badge {
  display: inline-flex; align-items: center; gap: 0.4rem;
  color: #B8860B;
  font-size: clamp(0.75rem, 1.3vw, 0.9rem);
  font-weight: 600;
  margin-bottom: 0.35rem;
  background: rgba(200, 144, 26, 0.08);
  border: 1px solid rgba(200, 144, 26, 0.30);
  border-radius: 999px;
  padding: 0.25rem 0.7rem;
}
.home-title {
  font-size: clamp(1.6rem, 3.5vw, 2.4rem);
  font-weight: 800;
  line-height: 1.15;
  letter-spacing: 0.04em;
  background: linear-gradient(to right, #9A7416 0%, #C8901A 45%, #9A7416 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  filter: drop-shadow(0 2px 6px rgba(200, 144, 26, 0.18));
  animation: titleFadeIn 0.8s ease-out;
}
.home-subtitle {
  font-size: clamp(0.9rem, 1.5vw, 1.1rem);
  color: rgba(58, 51, 90, 0.65);
  margin-top: 0.25rem;
  animation: titleFadeIn 0.8s ease-out 0.1s both;
}
@keyframes titleFadeIn {
  0% { opacity: 0; transform: translateY(20px); }
  100% { opacity: 1; transform: translateY(0); }
}

.main-area {
  width: 100%;
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  position: relative;
  z-index: 2;
  min-height: 0;
  gap: clamp(16px, 3vh, 32px);
}

.cards-container {
  display: flex; flex-wrap: wrap;
  justify-content: center; align-items: center;
  gap: clamp(0.8rem, 2vw, 1.8rem);
  perspective: 1200px;
  margin-bottom: 0;
  width: 100%;
  max-width: 1400px;
}

.card-wrap {
  width: clamp(260px, 28vw, 360px);
  height: clamp(380px, 54vh, 540px);
  position: relative;
  cursor: pointer;
  transition: transform 0.25s ease, opacity 0.35s ease;
  flex-shrink: 0;
}
.card-wrap:hover { transform: translateY(-6px); }
.card-wrap.flipped:hover { transform: translateY(-6px); }
.card-inner {
  position: relative; width: 100%; height: 100%;
  transform-style: preserve-3d;
  transition: transform 0.75s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.card-inner.flipped { transform: rotateY(180deg); }
.card-face {
  position: absolute; inset: 0;
  border-radius: clamp(20px, 3vw, 28px);
  backface-visibility: hidden;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  padding: clamp(1rem, 2.5vh, 1.5rem); text-align: center;
  overflow: hidden;
  border: 1.5px solid rgba(58, 51, 90, 0.10);
  background: linear-gradient(158deg, #FFFFFF 0%, #FBF7F2 44%, #F4EFF8 100%);
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,0.9),
    0 26px 60px rgba(58, 51, 90, 0.16),
    0 8px 20px rgba(58, 51, 90, 0.10);
}
.card-back {
  color: #3A335A;
  background:
    radial-gradient(circle at 50% 50%, rgba(58,51,90,0.06) 0%, transparent 36%),
    repeating-radial-gradient(circle at 50% 50%, rgba(58,51,90,0.045) 0px, rgba(58,51,90,0.045) 1px, transparent 1px, transparent 9px),
    linear-gradient(158deg, #FFFFFF, #FBF7F2);
}
.card-back::before {
  content: ''; position: absolute; inset: 0;
  background: radial-gradient(circle at 50% 50%, rgba(58,51,90,0.05) 0%, transparent 55%);
  pointer-events: none;
}
.card-back::after {
  content: ''; position: absolute;
  inset: 9px;
  border: 1px solid rgba(200, 144, 26, 0.22);
  border-radius: 16px;
  pointer-events: none;
}
.card-front {
  transform: rotateY(180deg);
  color: #3A335A;
  background: linear-gradient(158deg, #FFFFFF 0%, #FBF7F2 46%, #F4EFF8 100%);
  justify-content: flex-start;
  gap: 0.4rem;
}
.card-front::after {
  content: ''; position: absolute;
  inset: 9px;
  border: 1px solid rgba(200, 144, 26, 0.22);
  border-radius: 16px;
  pointer-events: none;
}
.card-icon { width: clamp(56px, 8vh, 76px); height: clamp(56px, 8vh, 76px); margin-bottom: 0.8rem; color: #3A335A; filter: drop-shadow(0 4px 8px rgba(58,51,90,0.18)); }
.card-award-name {
  font-size: clamp(1.3rem, 2.4vw, 1.9rem); font-weight: 800;
  margin-bottom: 0.4rem;
  line-height: 1.2;
}
.card-front .card-icon {
  width: clamp(38px, 5vh, 48px);
  height: clamp(38px, 5vh, 48px);
  margin-bottom: 0.1rem;
}
.card-front .card-award-name {
  font-size: clamp(1.05rem, 1.9vw, 1.4rem);
  margin-bottom: 0.15rem;
}
.card-hint {
  position: absolute;
  bottom: clamp(0.7rem, 1.8vh, 1.1rem);
  left: 50%;
  transform: translateX(-50%);
  font-size: 0.78rem;
  opacity: 0.7;
  color: rgba(58,51,90,0.55);
  white-space: nowrap;
}

.card-wrap[data-theme="purple"] .card-face {
  border-color: rgba(123, 92, 255, 0.45);
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,0.9),
    0 26px 60px rgba(58, 51, 90, 0.16),
    0 10px 30px rgba(115, 87, 255, 0.20);
}
.card-wrap[data-theme="purple"] .card-back,
.card-wrap[data-theme="purple"] .card-front {
  background:
    radial-gradient(circle at 50% 50%, rgba(115,87,255,0.14) 0%, transparent 46%),
    repeating-radial-gradient(circle at 50% 50%, rgba(115,87,255,0.07) 0px, rgba(115,87,255,0.07) 1px, transparent 1px, transparent 9px),
    linear-gradient(158deg, #FFFFFF, #F6F2FF);
}
.card-wrap[data-theme="purple"] .card-award-name { color: #6B4EFF; }
.card-wrap[data-theme="purple"] .card-icon { color: #7B5CFF; }
.card-wrap[data-theme="coral"] .card-face {
  border-color: rgba(230, 120, 90, 0.45);
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,0.9),
    0 26px 60px rgba(58, 51, 90, 0.16),
    0 10px 30px rgba(255, 128, 102, 0.20);
}
.card-wrap[data-theme="coral"] .card-back,
.card-wrap[data-theme="coral"] .card-front {
  background:
    radial-gradient(circle at 50% 50%, rgba(255,128,102,0.14) 0%, transparent 46%),
    repeating-radial-gradient(circle at 50% 50%, rgba(255,128,102,0.07) 0px, rgba(255,128,102,0.07) 1px, transparent 1px, transparent 9px),
    linear-gradient(158deg, #FFFFFF, #FFF4F0);
}
.card-wrap[data-theme="coral"] .card-award-name { color: #E15A28; }
.card-wrap[data-theme="coral"] .card-icon { color: #FF8055; }
.card-wrap[data-theme="teal"] .card-face {
  border-color: rgba(30, 180, 158, 0.45);
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,0.9),
    0 26px 60px rgba(58, 51, 90, 0.16),
    0 10px 30px rgba(46, 196, 182, 0.20);
}
.card-wrap[data-theme="teal"] .card-back,
.card-wrap[data-theme="teal"] .card-front {
  background:
    radial-gradient(circle at 50% 50%, rgba(46,196,182,0.14) 0%, transparent 46%),
    repeating-radial-gradient(circle at 50% 50%, rgba(46,196,182,0.07) 0px, rgba(46,196,182,0.07) 1px, transparent 1px, transparent 9px),
    linear-gradient(158deg, #FFFFFF, #EEFAF7);
}
.card-wrap[data-theme="teal"] .card-award-name { color: #118A75; }
.card-wrap[data-theme="teal"] .card-icon { color: #1FB39B; }

.winner-list {
  width: 100%;
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  margin-top: 0.15rem;
  overflow-y: auto;
  padding-right: 0.15rem;
}
.winner-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 0.55rem;
  border: 1px solid rgba(58, 51, 90, 0.12);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.72);
  color: #3A335A;
  padding: 0.3rem 0.6rem;
  text-align: left;
  cursor: pointer;
  transition: background 0.2s ease, border-color 0.2s ease, transform 0.2s ease;
}
.winner-item:hover, .winner-item:focus-visible {
  background: rgba(200, 144, 26, 0.16);
  border-color: rgba(200, 144, 26, 0.50);
  transform: translateY(-1px);
  outline: none;
}
.winner-item-cover {
  width: 52px;
  height: 30px;
  border-radius: 6px;
  object-fit: cover;
  flex-shrink: 0;
  border: 1px solid rgba(58, 51, 90, 0.12);
  background: rgba(58, 51, 90, 0.06);
}
.winner-item-text { min-width: 0; flex: 1; }
.winner-item-name {
  display: block;
  font-size: 0.88rem;
  font-weight: 800;
  line-height: 1.2;
}
.winner-item-project {
  display: block;
  margin-top: 0.08rem;
  color: rgba(58, 51, 90, 0.60);
  font-size: 0.7rem;
  line-height: 1.15;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.winner-list-empty {
  color: rgba(58, 51, 90, 0.55);
  font-size: 0.9rem;
  padding: 0.8rem 0;
}
.card-hint-front { font-size: 0.72rem; opacity: 0.7; color: rgba(58,51,90,0.5); margin-top: auto; }

.confetti {
  position: fixed; width: 10px; height: 10px; pointer-events: none; z-index: 50;
  animation: confettiFall 2.4s ease-out forwards;
}
@keyframes confettiFall {
  0% { transform: translateY(-10vh) rotate(0deg); opacity: 1; }
  100% { transform: translateY(110vh) rotate(720deg); opacity: 0; }
}

.detail-stage {
  position: fixed; inset: 0; z-index: 40;
  display: flex; align-items: center; justify-content: center;
  background: rgba(54, 48, 82, 0.34);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  opacity: 0; pointer-events: none;
  transition: opacity 0.45s ease;
  padding: clamp(16px, 3vw, 40px);
}
.detail-stage.active { opacity: 1; pointer-events: auto; }

.detail-card {
  background: linear-gradient(145deg, #FFFFFF, #FBF7F0);
  color: #3A335A;
  border-radius: 28px;
  padding: clamp(1.5rem, 4vw, 3rem);
  max-width: 720px; width: 100%;
  max-height: 90vh;
  overflow-y: auto;
  border: 1px solid rgba(58, 51, 90, 0.10);
  box-shadow: 0 30px 80px rgba(58, 51, 90, 0.22);
  transform: translateY(20px) scale(0.96);
  opacity: 0;
  transition: transform 0.5s cubic-bezier(0.22,1,0.36,1) 0.08s, opacity 0.5s ease 0.08s;
}
.detail-stage.active .detail-card { transform: translateY(0) scale(1); opacity: 1; }
.detail-header { display: flex; flex-direction: column; align-items: center; text-align: center; margin-bottom: 1.2rem; }
.detail-cover {
  margin: -0.4rem 0 1.2rem;
  border-radius: 18px;
  overflow: hidden;
  border: 1px solid rgba(58, 51, 90, 0.10);
  box-shadow: 0 12px 30px rgba(58, 51, 90, 0.12);
  aspect-ratio: 16 / 9;
  background: rgba(58, 51, 90, 0.05);
}
.detail-cover img { width: 100%; height: 100%; object-fit: cover; display: block; }
.detail-header svg { width: 56px; height: 56px; margin-bottom: 0.4rem; color: #3A335A; }
.detail-award {
  display: inline-block;
  background: linear-gradient(145deg, #FFD66B, #FFA62B);
  color: #10142F; padding: 0.35rem 0.9rem; border-radius: 999px;
  font-weight: 700; font-size: 0.95rem; margin-bottom: 0.7rem;
}
.detail-title { font-size: clamp(1.6rem, 5vw, 2.4rem); font-weight: 800; }
.detail-project { font-size: clamp(1rem, 3vw, 1.3rem); color: rgba(58,51,90,0.6); margin-top: 0.3rem; }
.detail-score {
  display: flex; align-items: center; justify-content: center; gap: 1rem;
  margin: 1.2rem 0;
  flex-wrap: wrap;
}
.score-big {
  font-size: clamp(3rem, 10vw, 4.5rem); font-weight: 800; line-height: 1;
  background: linear-gradient(to bottom, #C8901A, #9A7416);
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent;
}
.score-big span { font-size: 0.45em; color: rgba(58,51,90,0.55); -webkit-text-fill-color: rgba(58,51,90,0.55); }
.score-badge {
  background: rgba(200, 144, 26, 0.12); border: 1px solid rgba(200, 144, 26, 0.35);
  color: #9A7416; padding: 0.4rem 0.9rem; border-radius: 999px;
  font-weight: 700; font-size: 1rem;
}
.detail-suggestion, .detail-dimensions { margin-bottom: 1.2rem; }
.detail-strengths h4, .detail-suggestion h4 {
  font-size: 1.1rem; margin-bottom: 0.6rem; color: #9A7416;
}
.detail-strengths ul { list-style: none; display: flex; flex-direction: column; gap: 0.4rem; }
.detail-strengths li {
  background: rgba(58,51,90,0.04); border: 1px solid rgba(58,51,90,0.08);
  border-radius: 12px; padding: 0.6rem 0.9rem; line-height: 1.45;
}
.detail-suggestion p {
  background: rgba(46, 196, 182, 0.08); border: 1px solid rgba(46, 196, 182, 0.2);
  border-radius: 12px; padding: 0.8rem 1rem; line-height: 1.6;
}
.detail-dimensions {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 0.5rem;
}
.detail-dimension {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  background: rgba(200, 144, 26, 0.06);
  border: 1px solid rgba(200, 144, 26, 0.18);
  border-radius: 10px;
  padding: 0.55rem 0.75rem;
  color: rgba(58, 51, 90, 0.85);
  font-size: 0.88rem;
}
.detail-dimension-score { color: #9A7416; font-weight: 800; white-space: nowrap; }
.back-btn {
  margin-top: 0.5rem; padding: 0.7rem 1.8rem; border: none; border-radius: 999px;
  background: linear-gradient(145deg, #FFD66B, #FFA62B); color: #10142F;
  font-size: 1rem; font-weight: 700; cursor: pointer;
  box-shadow: 0 4px 16px rgba(255, 214, 107, 0.3);
  transition: transform 0.18s, box-shadow 0.18s;
}
.back-btn:hover { transform: translateY(-2px); box-shadow: 0 6px 22px rgba(255, 214, 107, 0.45); }

@media (max-height: 820px) {
  .home-title { font-size: clamp(1.5rem, 3.2vw, 2.2rem); }
  .card-wrap { width: clamp(240px, 26vw, 320px); height: clamp(340px, 50vh, 460px); }
  .card-icon { width: clamp(48px, 7vh, 64px); height: clamp(48px, 7vh, 64px); }
  .winner-list { gap: 0.25rem; }
}

@media (max-height: 700px) {
  .card-wrap { width: clamp(220px, 24vw, 280px); height: clamp(300px, 46vh, 400px); }
  .card-icon { width: clamp(44px, 6.5vh, 56px); height: clamp(44px, 6.5vh, 56px); }
  .winner-list { gap: 0.2rem; }
}

@media (max-width: 700px) {
  html, body { overflow-y: auto; }
  .stage { position: relative; min-height: 100vh; height: auto; padding: 14px 16px; }
  .cards-container { flex-direction: column; gap: 1rem; }
  .card-wrap { width: min(100%, 420px); height: clamp(420px, 70vh, 560px); }
}
"""


COMMON_BG_JS = r"""
function initBackground() {
  const svgNS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(svgNS, 'svg');
  svg.id = 'bg-particles';
  svg.setAttribute('viewBox', '0 0 100 100');
  svg.setAttribute('preserveAspectRatio', 'xMidYMid slice');

  const defs = document.createElementNS(svgNS, 'defs');
  defs.innerHTML = `
    <filter id="particleGlow" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur stdDeviation="0.5" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <radialGradient id="centerGlow" cx="50%" cy="50%" r="70%">
      <stop offset="0%" stop-color="#7357FF" stop-opacity="0.10"/>
      <stop offset="45%" stop-color="#FF8066" stop-opacity="0.05"/>
      <stop offset="100%" stop-color="#10142F" stop-opacity="0"/>
    </radialGradient>
  `;
  svg.appendChild(defs);

  const glowRect = document.createElementNS(svgNS, 'rect');
  glowRect.setAttribute('x', '0'); glowRect.setAttribute('y', '0');
  glowRect.setAttribute('width', '100'); glowRect.setAttribute('height', '100');
  glowRect.setAttribute('fill', 'url(#centerGlow)');
  svg.appendChild(glowRect);

  const colors = ['#FFD66B', '#FF8066', '#7357FF'];
  for (let i = 0; i < 20; i++) {
    const x = 2 + Math.random() * 96;
    const y = 5 + Math.random() * 90;
    const r = 0.15 + Math.random() * 0.6;
    const delay = Math.random() * 7;
    const duration = 8 + Math.random() * 6;
    const rise = 12 + Math.random() * 12;
    const color = colors[i % colors.length];
    const circle = document.createElementNS(svgNS, 'circle');
    circle.setAttribute('cx', x);
    circle.setAttribute('cy', y);
    circle.setAttribute('r', r);
    circle.setAttribute('fill', color);
    circle.setAttribute('opacity', '0');
    circle.setAttribute('filter', 'url(#particleGlow)');
    const animY = document.createElementNS(svgNS, 'animate');
    animY.setAttribute('attributeName', 'cy');
    animY.setAttribute('values', `${y};${Math.max(2, y - rise)};${y}`);
    animY.setAttribute('dur', `${duration}s`);
    animY.setAttribute('repeatCount', 'indefinite');
    animY.setAttribute('begin', `${delay}s`);
    const animOp = document.createElementNS(svgNS, 'animate');
    animOp.setAttribute('attributeName', 'opacity');
    animOp.setAttribute('values', '0;0.25;0');
    animOp.setAttribute('dur', `${duration}s`);
    animOp.setAttribute('repeatCount', 'indefinite');
    animOp.setAttribute('begin', `${delay}s`);
    circle.appendChild(animY);
    circle.appendChild(animOp);
    svg.appendChild(circle);
  }
  document.body.appendChild(svg);
}
initBackground();
"""


SINGLE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>小小游戏创造家 作品颁奖典礼</title>
<style>
{{COMMON_CSS}}
</style>
</head>
<body>
<div id="home" class="stage active">
  {{SITE_LOGOS}}
  <header class="stage-header">
    <div class="event-badge">
      <svg width="16" height="16" viewBox="0 0 64 64" style="vertical-align:-3px">
        <path d="M16 12 L48 12 L48 18 C48 30 40 38 32 38 C24 38 16 30 16 18 Z" fill="currentColor"/>
        <rect x="28" y="38" width="8" height="10" fill="currentColor"/>
        <rect x="22" y="48" width="20" height="4" rx="2" fill="currentColor"/>
      </svg>
      {{EVENT_LABEL}}
    </div>
    <h1 class="home-title">小小游戏创造家</h1>
    <h2 class="home-subtitle">作品颁奖典礼</h2>
  </header>

  <main class="main-area">
    <div class="cards-container" id="cardsContainer"></div>
  </main>

</div>

<div id="detail" class="detail-stage">
  <div class="detail-card" id="detailCard">
    <div class="detail-header">
      <svg viewBox="0 0 64 64" id="detailIcon"><use href="#icon-robot"></use></svg>
      <div class="detail-award" id="detailAward">奖项</div>
      <div class="detail-title" id="detailAuthor">姓名</div>
      <div class="detail-project" id="detailProject">作品</div>
    </div>
    <div class="detail-cover" id="detailCoverWrap" hidden>
      <img id="detailCover" alt="作品封面">
    </div>
    <div class="detail-score">
      <div class="score-big" id="detailScore">0<span>/100</span></div>
      <div class="score-badge" id="detailLabel">作品评价</div>
    </div>
    <div class="detail-strengths">
        <h4>🌟 作品闪光点</h4>
      <ul id="detailStrengths"></ul>
    </div>
    <div class="detail-suggestion">
      <h4>🚀 下一步挑战</h4>
      <p id="detailSuggestion">建议</p>
    </div>
    <div class="detail-dimensions" id="detailDimensions"></div>
    <div style="text-align:center">
      <button class="back-btn" id="backBtn">← 返回颁奖台</button>
    </div>
  </div>
</div>

<script>
const AWARDS = {{AWARD_DATA}};

const cardsContainer = document.getElementById('cardsContainer');
const detailStage = document.getElementById('detail');
let isRevealing = false;

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function createSvgSprite() {
  const svgNS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(svgNS, 'svg');
  svg.style.display = 'none';
  svg.innerHTML = `
    <symbol id="icon-robot" viewBox="0 0 64 64">
      <rect x="18" y="14" width="28" height="36" rx="6" fill="currentColor"/>
      <circle cx="26" cy="28" r="3" fill="#10142F"/>
      <circle cx="38" cy="28" r="3" fill="#10142F"/>
      <rect x="24" y="38" width="16" height="4" rx="2" fill="#10142F"/>
      <rect x="28" y="6" width="8" height="10" rx="2" fill="currentColor"/>
    </symbol>
    <symbol id="icon-planet" viewBox="0 0 64 64">
      <circle cx="32" cy="32" r="14" fill="currentColor"/>
      <ellipse cx="32" cy="32" rx="22" ry="8" fill="none" stroke="currentColor" stroke-width="3" transform="rotate(-20 32 32)"/>
    </symbol>
    <symbol id="icon-rocket" viewBox="0 0 64 64">
      <path d="M32 8 L42 36 L32 32 L22 36 Z" fill="currentColor"/>
      <circle cx="32" cy="26" r="4" fill="#10142F"/>
      <path d="M26 38 L22 50 L28 42 Z" fill="currentColor"/>
      <path d="M38 38 L42 50 L36 42 Z" fill="currentColor"/>
    </symbol>
  `;
  document.body.appendChild(svg);
}

function createConfetti() {
  const colors = ['#FFD66B', '#FF8066', '#7357FF', '#2EC4B6', '#F8F7FF'];
  for (let i = 0; i < 30; i++) {
    const c = document.createElement('div');
    c.className = 'confetti';
    c.style.left = (10 + Math.random() * 80) + 'vw';
    c.style.background = colors[Math.floor(Math.random() * colors.length)];
    c.style.animationDuration = (1.8 + Math.random() * 0.6) + 's';
    c.style.transform = `rotate(${Math.random() * 360}deg)`;
    document.body.appendChild(c);
    setTimeout(() => c.remove(), 2600);
  }
}

function showDetail(awardIndex, winnerIndex) {
  const award = AWARDS[awardIndex];
  const data = award && award.winners ? award.winners[winnerIndex] : null;
  if (!award || !data) return;
  document.getElementById('detailIcon').innerHTML = `<use href="#icon-${escapeHtml(award.icon)}"></use>`;
  document.getElementById('detailAward').textContent = award.award;
  document.getElementById('detailAuthor').textContent = data.author;
  document.getElementById('detailProject').textContent = '作品：《' + data.project + '》';
  const coverWrap = document.getElementById('detailCoverWrap');
  const coverImg = document.getElementById('detailCover');
  if (data.cover) {
    coverImg.src = data.cover;
    coverImg.alt = data.project + ' 封面';
    coverWrap.hidden = false;
  } else {
    coverImg.removeAttribute('src');
    coverWrap.hidden = true;
  }
  document.getElementById('detailScore').innerHTML = data.total + '<span>/100</span>';
  document.getElementById('detailLabel').textContent = data.label;
  const strengthList = document.getElementById('detailStrengths');
  strengthList.innerHTML = '';
  (data.strengths || []).forEach(s => {
    const li = document.createElement('li');
    li.textContent = s;
    strengthList.appendChild(li);
  });
  document.getElementById('detailSuggestion').textContent = data.suggestion;
  const dimensions = document.getElementById('detailDimensions');
  dimensions.innerHTML = '';
  (data.dimensions || []).forEach(dimension => {
    const row = document.createElement('div');
    row.className = 'detail-dimension';
    const name = document.createElement('span');
    name.textContent = dimension.name;
    const score = document.createElement('span');
    score.className = 'detail-dimension-score';
    score.textContent = dimension.score + '/20';
    row.append(name, score);
    dimensions.appendChild(row);
  });
  detailStage.classList.add('active');
}

function hideDetail() {
  detailStage.classList.remove('active');
}

function createCard(award, index) {
  const wrap = document.createElement('div');
  wrap.className = 'card-wrap';
  wrap.id = 'card-' + index;
  wrap.dataset.theme = award.theme;
  wrap.setAttribute('aria-label', award.award + '，点击揭晓获奖作品');
  wrap.innerHTML = `
    <div class="card-inner">
      <div class="card-face card-back">
        <svg class="card-icon"><use href="#icon-${escapeHtml(award.icon)}"></use></svg>
        <div class="card-award-name">${escapeHtml(award.award)}</div>
        <div class="card-hint">点击揭晓</div>
      </div>
      <div class="card-face card-front">
        <svg class="card-icon"><use href="#icon-${escapeHtml(award.icon)}"></use></svg>
        <div class="card-award-name">${escapeHtml(award.award)}</div>
        <div class="winner-list" aria-label="${escapeHtml(award.award)}获奖作品名单"></div>
        <div class="card-hint-front">点击具体作品查看详情</div>
      </div>
    </div>
  `;
  const winnerList = wrap.querySelector('.winner-list');
  if (!award.winners.length) {
    const empty = document.createElement('div');
    empty.className = 'winner-list-empty';
    empty.textContent = '暂无获奖作品';
    winnerList.appendChild(empty);
  } else {
    award.winners.forEach((winner, winnerIndex) => {
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'winner-item';
      item.setAttribute('aria-label', winner.author + '，' + winner.project + '，查看详情');
      const author = document.createElement('span');
      author.className = 'winner-item-name';
      author.textContent = winner.author;
      const project = document.createElement('span');
      project.className = 'winner-item-project';
      project.textContent = '《' + winner.project + '》';
      const text = document.createElement('span');
      text.className = 'winner-item-text';
      text.append(author, project);
      if (winner.cover) {
        const thumb = document.createElement('img');
        thumb.className = 'winner-item-cover';
        thumb.src = winner.cover;
        thumb.alt = '';
        item.append(thumb, text);
      } else {
        item.append(text);
      }
      item.addEventListener('click', event => {
        event.stopPropagation();
        showDetail(index, winnerIndex);
      });
      winnerList.appendChild(item);
    });
  }
  wrap.addEventListener('click', () => {
    if (isRevealing) return;
    const inner = wrap.querySelector('.card-inner');
    if (!wrap.classList.contains('flipped')) {
      isRevealing = true;
      wrap.classList.add('flipped');
      inner.classList.add('flipped');
      wrap.setAttribute('aria-label', award.award + '，已揭晓，点击获奖作品查看详情');
      createConfetti();
      setTimeout(() => { isRevealing = false; }, 800);
    }
  });
  return wrap;
}

document.getElementById('backBtn').addEventListener('click', hideDetail);
detailStage.addEventListener('click', (e) => {
  if (e.target === detailStage) hideDetail();
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') hideDetail();
});

createSvgSprite();
AWARDS.forEach((award, i) => cardsContainer.appendChild(createCard(award, i)));

{{COMMON_BG_JS}}
</script>
</body>
</html>
"""


def generate_html(
    participants: list[dict[str, Any]],
    awards: list[dict[str, Any]],
    output_dir: Path,
    event_label: str = "摩力AI亲子公益沙龙 · 第二期",
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)

    # Clean up old detail pages from previous versions
    for old in output_dir.glob("detail-*.html"):
        old.unlink(missing_ok=True)

    participant_by_id = {participant["id"]: participant for participant in participants}
    cover_by_id: dict[str, str] = {}
    for participant in participants:
        project_dir = participant.get("dir")
        if not project_dir:
            continue
        cover_path = find_cover(Path(project_dir))
        if cover_path is None:
            continue
        cover_uri = load_cover_data(cover_path)
        if cover_uri:
            cover_by_id[participant["id"]] = cover_uri
    award_data: list[dict[str, Any]] = []
    for award in awards:
        winners: list[dict[str, Any]] = []
        for winner_id in award.get("winnerIds", []):
            winner = participant_by_id.get(winner_id)
            if winner is None:
                continue
            total = int(compute_total(winner["scores"]))
            strengths = winner["strengths"][:3] if isinstance(winner["strengths"], list) else [str(winner["strengths"])]
            dimensions = [
                {"name": dimension, "score": winner["scores"].get(dimension, 0)}
                for dimension in DIMENSIONS
            ]
            winners.append({
                "id": winner["id"],
                "author": winner["author"],
                "project": winner["project"],
                "total": total,
                "label": qualitative_label(compute_average(winner["scores"])),
                "strengths": strengths,
                "suggestion": winner["suggestion"],
                "dimensions": dimensions,
                "cover": cover_by_id.get(winner["id"]),
            })
        award_data.append({
            "award": award["title"],
            "icon": award.get("icon", "robot"),
            "theme": award.get("theme", "purple"),
            "winners": winners,
        })

    html = SINGLE_TEMPLATE
    html = html.replace("{{COMMON_CSS}}", COMMON_CSS)
    html = html.replace("{{SITE_LOGOS}}", build_site_logos_html())
    html = html.replace("{{AWARD_DATA}}", json.dumps(award_data, ensure_ascii=False))
    html = html.replace("{{COMMON_BG_JS}}", COMMON_BG_JS)
    safe_label = event_label.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html = html.replace("{{EVENT_LABEL}}", safe_label)
    (output_dir / "index.html").write_text(html, encoding="utf-8")

    # Write scores.json backup
    scores_path = output_dir / "scores.json"
    scores_path.write_text(
        json.dumps(
            {"version": 3, "participants": participants, "awards": awards},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return output_dir / "index.html"


def main() -> None:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()
    award_titles = [a.strip() for a in args.awards.split(",") if a.strip()]
    if len(award_titles) != 3:
        raise ValueError("--awards must contain exactly three award names")

    if not input_path.exists():
        raise FileNotFoundError(f"Input path not found: {input_path}")

    temp_extracted: Path | None = None
    try:
        if input_path.is_file() and input_path.suffix.lower() == ".zip":
            temp_extracted = extract_zip(input_path)
            scan_path = temp_extracted
        elif input_path.is_dir():
            scan_path = input_path
        else:
            raise ValueError(f"Input must be a .zip file or directory: {input_path}")

        projects = discover_projects(scan_path)
        if not projects:
            raise ValueError("No project folders found. Expected sub-folders like '姓名-作品名'.")

        output_dir.mkdir(parents=True, exist_ok=True)
        scores = load_scores(output_dir)

        if scores is None:
            print_discovery(projects)
            print("\n=== NEXT STEPS ===")
            print(f"Please evaluate the projects above and write scores to: {output_dir / 'scores.json'}")
            print("\nNew format (recommended):")
            example_participants = []
            for i, p in enumerate(projects):
                example_participants.append({
                    "id": f"child-{i+1:03d}",
                    "author": p["author"],
                    "project": p["project"],
                    "scores": {d: 18 for d in DIMENSIONS},
                    "strengths": [
                        "游戏目标非常清晰",
                        "操作过程流畅自然",
                        "音效和得分系统很完整",
                    ],
                    "suggestion": "尝试加入 Boss 关卡，让故事更精彩。",
                })
            print(json.dumps({
                "version": 3,
                "participants": example_participants,
                "awards": [
                    {"id": "ai-master", "title": "驭AI大师奖", "winnerIds": ["child-001"]},
                    {"id": "creative-dreamer", "title": "创意造梦师奖", "winnerIds": ["child-002"]},
                    {"id": "future-explorer", "title": "未来探索家奖", "winnerIds": ["child-003"]},
                ],
            }, ensure_ascii=False, indent=2))
            print("\nLegacy format also supported: {\"作者-作品\": {\"scores\": {...}, \"comment\": \"...\"}}")
            return

        participants, awards = normalize_scores(scores, projects, award_titles)
        output_path = generate_html(participants, awards, output_dir, event_label=args.event)

        print(f"Generated award site: {output_dir}")
        print(f"Home page: {output_path}")
        print("\nAwards:")
        participants_by_id = {participant["id"]: participant for participant in participants}
        for award in awards:
            winners = [
                participants_by_id[wid]
                for wid in award.get("winnerIds", [])
                if wid in participants_by_id
            ]
            if winners:
                names = ", ".join(f"{winner['author']} - {winner['project']}" for winner in winners)
                print(f"  {award['title']}: {names}")
            else:
                print(f"  {award['title']}: 无获奖者")
    finally:
        if temp_extracted and temp_extracted.exists():
            shutil.rmtree(temp_extracted, ignore_errors=True)


if __name__ == "__main__":
    main()
