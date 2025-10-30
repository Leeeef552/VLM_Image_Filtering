#!/usr/bin/env python3
"""
Singapore image filter – 2-model ensemble (Mistral + InternVL)
- Uses metadata 'file_path' to locate images (absolute or relative)
- Creates symbolic links instead of copies in output folders
- Organizes images into subdirectories based on the first two characters of the image ID
- Decision rules:
    * Both 1  → ACCEPTED
    * Both 0  → REJECTED
    * Disagree → PENDING
    * Any model error → ERROR
- Paths are resolved relative to the script's directory (not the run location)
"""

import os
import base64
import json
import logging
import argparse
import re
import threading
from pathlib import Path
from typing import Tuple, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI
from dotenv import load_dotenv
from tqdm import tqdm

###############################################################################
###                         PATH & CONFIGURATION                             ###
###############################################################################

# Base directory of this script (important for path resolution)
BASE_DIR = Path(__file__).resolve().parent

MODELS = {
    "mistral": {
        "model_name": "mistralai/Mistral-Small-3.2-24B-Instruct-2506",
        "port": 8125,
        "extra_body": None,
    },
    "internvl": {
        "model_name": "Qwen/Qwen3-VL-30B-A3B-Instruct",
        "port": 8124,
        "extra_body": None,
    },
}

MODEL_KEYS = ["mistral", "Qwen"]
MAX_WORKERS = 96

load_dotenv()
clients = {
    k: OpenAI(base_url=f"http://localhost:{cfg['port']}/v1", api_key="dummy")
    for k, cfg in MODELS.items()
}

SYSTEM = """
You are a Singapore-based intelligent classifier. You will be given an image. Decide if the image contains anything uniquely identifiable to Singapore.

## Instructions:
1. Respond in the following format:
    - ## Score:
    - ## Explanation:

2. For the score, respond only 1 or 0:
    - 1 = 100% certain the image is uniquely identifiable to Singapore
    - 0 = uncertain, maybe, or definitely not Singapore related

3. For the explanation, explain briefly the reason for your score.
"""

quota_exceeded = False

# ---------------- THREAD SAFETY ---------------- #
tracker_lock = threading.Lock()
in_progress_lock = threading.Lock()
in_progress_ids = set()
# ------------------------------------------------ #

###############################################################################
###                         HELPER FUNCTIONS                                 ###
###############################################################################

def _parse_vlm_response(response_text: str) -> Tuple[int, str]:
    score_match = re.search(r"## Score:\s*(\d+)", response_text)
    expl_match = re.search(r"## Explanation:\s*(.+)", response_text, re.DOTALL)
    score = int(score_match.group(1)) if score_match else 0
    explanation = expl_match.group(1).strip() if expl_match else "No explanation provided."
    return score, explanation


def is_quota_error(error_message: str) -> bool:
    return any(k in str(error_message).lower() for k in
               ["quota", "rate limit", "exceeded", "limit exceeded",
                "insufficient quota", "rate_limit_exceeded"])


def call_vlm_model(model_key: str, img_b64: str) -> Tuple[str, int, str, bool]:
    """Call one vision-language model."""
    global quota_exceeded
    try:
        response = clients[model_key].chat.completions.create(
            model=MODELS[model_key]["model_name"],
            messages=[
                {"role": "system", "content": SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Respond with 1 if the image is relevant to Singapore, 0 if not."},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}" }},
                    ],
                },
            ],
            temperature=0.6,
            max_tokens=75,
            extra_body=MODELS[model_key]["extra_body"],
        )
        raw = response.choices[0].message.content.strip()
        score, expl = _parse_vlm_response(raw)
        return model_key, score, expl, False
    except Exception as e:
        print(f"[{model_key}] Error: {e}")
        if is_quota_error(str(e)):
            quota_exceeded = True
        return model_key, 0, "Error occurred", True


