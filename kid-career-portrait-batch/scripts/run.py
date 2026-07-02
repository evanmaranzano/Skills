#!/usr/bin/env python3
"""
kid-career-portrait-batch: batch-generate adult career portraits from children's photos.

Usage:
    python scripts/run.py --input ./kidtest --output ./output
    python scripts/run.py --input ./kidtest --output ./output --dry-run
"""

import argparse
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

from api_client import ImageEditClient
from image_utils import make_output_name, normalize_image_file, save_image
from parser import parse_filename_details, scan_images
from prompt_builder import build_prompt, load_careers, load_prompt_template
from report import write_failed, write_manifest, write_report
from ppt_builder import build_comparison_ppt
from lark_publish import publish as publish_to_lark

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent


def load_config(config_path: str) -> dict:
    if config_path and Path(config_path).exists():
        if yaml is None:
            print("WARNING: pyyaml not installed, skipping config file.", file=sys.stderr)
            return {}
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def resolve_value(cli_val, cfg_path: str, default=None, env_name: str = None):
    """Merge precedence: CLI args > env var > config file > default."""
    if cli_val is not None:
        return cli_val
    if env_name and os.environ.get(env_name):
        return os.environ[env_name]
    node = cfg
    for part in cfg_path.split("."):
        if isinstance(node, dict):
            node = node.get(part)
        else:
            node = None
            break
    return node if node is not None else default


