#!/usr/bin/env python3
"""Unit tests for picture-book-judges."""

from __future__ import annotations

import base64
import csv
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import judge  # noqa: E402


class _RawGbkZipInfo(zipfile.ZipInfo):
    """ZipInfo subclass that writes raw GBK bytes with flag bit 0x800 cleared (Windows legacy zip)."""

    def _encodeFilenameFlags(self) -> tuple[bytes, int]:  # noqa: N802
        return self.filename.encode("gb18030"), self.flag_bits & ~0x800


def make_jpeg_data_uri(color: tuple[int, int, int], size: tuple[int, int] = (120, 160)) -> str:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def make_stpageflip_html(
    title: str,
    author: str,
    date: str,
    pages: list[dict[str, str]],
    cover: str = "",
    decl: str = "const",
    lib_padding_bytes: int = 48000,
) -> str:
    fake_lib = "// StPageFlip stub\nvar StPadding = '" + ("x" * lib_padding_bytes) + "';\n"
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>{title}</title></head>
<body>
<script>{fake_lib}</script>
<script>
{decl} TITLE={json.dumps(title, ensure_ascii=False)}, AUTHOR={json.dumps(author, ensure_ascii=False)}, DATE={json.dumps(date, ensure_ascii=False)};
{decl} COVER={json.dumps(cover, ensure_ascii=False)}, PAGES={json.dumps(pages, ensure_ascii=False)};
</script>
</body>
</html>
"""


class PictureBookJudgeTests(unittest.TestCase):
    def test_parse_stpageflip_html_beyond_44kb(self) -> None:
        cover_uri = make_jpeg_data_uri((220, 140, 80))
        p1_uri = make_jpeg_data_uri((80, 150, 220))
        p2_uri = make_jpeg_data_uri((90, 180, 120))
        html = make_stpageflip_html(
            title="星河小书童",
            author="林小满",
            date="2026.11",
            cover=cover_uri,
            pages=[
                {"img": p1_uri, "text": "第一页：阿满打开魔法书。"},
                {"img": p2_uri, "text": "第二页：小星星落在了肩膀上。"},
            ],
            decl="var",
            lib_padding_bytes=50000,
        )
        self.assertGreater(html.find("TITLE="), 48000)
        parsed, warnings = judge.parse_stpageflip_html(html)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(warnings, [])
        self.assertEqual(parsed["title"], "星河小书童")
        self.assertEqual(parsed["author"], "林小满")
        self.assertEqual(parsed["date"], "2026.11")
        self.assertEqual(parsed["cover"], cover_uri)
        self.assertEqual(len(parsed["pages"]), 2)
        self.assertEqual(parsed["pages"][1]["text"], "第二页：小星星落在了肩膀上。")

    def test_discover_mixed_formats_and_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            img_uri = make_jpeg_data_uri((100, 120, 200))

            # 1. Top-level <书名>.html where author comes from HTML AUTHOR
            (root / "阿澄的星星旅行.html").write_text(
                make_stpageflip_html("阿澄的星星旅行", "阿澄", "2026.11", [{"img": img_uri, "text": "出发！"}], cover=img_uri),
                encoding="utf-8",
            )
            # 2. Top-level <姓名>-<作品名>.html overriding generic "小作者"
            (root / "王小明-云端小火车.html").write_text(
                make_stpageflip_html("云端小火车", "小作者", "2026.11", [{"img": img_uri, "text": "呜呜！"}], cover=img_uri),
                encoding="utf-8",
            )
            # 3. Subdir with story.json + images
            sub_story = root / "陈朵朵-月光茶会"
            sub_story.mkdir()
            Image.new("RGB", (100, 130), (200, 100, 100)).save(sub_story / "cover.png")
            Image.new("RGB", (100, 130), (100, 200, 100)).save(sub_story / "p01.png")
            (sub_story / "story.json").write_text(
                json.dumps({
                    "title": "月光茶会",
                    "author": "陈朵朵",
                    "pages": [{"name": "p01", "caption": "小兔子端出了桂花茶。"}],
                }, ensure_ascii=False),
                encoding="utf-8",
            )
            # 4. Loose image folder
            sub_imgs = root / "张乐乐-彩虹积木"
            sub_imgs.mkdir()
            Image.new("RGB", (100, 130), (255, 200, 0)).save(sub_imgs / "00_cover.jpg")
            Image.new("RGB", (100, 130), (0, 200, 255)).save(sub_imgs / "01_p1.jpg")
            (sub_imgs / "captions.txt").write_text("乐乐搭了一座彩虹桥。\n", encoding="utf-8")

            # 5. Empty folder + unsupported file -> explicit warnings, not silent
            (root / "空文件夹").mkdir()
            (root / "说明.docx").write_text("not a book", encoding="utf-8")

            books, warnings = judge.discover_books(root)
            self.assertEqual(len(books), 4)
            by_project = {b["project"]: b for b in books}
            self.assertEqual(by_project["阿澄的星星旅行"]["author"], "阿澄")
            self.assertEqual(by_project["云端小火车"]["author"], "王小明")
            self.assertEqual(by_project["月光茶会"]["source_type"], "story_json")
            self.assertEqual(by_project["彩虹积木"]["source_type"], "image_folder")
            self.assertTrue(any("空文件夹" in w for w in warnings))
            self.assertTrue(any("说明.docx" in w for w in warnings))

    def test_zip_discovery_and_zip_slip_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            img_uri = make_jpeg_data_uri((180, 90, 90))
            good_zip = root / "books.zip"
            with zipfile.ZipFile(good_zip, "w") as zf:
                zf.writestr(
                    "提交合集/李安-森林迷宫.html",
                    make_stpageflip_html("森林迷宫", "李安", "2026.11", [{"img": img_uri, "text": "树叶沙沙响。"}], cover=img_uri),
                )
            extracted = judge.extract_zip_safe(good_zip)
            try:
                books, _ = judge.discover_books(extracted)
                self.assertEqual(len(books), 1)
                self.assertEqual(books[0]["author"], "李安")
                self.assertEqual(books[0]["project"], "森林迷宫")
            finally:
                judge.shutil.rmtree(extracted, ignore_errors=True)

            evil_zip = root / "evil.zip"
            with zipfile.ZipFile(evil_zip, "w") as zf:
                zf.writestr("../../outside.txt", "bad")
            with self.assertRaises(ValueError):
                judge.extract_zip_safe(evil_zip)

    def test_gbk_zip_without_utf8_flag_and_path_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            img_uri = make_jpeg_data_uri((140, 160, 210))
            png_buf = io.BytesIO()
            Image.new("RGB", (100, 130), (120, 200, 140)).save(png_buf, format="PNG")
            png_bytes = png_buf.getvalue()

            gbk_zip = root / "第七期-空白谜案.zip"
            with zipfile.ZipFile(gbk_zip, "w") as zf:
                zi_html = _RawGbkZipInfo("第七期-空白谜案/01-云梦仙踪.html")
                zf.writestr(
                    zi_html,
                    make_stpageflip_html("云梦仙踪", "阿砚", "2026.11", [{"img": img_uri, "text": "山林起雾了。"}], cover=img_uri).encode("utf-8"),
                )
                zf.writestr(_RawGbkZipInfo("第七期-空白谜案/02-张三-森林奇遇/cover.png"), png_bytes)
                zf.writestr(_RawGbkZipInfo("第七期-空白谜案/02-张三-森林奇遇/images/p01.png"), png_bytes)
                zf.writestr(
                    _RawGbkZipInfo("第七期-空白谜案/02-张三-森林奇遇/story.json"),
                    json.dumps({
                        "title": "森林奇遇",
                        "author": "张三",
                        "pages": [{"img": "images/p01.png", "caption": "小狐狸发现一盏灯笼。"}],
                    }, ensure_ascii=False).encode("utf-8"),
                )

            with zipfile.ZipFile(gbk_zip, "r") as check_zf:
                for info in check_zf.infolist():
                    self.assertEqual(info.flag_bits & 0x800, 0)

            extracted = judge.extract_zip_safe(gbk_zip)
            try:
                books, warnings = judge.discover_books(extracted)
                self.assertEqual(warnings, [])
                self.assertEqual(len(books), 2)
                by_proj = {b["project"]: b for b in books}
                self.assertEqual(by_proj["云梦仙踪"]["author"], "阿砚")
                self.assertEqual(by_proj["森林奇遇"]["author"], "张三")
                self.assertEqual(by_proj["森林奇遇"]["source_type"], "story_json")
            finally:
                judge.shutil.rmtree(extracted, ignore_errors=True)

            # Drive letter, absolute path, and backslash Zip-Slip in non-UTF-8 zip must be blocked
            for bad_name in ("C:\\evil.txt", "/etc/passwd", "中文目录\\..\\..\\outside.txt"):
                bad_zip = root / "bad_path.zip"
                with zipfile.ZipFile(bad_zip, "w") as zf:
                    zf.writestr(_RawGbkZipInfo(bad_name), b"bad")
                with self.assertRaises(ValueError):
                    judge.extract_zip_safe(bad_zip)

    def test_find_project_root_hyphen_wrapper_and_numeric_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Single book folder with story.json + images/ must NOT unwrap into images/
            single = root / "陈朵朵-月光茶会"
            (single / "images").mkdir(parents=True)
            Image.new("RGB", (80, 100), (100, 120, 140)).save(single / "images" / "p01.png")
            (single / "story.json").write_text(json.dumps({"title": "月光茶会", "pages": []}), encoding="utf-8")
            self.assertEqual(judge.find_project_root(root), root)

            # Batch wrapper folder containing '-' IS unwrapped
            batch_root = Path(tmp) / "batch"
            wrapper = batch_root / "第七期-空白谜案"
            (wrapper / "张三-作品一").mkdir(parents=True)
            (wrapper / "李四-作品二").mkdir(parents=True)
            self.assertEqual(judge.find_project_root(batch_root), wrapper)

            # Pure numeric prefix does not override HTML AUTHOR; 02-张三-森林奇遇 extracts 张三
            self.assertEqual(judge.resolve_author_and_title("01-云梦仙踪", "阿砚", "云梦仙踪"), ("阿砚", "云梦仙踪"))
            self.assertEqual(judge.resolve_author_and_title("02-张三-森林奇遇", "", ""), ("张三", "森林奇遇"))

    def test_twenty_family_snake_draft_7_7_6_and_manual_override(self) -> None:
        books = [
            {
                "id": f"book-{i+1:03d}",
                "key": f"家庭{i+1:02d}-作品{i+1:02d}",
                "author": f"小作者{i+1:02d}",
                "project": f"奇妙绘本{i+1:02d}",
                "pages": [{"page": 1, "text": "t", "img": ""}],
                "source_file": f"book-{i+1:03d}.html",
                "cover": "",
            }
            for i in range(20)
        ]
        scores_data = {
            "version": 1,
            "participants": [
                {
                    "id": b["id"],
                    "scores": {
                        "故事结构与完整性": 19 if i % 3 else 20,
                        "画面表现与角色一致性": 19 if i % 2 else 20,
                        "创意想象力": 19,
                        "图文契合度": 19,
                        "完成度与细节": 19,
                    },
                }
                for i, b in enumerate(books)
            ],
        }
        participants, awards = judge.normalize_scores(scores_data, books, judge.DEFAULT_AWARD_TITLES)
        counts = [len(a["winnerIds"]) for a in awards]
        self.assertEqual(counts, [7, 7, 6])
        all_assigned = [wid for a in awards for wid in a["winnerIds"]]
        self.assertEqual(len(all_assigned), 20)
        self.assertEqual(len(set(all_assigned)), 20)
        self.assertEqual(len(participants), 20)

        # Manual override with winnerId (singular) and duplicate across awards -> deduplicated
        override_data = {
            "version": 1,
            "participants": scores_data["participants"],
            "awards": [
                {"id": "best-story", "title": "最佳故事奖", "winnerIds": ["book-001", "book-002"]},
                {"id": "best-art", "title": "最佳画面奖", "winnerId": "book-002"},  # duplicate + singular
                {"id": "best-creativity", "title": "最佳创意奖"},
            ],
        }
        _, ov_awards = judge.normalize_scores(override_data, books, judge.DEFAULT_AWARD_TITLES)
        ov_assigned = [wid for a in ov_awards for wid in a["winnerIds"]]
        self.assertEqual(len(ov_assigned), 20)
        self.assertEqual(len(set(ov_assigned)), 20)
        self.assertIn("book-001", ov_awards[0]["winnerIds"])
        self.assertIn("book-002", ov_awards[0]["winnerIds"])
        self.assertNotIn("book-002", ov_awards[1]["winnerIds"])
        self.assertTrue(all(len(a["winnerIds"]) >= 1 for a in ov_awards))

    def test_html_xss_escaping_and_csv_bom_formula_safety(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            in_dir = tmp_dir / "input"
            out_dir = tmp_dir / "output"
            in_dir.mkdir()
            img_uri = make_jpeg_data_uri((120, 180, 220))
            evil_title = '黑雾</script><img src=x onerror=alert(1)>'
            evil_author = '=CMD("calc")<script>'
            (in_dir / "book1.html").write_text(
                make_stpageflip_html(evil_title, evil_author, "2026.11", [{"img": img_uri, "text": "+1+1"}], cover=img_uri),
                encoding="utf-8",
            )
            books, _ = judge.discover_books(in_dir)
            scores = {
                "version": 1,
                "participants": [{
                    "id": "book-001",
                    "author": evil_author,
                    "project": evil_title,
                    "scores": {d: 19 for d in judge.DIMENSIONS},
                    "strengths": ["=SUM(1,2)", "<b>亮</b>点"],
                    "suggestion": "-尝试更多变化",
                }],
            }
            participants, awards = judge.normalize_scores(scores, books, judge.DEFAULT_AWARD_TITLES)
            index_path = judge.generate_html(
                participants=participants,
                awards=awards,
                books=books,
                output_dir=out_dir,
                event_label="测试<script>活动",
                page_title=judge.DEFAULT_PAGE_TITLE,
                page_subtitle=judge.DEFAULT_PAGE_SUBTITLE,
                logo_specs=[str(tmp_dir / "nonexistent-logo.png")],
                music_arg=None,
                no_music=True,
            )
            html_content = index_path.read_text(encoding="utf-8")
            self.assertNotIn('</script><img', html_content)
            self.assertIn('\\u003c/script\\u003e', html_content)
            self.assertIn('测试&lt;script&gt;活动', html_content)
            self.assertNotIn('<audio id="bgm"', html_content)

            csv_path = judge.write_awards_csv(participants, awards, out_dir)
            raw_bytes = csv_path.read_bytes()
            self.assertTrue(raw_bytes.startswith(b"\xef\xbb\xbf"))
            with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
                rows = list(csv.reader(f))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0][0], "奖项")
            # Formula prefixes neutralized (including leading whitespace bypass)
            self.assertTrue(rows[1][3].startswith("'=CMD"))
            self.assertTrue(rows[1][13].startswith("'-尝试"))
            self.assertEqual(judge.safe_csv_cell("  =SUM(1,2)"), "'  =SUM(1,2)")
            self.assertEqual(judge.safe_csv_cell(" \t+1+1"), "' \t+1+1")
            self.assertEqual(judge.safe_csv_cell("\n-cmd"), "'\n-cmd")
            self.assertEqual(judge.safe_csv_cell("  @evil"), "'  @evil")
            self.assertEqual(judge.safe_csv_cell("  普通评语"), "  普通评语")

    def test_logo_loaded_when_present_and_nested_output_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            in_dir = root / "submissions"
            in_dir.mkdir()
            nested_out = in_dir / "award-output"
            with self.assertRaises(ValueError):
                judge.validate_paths(in_dir, nested_out)
            with self.assertRaises(ValueError):
                judge.validate_paths(in_dir, in_dir)

            logo_path = root / "brand_logo.png"
            Image.new("RGB", (80, 40), (255, 120, 40)).save(logo_path)
            logos_html = judge.build_site_logos_html([f"{logo_path}|主办方", str(root / "missing.png")])
            self.assertIn("data:image/png;base64,", logos_html)
            self.assertIn('alt="主办方"', logos_html)


if __name__ == "__main__":
    unittest.main()
