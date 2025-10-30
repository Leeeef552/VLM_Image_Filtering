#!/usr/bin/env python3
"""
Singapore image filter – 4-model ensemble
≥ 2 positive votes required for acceptance
"""
import os
import base64
import json
import logging
import argparse
import shutil
import re
from pathlib import Path
from typing import Tuple, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI
from dotenv import load_dotenv
from tqdm import tqdm
import time

###############################################################################
###                         MODEL CONFIGURATION                              ###
###############################################################################
MODELS = {
    "mistral": {
        "model_name": "mistralai/Mistral-Small-3.2-24B-Instruct-2506",
        "port": 8124,
        "extra_body": None,
    },
    "qwen": {
        "model_name": "Qwen/Qwen2.5-VL-72B-Instruct-AWQ",
        "port": 8125,
        "extra_body": None,
    },
    "glm": {
        "model_name": "zai-org/GLM-4.1V-9B-Base",
        "port": 8123,
        "extra_body": None,
    },
    "internvl": {
        "model_name": "OpenGVLab/InternVL3_5-30B-A3B-Instruct",
        "port": 8122,
        "extra_body": None,
    },
}

MODEL_KEYS = ["mistral", "qwen", "glm", "internvl"]  # edit here to reduce ensemble
MAX_WORKERS = 64
VLM_MAX_RETRIES = 2  # total attempts = 3 (initial + 2 retries)

load_dotenv()
clients = {
    k: OpenAI(base_url=f"http://localhost:{cfg['port']}/v1", api_key="dummy")
    for k, cfg in MODELS.items()
}

SYSTEM = """
You are a vision-language data curator focused on Singapore. You will be given an image that may or may not be related to Singapore. Your task is to decide how **useful** this image would be for training a vision-language model to recognize Singapore-related **scenes, objects, entities, or cultural/semantic cues**.

## Instructions:
1. Respond in the following format:
    - ## Score:
    - ## Explanation:

2. For the score, respond with an integer from 1 to 5:
    - 5 = Extremely useful – clearly shows distinctive Singapore-specific visuals 
          (e.g., Merlion, MRT signage, HDB blocks, SMRT logo, bilingual signboards)
    - 4 = Very useful – strong Singapore context or multiple recognizable local elements
    - 3 = Moderately useful – some Singapore cues but partially generic or unclear
    - 2 = Slightly useful – weak or indirect Singapore cues
    - 1 = Not useful – no meaningful Singapore-related visual or semantic content

3. When deciding usefulness:
    - Focus on **visual recognizability** — whether the image helps a model *see* what Singapore looks like, or captures a Singapore specific scene or cultural/semantic cues.
    - Consider both:
        - **Object/entity recognitions:** e.g., MRT, HDB flats, ERP gantries, hawker stalls, SMRT or SingPost logos.
        - **Cultural/contextual portrayals:** e.g., long queues (queue culture), bilingual signage, orderly streets, public housing layouts.
    - **Text alone (e.g., “Orchard Road”, “Marina Bay”) is not useful** unless it is accompanied by **visual or contextual cues** that indicate Singapore (e.g., a signboard or MRT station background).
    - Ignore aesthetic or artistic quality — focus purely on usefulness for recognition training.

4. Keep the explanation concise and factual. 
    - Mention which specific visual or textual elements influenced your score (e.g., “SMRT logo and MRT train visible – strong Singapore cue or “Only text ‘Orchard Road’ on plain background – no visual context”).
"""

quota_exceeded = False

###############################################################################
###                         HELPER FUNCTIONS                                 ###
###############################################################################
def _parse_vlm_response(response_text: str) -> Tuple[int, str]:
    score_match = re.search(r"## Score:\s*(\d+)", response_text)
    expl_match  = re.search(r"## Explanation:\s*(.+)", response_text, re.DOTALL)
    score = int(score_match.group(1)) if score_match else 0
    explanation = expl_match.group(1).strip() if expl_match else "No explanation provided."
    return score, explanation


def is_quota_error(error_message: str) -> bool:
    return any(k in str(error_message).lower() for k in
               ["quota", "rate limit", "exceeded", "limit exceeded",
                "insufficient quota", "rate_limit_exceeded"])


def call_vlm_model(model_key: str, img_b64: str, max_retries: int = 3) -> Tuple[str, int, str, bool]:
    global quota_exceeded
    for attempt in range(max_retries + 1):
        try:
            response = clients[model_key].chat.completions.create(
                model=MODELS[model_key]["model_name"],
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Please evaluate the image according to the instructions above."},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                        ],
                    },
                ],
                temperature=0.6,
                max_tokens=75,
                extra_body=MODELS[model_key]["extra_body"],
            )
            raw = response.choices[0].message.content.strip()
            score, expl = _parse_vlm_response(raw)
            # If parsing yields score=0, consider it a soft failure and retry?
            # Optional: only retry if score == 0 and no explanation
            if score == 0 and expl == "No explanation provided.":
                if attempt < max_retries:
                    wait = (2 ** attempt) + 0.1  # exponential backoff + jitter
                    print(f"[{model_key}] Got empty response, retrying in {wait:.1f}s (attempt {attempt+1}/{max_retries})")
                    time.sleep(wait)
                    continue
            return model_key, score, expl, False

        except Exception as e:
            error_str = str(e)
            print(f"[{model_key}] Attempt {attempt+1}/{max_retries+1} failed: {e}")
            if is_quota_error(error_str):
                quota_exceeded = True
                return model_key, 0, "Quota exceeded", True
            if attempt < max_retries:
                wait = (2 ** attempt) + 0.1  # e.g., 1.1s, 2.1s, 4.1s
                time.sleep(wait)
            else:
                return model_key, 0, f"Failed after {max_retries+1} attempts: {error_str}", True
    # Should not reach here
    return model_key, 0, "Unexpected exit", True


