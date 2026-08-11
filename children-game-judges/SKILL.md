---
name: children-game-judges
description: Use when you need to judge a collection of children's game or code projects packaged in a zip or folder and produce an animated HTML award ceremony page with three award categories and multiple winners per category.
---

# Children Game Judges

## Overview

A reusable skill that evaluates children's game or code projects and generates a single-file animated HTML award site.

The skill accepts a local folder or a `.zip` archive. Inside it, each sub-folder is one family's work and must be named `姓名-作品名`. It scores every project across five dimensions, resolves ties, assigns every project to exactly one award, and renders an interactive single-page site with three 3D award cards. An award may have multiple winners.

## When to Use

- You have a `.zip` archive or local folder whose sub-folders are child/family projects.
- Each project is in its own sub-folder.
- You need multi-dimensional scoring and deterministic tie-breaking.
- The final deliverable is a browser-viewable HTML award ceremony.

## When Not to Use

- Projects are not organized by folder.
- You only need a spreadsheet of scores instead of an animated page.
- You need real-time voting or audience interaction.

## Arguments

| Argument | Required | Default | Description |
|---|---|---|---|
| `--input` | Yes | — | Path to a `.zip` file or local directory |
| `--output` | Yes | — | Output directory where the HTML site will be written |
| `--awards` | No | `驭AI大师奖,创意造梦师奖,未来探索家奖` | Exactly three comma-separated award names |

## Workflow

1. Run the helper script in discovery mode with a folder or zip path:
   ```bash
   python scripts/judge.py --input <path> --output <dir>
   ```
2. The script prints a JSON summary for every discovered project.
3. Read each project's files and assign five scores (0–20) plus encouraging comments.
4. Write the scores to `scores.json` inside the output directory.
5. Re-run the same command; the script reads `scores.json`, distributes participants evenly across the three awards by snake draft (skipped if any `winnerIds` are set), and generates `index.html`.
6. Open `index.html` in a browser to verify the card flips, winner lists, and detail views.

## Scoring Dimensions

Score each project 0–20 in these five dimensions (total max 100):

| Dimension | Focus |
|---|---|
| 创意想象力 | Original ideas, story, world-building |
| 完成度/质量 | Polish, completeness, absence of bugs |
| 技术探索 | Use of coding or AI features beyond basics |
| 视觉/听觉表现 | Art, color, sound, layout |
| 趣味性/可玩性 | Fun to interact with, clear goal, pacing |

### Scoring Guidance for Children's Work

Because these are children's projects, score generously and keep the ceremony uplifting. Treat **19 in each dimension** as the norm — dip to 18 for rough edges, reach 20 for genuine delight, and rarely go below 17. Every project should finish at **95 or above** overall.

Target distribution:

| Target | Score Range |
|---|---|
| Participation projects | 95–96 |
| Average project | 96–97 |
| Strong award entries | 97–99 |

This keeps the whole field at 95+ while leaving just enough separation for the snake-draft awards to feel earned.

## Awards and Tie-Breaking

Default awards. The dimension priority listed for each is used only to match projects to awards under manual override (see below); the default distribution ignores it.

- **驭AI大师奖** — 完成度/质量 > 技术探索 > 视觉/听觉表现 > 趣味性/可玩性 > 创意想象力
- **创意造梦师奖** — 创意想象力 > 完成度/质量 > 趣味性/可玩性 > 视觉/听觉表现 > 技术探索
- **未来探索家奖** — 技术探索 > 创意想象力 > 完成度/质量 > 趣味性/可玩性 > 视觉/听觉表现

### Even Distribution (default)

When `scores.json` lists **no** `winnerIds` for any award, all participants are split evenly across the three awards by a **snake draft** over total score (ties broken by the lexicographically greater stable ID). Each award ends up the same size — 15 projects become 5/5/5, 18 become 6/6/6 — and total strength stays balanced: the top scorer goes to the first award, then the pick order reverses each round. Every participant appears in exactly one award. An opened card shows its winners without scrolling for up to six entries and scrolls beyond that.

### Manual Override

To pin specific winners, set `winnerIds` on the relevant awards inside `scores.json`. As soon as **any** award has `winnerIds`, even distribution is skipped: listed winners are kept (the first award wins any duplicate), each still-empty award is seeded with its single best-fitting participant, and remaining participants go to their best-fitting award using the dimension priorities above (ties prefer the award with fewer winners). The old single-value `winnerId` field is still accepted as a compatibility alias.

Recommended award shape:

```json
{
  "id": "creative-dreamer",
  "title": "创意造梦师奖",
  "winnerIds": ["child-001", "child-004"]
}
```

## Output Site

The output directory contains:

- `index.html` — the complete, self-contained award ceremony (data embedded, works offline).
- `scores.json` — structured data backup with participants, scores, and award assignments. Award assignments are normalized to `winnerIds` arrays.

Old `detail-*.html` files from previous versions are automatically removed when regenerating.

The home page includes:

- Three award cards, initially face-down, showing the award name on the back.
- **First click** on a card flips it with a 3D animation and confetti, revealing that award's complete winner list.
- Clicking a specific winner in the list opens that work's in-page detail view.
- A back button on the detail view returns to the home page and leaves the card face-up.

The detail view shows the award, author, project, total score, score label, a "🌟 作品闪光点" list with up to 3 encouraging sentences, a gentle "🚀 下一步挑战" suggestion, and the five dimension scores.

## Cover Images

If a project folder contains a file named `cover.png` (or `cover.jpg` / `cover.jpeg` / `cover.webp`), it is embedded into the page in two places:

- A small thumbnail next to the author/project name in the award card's winner list.
- A large 16:9 banner at the top of that work's detail view.

Covers are downscaled to at most 960 px wide and base64-encoded as JPEG, so `index.html` stays self-contained and works offline. Any aspect ratio works (the banner crops with `object-fit: cover`), but **16:9 landscape at roughly 1280×720** looks best. Projects without a cover simply render without one.

## Event Logos

If the following logo files exist, they are embedded in the top-left corner of the home page, horizontally aligned:

- `F:\\Edge\\透明底人工智能加速中心logo.png`
- `F:\\Edge\\摩力创境透明底logo.png`

Logos are resized and base64-encoded so the generated `index.html` remains self-contained and works offline. If a logo has no alpha channel (for example, a white-background RGB PNG), the script automatically removes near-white pixels so the logo blends into the stage background.

## Example

```bash
python scripts/judge.py --input "F:\\molispark\\亲子沙龙第二期\\亲子沙龙第二期游戏示例" --output "F:\\molispark\\亲子沙龙第二期\\award-output-test"
```

After writing `scores.json` and re-running, open:

```bash
start "F:\\molispark\\亲子沙龙第二期\\award-output-test\\index.html"
```

Or double-click `index.html` in the output folder.

## Notes

- Put the `--output` directory outside the `--input` folder: every sub-folder of `--input` is discovered as a project, so an output folder nested inside `--input` is misread as a project and overwrites `scores.json`.
- The skill does not call external LLM APIs. The calling agent performs the evaluation directly.
- `index.html` embeds all data and styles, so it works offline when opened directly — no local server or CDN required.
- Binary files are listed by name but not read for scoring.
- Empty folders and non-folder entries at the top level are skipped with a warning.
- Names, project names, and comments are HTML-escaped before rendering.