def get_all_vlm_scores(img_path: Path) -> Tuple[Dict[str, Tuple[int, str]], bool]:
    """Run all models concurrently for one image."""
    global quota_exceeded
    with open(img_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    results, has_error = {}, False

    with ThreadPoolExecutor() as exe:
        futures = {exe.submit(call_vlm_model, k, img_b64): k for k in MODEL_KEYS}
        for fut in as_completed(futures):
            key, score, expl, err = fut.result()
            results[key] = (score, expl)
            if err:
                has_error = True
            if quota_exceeded:
                break
    return results, has_error


def determine_final_result(responses: Dict[str, Tuple[int, str]], has_error: bool) -> Tuple[int, str]:
    """Decision logic."""
    if has_error:
        expls = [e for _, (_, e) in responses.items()]
        return -1, "ERROR: " + " | ".join(expls)

    scores = [s for _, (s, _) in responses.items()]
    if len(scores) != 2:
        return -1, "ERROR: missing model outputs"

    if scores[0] == scores[1] == 1:
        final = 1
    elif scores[0] == scores[1] == 0:
        final = 0
    else:
        final = 2  # disagreement → pending

    expl = " | ".join([e for _, (_, e) in responses.items()])
    return final, expl


def log_vlm_results(out_dir: Path, rec: dict, final_score: int, final_expl: str,
                    responses: Dict[str, Tuple[int, str]]):
    log_file = out_dir / "vlm_results.log"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"Image ID: {rec.get('image_id', 'unknown')}\n")
        f.write(f"Final Score: {final_score}\n")
        f.write(f"Combined Explanation: {final_expl}\n")
        for k, (s, e) in responses.items():
            f.write(f"  {MODELS[k]['model_name']}: {s} – {e}\n")
        f.write("-" * 60 + "\n")


def load_processed_images(tracker: Path) -> set:
    return set(tracker.read_text().splitlines()) if tracker.exists() else set()


def save_processed_image(tracker: Path, img_id: str):
    """Thread-safe tracker write."""
    with tracker_lock:
        with open(tracker, "a", encoding="utf-8") as f:
            f.write(f"{img_id}\n")


###############################################################################
###                IMAGE PATH RESOLUTION & LINK CREATION                     ###
###############################################################################

def resolve_image_path(rec: dict, img_dir: Path) -> Path:
    BASE_PREFIX = Path("/workspace/eefun/webscraping/filtering/")  # hardcoded base prefix
    if rec.get("file_path"):
        img_path = (BASE_PREFIX / Path(rec["file_path"])).resolve()
    else:
        img_id = rec.get("image_id", "unknown")
        img_path = (BASE_PREFIX / img_dir / f"{img_id}.jpg").resolve()
    return img_path


def create_symlink(src: Path, dst: Path):
    """Create or replace a symlink safely."""
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    os.symlink(src, dst)


###############################################################################
###                    SINGLE-IMAGE PROCESSING LOGIC                         ###
###############################################################################