def get_all_vlm_scores(img_path: Path) -> Tuple[Dict[str, Tuple[int, str]], bool]:
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
    if has_error:
        expls = [e for _, (_, e) in responses.items()]
        return -1, "ERROR: " + " | ".join(expls)

    # Only consider valid scores (≥1 and ≤5); though errors should already be caught
    valid_scores = [s for s in [score for score, _ in responses.values()] if 1 <= s <= 5]
    
    if not valid_scores:
        # Fallback: all models failed silently? Treat as error
        return -1, "ERROR: No valid scores from models"

    avg_score = sum(valid_scores) / len(valid_scores)
    # Keep final_score as float or round if you prefer int
    # Here we return float for precision; adjust if you need int
    final_score = round(avg_score, 2)  # or just avg_score
    expl = " | ".join([e for _, (_, e) in responses.items()])
    return final_score, expl


def vlm_sg_score(rec: dict, img_path: Path) -> Tuple[int, str, bool]:
    responses, has_error = get_all_vlm_scores(img_path)
    final_score, final_expl = determine_final_result(responses, has_error)
    return final_score, final_expl, has_error


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
    with open(tracker, "a", encoding="utf-8") as f:
        f.write(f"{img_id}\n")

###############################################################################
###                    SINGLE-IMAGE WRAPPER (CONCURRENT)                     ###
###############################################################################
def process_single_image_wrapper(args):
    global quota_exceeded
    if quota_exceeded:
        return False, None, None
    rec, img_dir, acc_dir, rej_dir, err_dir, out_dir, tracker = args
    img_id = rec.get("image_id")
    if not img_id:
        return False, rec, None
    img_path = img_dir / img_id[:2] / f"{img_id}.jpg"
    if not img_path.exists():
        rec["error"] = "Image file not found"
        meta = rej_dir.parent / "metadata.jsonl"
        meta.parent.mkdir(parents=True, exist_ok=True)
        with open(meta, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        save_processed_image(tracker, img_id)
        return False, rec, img_id

    try:
        responses, has_error = get_all_vlm_scores(img_path)
        if quota_exceeded:
            return False, rec, img_id
        final_score, final_expl = determine_final_result(responses, has_error)
        rec["vlm_sg_score"] = final_score
        rec["vlm_sg_explanation"] = final_expl
        log_vlm_results(out_dir, rec, final_score, final_expl, responses)

        if final_score == -1:
            tgt_dir, meta_file, status = err_dir, err_dir.parent / "metadata.jsonl", "ERROR"
        else:
            tgt_dir, meta_file, status = acc_dir, acc_dir.parent / "metadata.jsonl", "ACCEPTED"

        tgt_dir.mkdir(parents=True, exist_ok=True)
        meta_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(img_path, tgt_dir / img_path.name)
        with open(meta_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        save_processed_image(tracker, img_id)
        print(f"[{status}] {img_id}")
        return True, rec, img_id

    except Exception as e:
        logging.error(f"Processing failed {img_id}: {e}")
        err_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(img_path, err_dir / img_path.name)
        rec.update({"vlm_sg_score": -1, "vlm_sg_explanation": str(e), "error": str(e)})
        meta_file = err_dir.parent / "metadata.jsonl"
        meta_file.parent.mkdir(parents=True, exist_ok=True)
        with open(meta_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        save_processed_image(tracker, img_id)
        return False, rec, img_id

###############################################################################
###                         BATCH ENTRY POINT                                ###
###############################################################################
def batch_process_with_vlm_filter(images_dir: Path, metadata_file: Path, output_dir: Path):
    global quota_exceeded
    accepted_dir   = output_dir / "accepted" / "images"
    rejected_dir   = output_dir / "rejected" / "images"
    error_dir      = output_dir / "error"    / "images"
    tracker_file   = output_dir / "processed_tracker.txt"
    for d in (accepted_dir, error_dir, output_dir):
        d.mkdir(parents=True, exist_ok=True)

    processed = load_processed_images(tracker_file)

    # Read ALL valid JSONL lines from metadata file
    records = []
    with metadata_file.open(encoding="utf-8") as f:
        for line_no, raw in enumerate(f, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"⚠️  Bad JSONL line {line_no}: {e} – skipped")

    todo      = [r for r in records if r.get("image_id") not in processed]
    skipped   = len(records) - len(todo)
    if skipped:
        print(f"Skipped {skipped} already processed images")
    print(f"Processing {len(todo)} images with {MAX_WORKERS} workers")

    success = failed = 0
    if todo:
        args_list = [(r, images_dir, accepted_dir, rejected_dir, error_dir, output_dir, tracker_file)
                    for r in todo]
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as exe:
            futures = {exe.submit(process_single_image_wrapper, a): a for a in args_list}
            for fut in tqdm(as_completed(futures), total=len(futures), unit="img"):
                if quota_exceeded:
                    print("\n⚠️  Quota exceeded – cancelling remaining jobs")
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

    print("\n" + "="*60)
    if quota_exceeded:
        print("❌ PROCESSING STOPPED – quota exceeded")
    print(f"Success: {success}   Failed: {failed}   Total: {success+failed}   Skipped: {skipped}")
    print("="*60)

###############################################################################
###                              CLI                                         ###
###############################################################################
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Singapore image filter – 4-model ensemble")
    parser.add_argument("images_dir",    type=Path, help="Directory containing images")
    parser.add_argument("metadata_file", type=Path, help="JSONL metadata file")
    parser.add_argument("output_dir",    type=Path, help="Output directory")
    args = parser.parse_args()
    batch_process_with_vlm_filter(args.images_dir, args.metadata_file, args.output_dir)