def process_one(
    task: dict,
    client: ImageEditClient,
    careers_map: dict,
    template: str,
    adult_age: str,
    suffix: str,
    fmt: str,
    skip_existing: bool,
    logger: logging.Logger,
    size: str = None,
) -> dict:
    """Process a single image task."""
    name = task["name"]
    career = task["career"]
    gender = task.get("gender", "")
    src_path = task["path"]
    output_dir = task["output_dir"]

    out_name = make_output_name(name, career, suffix, fmt)
    out_path = output_dir / "images" / out_name

    record = {
        "name": name,
        "career": career,
        "gender": gender,
        "input_file": str(src_path),
        "output_file": str(out_path),
        "status": "",
        "error": "",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    prompt = build_prompt(name, career, careers_map, template, adult_age)
    record["prompt"] = prompt

    # skip existing
    if skip_existing and out_path.exists():
        logger.info(f"[SKIP] {src_path.name} -> {out_name} (already exists)")
        record["status"] = "skipped"
        try:
            if normalize_image_file(out_path, size):
                logger.info(f"[NORMALIZE] {out_name} -> {size}")
        except Exception as e:
            logger.warning(f"[NORMALIZE-SKIP] {out_name}: {e}")
        return record

    logger.info(f"[START] {src_path.name} -> {out_name}")

    result = client.call(src_path, prompt, logger, task["retry_times"], task["backoff"])

    if result["success"] and result["image_bytes"]:
        save_image(result["image_bytes"], out_path, size)
        record["status"] = "success"
        logger.info(f"[OK]    {out_name} ({len(result['image_bytes'])} bytes)")
    else:
        record["status"] = "failed"
        record["error"] = result.get("error", "unknown error")
        logger.error(f"[FAIL]  {src_path.name}: {record['error']}")
        err_entry = {
            "file": src_path.name,
            "status": result.get("status"),
            "error": record["error"],
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        err_log = output_dir / "logs" / "api_errors.jsonl"
        with open(err_log, "a", encoding="utf-8") as ef:
            ef.write(json.dumps(err_entry, ensure_ascii=False) + "\n")

    return record


def main():
    parser = argparse.ArgumentParser(
        description="Batch-generate adult career portraits from children's photos."
    )
    parser.add_argument("--input", "-i", required=True, help="input folder")
    parser.add_argument("--output", "-o", required=True, help="output folder")
    parser.add_argument("--config", default=None, help="config file path")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--fallback-base-url", default=None)
    parser.add_argument("--fallback-api-key", default=None)
    parser.add_argument("--fallback-model", default=None)
    parser.add_argument("--size", default=None)
    parser.add_argument("--quality", default=None)
    parser.add_argument("--concurrency", type=int, default=None)
    parser.add_argument("--retry", type=int, default=None)
    parser.add_argument("--backoff", type=int, default=None)
    parser.add_argument("--skip-existing", action="store_true", default=None)
    parser.add_argument("--no-skip-existing", action="store_true")
    parser.add_argument(
        "--dry-run", action="store_true", help="parse only, no API calls"
    )
    parser.add_argument(
        "--proxy",
        default=None,
        help="proxy URL, e.g. http://127.0.0.1:7897 (overrides system proxy)",
    )
    parser.add_argument(
        "--no-proxy", action="store_true", help="bypass all proxies (direct connection)"
    )
    parser.add_argument(
        "--career-map", default=None, help="path to custom career_map.json"
    )
    parser.add_argument(
        "--prompt-template", default=None, help="path to custom prompt template"
    )
    parser.add_argument("--no-ppt", action="store_true", help="do not create local PPTX")
    parser.add_argument("--ppt-name", default=None, help="local PPTX filename")
    parser.add_argument("--publish-lark", action="store_true", help="import PPTX and Base to Lark via lark-cli")
    parser.add_argument("--lark-folder-token", default=None, help="target Lark Drive folder token")
    parser.add_argument("--lark-name", default=None, help="Lark Slides/Base base name")
    parser.add_argument("--public-share", action="store_true", help="set Lark Slides/Base to anyone_readable; use only after explicit user request")
    args = parser.parse_args()

    # load config (find config.yaml if not specified)
    config_path = args.config
    if config_path is None:
        default_cfg = SKILL_DIR / "config.yaml"
        if default_cfg.exists():
            config_path = str(default_cfg)
    global cfg
    cfg = load_config(config_path)

    # merge configuration
    base_url = resolve_value(args.base_url, "api.base_url", "https://api-slb.packyapi.com")
    api_key = resolve_value(args.api_key, "api.api_key", env_name="IMAGE_API_KEY")
    model = resolve_value(args.model, "api.model", "gpt-image-2")
    size = resolve_value(args.size, "output.size", "1536x2048")
    quality = resolve_value(args.quality, "output.quality", "high")
    concurrency = resolve_value(args.concurrency, "batch.concurrency", 2)
    retry_times = resolve_value(args.retry, "batch.retry_times", 3)
    backoff = resolve_value(args.backoff, "batch.retry_backoff_seconds", 10)
    suffix = resolve_value(None, "output.suffix", "职业照")
    fmt = resolve_value(None, "output.format", "png")
    adult_age = resolve_value(None, "prompt.adult_age_range", "25-35")
    fallback_base_url = resolve_value(args.fallback_base_url, "api.fallback_base_url", None)
    fallback_api_key = resolve_value(args.fallback_api_key, "api.fallback_api_key", env_name="FALLBACK_IMAGE_API_KEY")
    fallback_model = resolve_value(args.fallback_model, "api.fallback_model", None)
    allowed_ext = [
        e.lower()
        for e in resolve_value(
            None, "input.allowed_extensions", [".jpg", ".jpeg", ".png", ".webp"]
        )
    ]
    separators = resolve_value(None, "input.filename_separators", [" ", "_", "-"])
    recursive = resolve_value(None, "input.recursive", False)

    # proxy handling
    proxies = None
    if args.no_proxy:
        proxies = {"http": None, "https": None}
    elif args.proxy:
        proxies = {"http": args.proxy, "https": args.proxy}
    elif resolve_value(None, "api.proxy", None):
        px = resolve_value(None, "api.proxy", None)
        proxies = {"http": px, "https": px}

    if args.no_skip_existing:
        skip_existing = False
    else:
        skip_existing = resolve_value(args.skip_existing, "batch.skip_existing", True)

    if not api_key and not args.dry_run:
        print(
            "ERROR: no API key. Set --api-key, IMAGE_API_KEY env, or api.api_key in config.",
            file=sys.stderr,
        )
        sys.exit(1)

    input_dir = Path(args.input).resolve()
    output_dir = Path(args.output).resolve()
    if not input_dir.is_dir():
        print(f"ERROR: input folder not found: {input_dir}", file=sys.stderr)
        sys.exit(1)

    # setup output dirs
    (output_dir / "images").mkdir(parents=True, exist_ok=True)
    (output_dir / "logs").mkdir(parents=True, exist_ok=True)

    # setup logging
    logger = logging.getLogger("kid-career")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    fh = logging.FileHandler(output_dir / "logs" / "run.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(sh)

    logger.info("=" * 60)
    logger.info(f"Input:  {input_dir}")
    logger.info(f"Output: {output_dir}")
    logger.info(f"Model:  {model}  Size: {size}  Quality: {quality}")
    logger.info(
        f"Concurrent: {concurrency}  Retry: {retry_times}  Skip existing: {skip_existing}"
    )
    logger.info("=" * 60)

    # scan
    image_files = scan_images(input_dir, recursive, allowed_ext)
    logger.info(f"Found {len(image_files)} image file(s).")

    careers_map = load_careers(
        Path(args.career_map) if args.career_map else None
    )
    template = load_prompt_template(
        Path(args.prompt_template) if args.prompt_template else None
    )

    # parse filenames
    tasks = []
    skipped_parse = []
    for img in image_files:
        parsed = parse_filename_details(img.stem, separators)
        if not parsed:
            logger.warning(f"[PARSE-SKIP] cannot parse: {img.name}")
            skipped_parse.append(img.name)
            continue
        tasks.append(
            {
                "name": parsed["name"],
                "gender": parsed.get("gender", ""),
                "career": parsed["career"],
                "path": img,
                "output_dir": output_dir,
                "retry_times": retry_times,
                "backoff": backoff,
            }
        )

    logger.info(
        f"Parsed {len(tasks)} task(s), skipped {len(skipped_parse)} unparseable file(s)."
    )

    if args.dry_run:
        logger.info("\n--- DRY RUN ---")
        for t in tasks:
            out_name = make_output_name(t["name"], t["career"], suffix, fmt)
            prompt_preview = build_prompt(
                t["name"], t["career"], careers_map, template, adult_age
            )[:120]
            logger.info(f"  {t['path'].name} -> images/{out_name}")
            logger.info(f"    prompt: {prompt_preview}...")
        logger.info(f"\nTotal: {len(tasks)} tasks. No API calls made.")
        return

    if not tasks:
        logger.info("No tasks to process. Exiting.")
        return

    # create client
    client = ImageEditClient(
        base_url, api_key, model, size, quality, proxies=proxies,
        fallback_base_url=fallback_base_url,
        fallback_api_key=fallback_api_key,
        fallback_model=fallback_model,
    )

    # process with thread pool
    records = []
    for i, t in enumerate(tasks, 1):
        logger.info(f"[{i}/{len(tasks)}] {t['path'].name}")

    if concurrency <= 1:
        for t in tasks:
            r = process_one(
                t, client, careers_map, template, adult_age, suffix, fmt, skip_existing, logger, size
            )
            records.append(r)
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {
                pool.submit(
                    process_one,
                    t,
                    client,
                    careers_map,
                    template,
                    adult_age,
                    suffix,
                    fmt,
                    skip_existing,
                    logger,
                    size,
                ): t
                for t in tasks
            }
            for future in as_completed(futures):
                try:
                    r = future.result()
                    records.append(r)
                except Exception as e:
                    t = futures[future]
                    logger.error(f"[EXCEPTION] {t['path'].name}: {e}")
                    records.append(
                        {
                            "name": t["name"],
                            "career": t["career"],
                            "gender": t.get("gender", ""),
                            "input_file": str(t["path"]),
                            "output_file": "",
                            "status": "failed",
                            "error": str(e),
                            "prompt": build_prompt(t["name"], t["career"], careers_map, template, adult_age),
                            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        }
                    )

    # sort records by name for consistent output
    records.sort(key=lambda r: (r.get("name", ""), r.get("career", "")))

    # write outputs
    write_manifest(records, output_dir)
    write_failed(records, output_dir)

    ppt_path = None
    if not args.no_ppt:
        ppt_name = args.ppt_name or resolve_value(None, "ppt.filename", "kid-career-portraits.pptx")
        try:
            ppt_path = build_comparison_ppt(records, output_dir, ppt_name)
            if ppt_path:
                logger.info(f"PPTX:   {ppt_path}")
            else:
                logger.warning("PPTX:   skipped because no successful image pair exists")
        except Exception as e:
            logger.error(f"PPTX generation failed: {e}")
            if args.publish_lark:
                raise

    lark_result_path = None
    if args.publish_lark:
        if not ppt_path:
            print("ERROR: --publish-lark requires a generated PPTX. Remove --no-ppt or fix PPT generation.", file=sys.stderr)
            sys.exit(1)
        lark_name = args.lark_name or resolve_value(None, "lark.name", "儿童未来职业照")
        lark_result_path = output_dir / "lark_publish_result.json"
        try:
            publish_to_lark(
                output_dir / "manifest.json",
                ppt_path,
                lark_name,
                args.lark_folder_token or resolve_value(None, "lark.folder_token", None),
                args.public_share,
                lark_result_path,
            )
            logger.info(f"Lark:   {lark_result_path}")
        except Exception as e:
            logger.error(f"Lark publish failed: {e}")
            raise

    write_report(records, output_dir, ppt_path=ppt_path, lark_result_path=lark_result_path)

    # summary
    total = len(records)
    success = sum(1 for r in records if r["status"] == "success")
    skipped = sum(1 for r in records if r["status"] == "skipped")
    failed = sum(1 for r in records if r["status"] == "failed")

    logger.info("\n" + "=" * 60)
    logger.info(f"DONE. Total: {total}  Success: {success}  " f"Skipped: {skipped}  Failed: {failed}")
    logger.info(f"Report: {output_dir / 'report.md'}")
    if ppt_path:
        logger.info(f"PPTX:   {ppt_path}")
    if lark_result_path:
        logger.info(f"Lark:   {lark_result_path}")
    logger.info("=" * 60)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