def process_single_image(rec: dict, img_dir: Path, acc_dir: Path, rej_dir: Path,
                         pend_dir: Path, err_dir: Path, out_dir: Path, tracker: Path) -> Tuple[bool, dict, str]:
    """Process one image record end-to-end."""
    global quota_exceeded, in_progress_ids
    img_id = rec.get("image_id")

    if not img_id or quota_exceeded:
        return False, rec, img_id

    # Prevent duplicates across threads
    with in_progress_lock:
        if img_id in in_progress_ids:
            return False, rec, img_id
        in_progress_ids.add(img_id)

    img_path = resolve_image_path(rec, img_dir)
    if not img_path.exists():
        rec["error"] = f"Image not found: {img_path}"
        meta_file = rej_dir.parent / "metadata.jsonl"
        meta_file.parent.mkdir(parents=True, exist_ok=True)
        with open(meta_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        save_processed_image(tracker, img_id)
        with in_progress_lock:
            in_progress_ids.discard(img_id)
        print(f"⚠️ Missing image: {img_path}")
        return False, rec, img_id

    try:
        responses, has_error = get_all_vlm_scores(img_path)
        if quota_exceeded:
            return False, rec, img_id

        final_score, final_expl = determine_final_result(responses, has_error)
        rec["vlm_sg_score"] = final_score
        rec["vlm_sg_explanation"] = final_expl
        log_vlm_results(out_dir, rec, final_score, final_expl, responses)

        if has_error:
            tgt_dir, status = err_dir, "ERROR"
        elif final_score == 1:
            tgt_dir, status = acc_dir, "ACCEPTED"
        elif final_score == 0:
            tgt_dir, status = rej_dir, "REJECTED"
        elif final_score == 2:
            tgt_dir, status = pend_dir, "PENDING"
        else:
            tgt_dir, status = err_dir, "ERROR"

        # Create subdirectory based on first two characters of image ID
        subdir = img_id[:2]
        tgt_dir = tgt_dir / subdir
        tgt_dir.mkdir(parents=True, exist_ok=True)

        meta_file = tgt_dir.parent.parent / "metadata.jsonl"
        tgt_dir.parent.mkdir(parents=True, exist_ok=True)
        meta_file.parent.mkdir(parents=True, exist_ok=True)
        dest_path = tgt_dir / img_path.name
        create_symlink(img_path, dest_path)

        with open(meta_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        save_processed_image(tracker, img_id)
        with in_progress_lock:
            in_progress_ids.discard(img_id)

        print(f"[{status}] {img_id} → {dest_path}")
        return True, rec, img_id

    except Exception as e:
        logging.error(f"Processing failed {img_id}: {e}")
        err_dir.mkdir(parents=True, exist_ok=True)
        
        # Create subdirectory based on first two characters of image ID
        subdir = img_id[:2]
        err_dir = err_dir / subdir
        err_dir.mkdir(parents=True, exist_ok=True)
        
        dest_path = err_dir / img_path.name
        create_symlink(img_path, dest_path)
        rec.update({"vlm_sg_score": -1, "vlm_sg_explanation": str(e), "error": str(e)})
        meta_file = err_dir.parent.parent / "metadata.jsonl"
        meta_file.parent.mkdir(parents=True, exist_ok=True)
        with open(meta_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        save_processed_image(tracker, img_id)
        with in_progress_lock:
            in_progress_ids.discard(img_id)
        return False, rec, img_id


###############################################################################
###                         BATCH ENTRY POINT                                ###
###############################################################################

def batch_process_with_vlm_filter(images_dir: Path, metadata_file: Path, output_dir: Path):
    """Main pipeline for all images."""
    accepted_dir = output_dir / "accepted" / "images"
    rejected_dir = output_dir / "rejected" / "images"
    pending_dir  = output_dir / "pending"  / "images"
    error_dir    = output_dir / "error"    / "images"
    tracker_file = output_dir / "processed_tracker.txt"

    for d in (accepted_dir, rejected_dir, pending_dir, error_dir, output_dir):
        d.mkdir(parents=True, exist_ok=True)

    processed = load_processed_images(tracker_file)

    # Load all JSONL records
    records = []
    with metadata_file.open(encoding="utf-8") as f:
        for line_no, raw in enumerate(f, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"⚠️ Bad JSONL line {line_no}: {e} – skipped")

    todo = [r for r in records if r.get("image_id") not in processed]
    skipped = len(records) - len(todo)
    print(f"Skipped {skipped} already processed images")
    print(f"Processing {len(todo)} images with {MAX_WORKERS} workers")

    success = failed = 0
    if todo:
        args_list = [(r, images_dir, accepted_dir, rejected_dir, pending_dir, error_dir, output_dir, tracker_file)
                     for r in todo]
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as exe:
            futures = {exe.submit(process_single_image, *a): a for a in args_list}
            for fut in tqdm(as_completed(futures), total=len(futures), unit="img"):
                if quota_exceeded:
                    print("\n⚠️ Quota exceeded – cancelling remaining jobs")
                    for f in futures:
                        if not f.done():
                            f.cancel()
                    break
                try:
                    ok, _, _ = fut.result()
                    success += bool(ok)
                    failed  += not ok
                except Exception as e:
                    failed += 1
                    logging.error(f"Future failed: {e}")

    print("\n" + "=" * 60)
    if quota_exceeded:
        print("❌ PROCESSING STOPPED – quota exceeded")
    print(f"Success: {success}   Failed: {failed}   Total: {success + failed}   Skipped: {skipped}")
    print("=" * 60)


###############################################################################
###                              CLI ENTRY                                   ###
###############################################################################

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Singapore image filter – 2-model ensemble (Mistral + InternVL)")
    parser.add_argument("images_dir",    type=Path, help="Base directory for image paths (used to resolve relative file_path)")
    parser.add_argument("metadata_file", type=Path, help="JSONL metadata file")
    parser.add_argument("output_dir",    type=Path, help="Output directory")
    args = parser.parse_args()

    cwd = Path.cwd()
    images_dir = args.images_dir if args.images_dir.is_absolute() else (cwd / args.images_dir).resolve()
    metadata_file = args.metadata_file if args.metadata_file.is_absolute() else (cwd / args.metadata_file).resolve()
    output_dir = args.output_dir if args.output_dir.is_absolute() else (cwd / args.output_dir).resolve()

    print(f"\n📁 Using paths:")
    print(f"  Images directory : {images_dir}")
    print(f"  Metadata file    : {metadata_file}")
    print(f"  Output directory : {output_dir}\n")

    batch_process_with_vlm_filter(images_dir, metadata_file, output_dir)