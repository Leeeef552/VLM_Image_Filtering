import argparse
import json
import shutil
import logging
import logging.handlers
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import cv2
import numpy as np
from PIL import Image
from tqdm import tqdm
from openai import OpenAI
import base64
from typing import Tuple
from func_timeout import func_timeout, FunctionTimedOut
import functools


# -----------------------------------------------------------------------------
#                  Set Up / Filtering parameters and thresholds
# -----------------------------------------------------------------------------

LOG_FMT = "%(asctime)s | %(levelname)-8s | %(funcName)s | %(message)s"

# Suppress verbose third-party loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai._base_client").setLevel(logging.WARNING)

logging.basicConfig(level=logging.INFO, format=LOG_FMT)
logger = logging.getLogger("filter")

MIN_SHORT_EDGE       = 256
MIN_FILE_SIZE_B      = 5 * 1024
EDGE_DENSITY_THRESH  = 0.02

# -----------------------------------------------------------------------------
#                       Pre-compiled NSFW regex objects
# -----------------------------------------------------------------------------
NSFW_REGEX_WEIGHTS = {
    r"\bporn\b": 8, r"\bsex\b": 6, r"\bnude\b": 6, r"\bhentai\b": 7,
    r"\bfuck\b": 9, r"\bpenis\b": 8, r"\bvagina\b": 8, r"\blowjob\b": 8,
    r"\bdick\b": 8, r"\bpussy\b": 8, r"\banal\b": 7, r"\bcum\b": 7,
    r"\bcumshot\b": 9, r"\bhandjob\b": 8, r"\bmasturbat\b": 8,
    r"\berotic\b": 6, r"\bnsfw\b": 4, r"\badult\b": 1.5,
}
NSFW_REGEX_THRESHOLD = 10.0
NSFW_REGEXES = {re.compile(k, re.I): v for k, v in NSFW_REGEX_WEIGHTS.items()}


# -----------------------------------------------------------------------------
#                     Pre-compiled Singapore regex objects
# -----------------------------------------------------------------------------
SINGAPORE_KEYWORDS = [
    "singapore", "sg", "🇸🇬", "merlion", "sentosa", "orchard road",
    "marina bay", "raffles place", "gardens by the bay", "mrt", "ntu", "nus",
    "dbs", "ocbc", "uob", "hdb", "cpf", "singpass", "grab", "shopee",
]
SINGAPORE_REGEX = re.compile("|".join(map(re.escape, SINGAPORE_KEYWORDS)), re.I)

# -----------------------------------------------------------------------------
#                                LLM variables
# -----------------------------------------------------------------------------
TEXT_MODEL         = "google/gemma-3-12b-it"
TEXT_MODEL_BASE_URL = "http://localhost:8124/v1"
VISION_MODEL         = "Qwen/Qwen2.5-VL-72B-Instruct-AWQ"
VISION_MODEL_BASE_URL = "http://localhost:8125/v1"

MAX_WORKERS   = 72

text_client = OpenAI(base_url=TEXT_MODEL_BASE_URL, api_key="dummy")
vision_client = OpenAI(base_url=VISION_MODEL_BASE_URL, api_key="dummy")

# -----------------------------------------------------------------------------
#                              Progress tracking
# -----------------------------------------------------------------------------

PROCESSED_IDS_FILE = None

# -----------------------------------------------------------------------------
#                      TEXT Based Helpers for SG and NSFW
# -----------------------------------------------------------------------------

def gather_text(rec: dict) -> str:
    parts = [
        rec.get("page_url", ""),
        rec.get("page_title", ""),
        rec.get("page_summary", ""),
        rec.get("raw_caption", ""),
    ]
    return " ".join(parts).lower()


def quick_nsfw_regex(rec: dict) -> bool:
    hay = gather_text(rec)
    score = sum(len(rx.findall(hay)) * w for rx, w in NSFW_REGEXES.items())
    ok = score < NSFW_REGEX_THRESHOLD
    logger.debug("quick_nsfw_regex: %s (score=%.2f)", "pass" if ok else "fail", score)
    return ok


def llm_nsfw_score(rec: dict) -> int:
    text = gather_text(rec)[:4000]
    try:
        response = text_client.chat.completions.create(
            model=TEXT_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a classifier. Reply only 0, 1 or 2.\n"
                        "0 = definitely SAFE / not NSFW.\n"
                        "1 = uncertain / not enough context.\n"
                        "2 = 100 % certain it IS NSFW."
                    ),
                },
                {"role": "user", "content": text},
            ],
            temperature=0,
            max_tokens=1,
        )
        score = int(response.choices[0].message.content.strip())
        logger.debug("llm_nsfw_score: %d for image_id=%s", score, rec["image_id"])
        return score
    except Exception as e:
        logger.warning("llm_nsfw_score failed: %s; treating as safe", e)
        return 0


def quick_sg_regex(rec: dict) -> bool:
    ok = bool(SINGAPORE_REGEX.search(gather_text(rec)))
    logger.debug("quick_sg_regex: %s for image_id=%s", "pass" if ok else "fail", rec["image_id"])
    return ok


def llm_sg_score(rec: dict) -> int:
    text = gather_text(rec)[:4000]
    try:
        response = text_client.chat.completions.create(
            model=TEXT_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a classifier. Reply only 0, 1 or 2.\n"
                        "0 = definitely NOT related to Singapore.\n"
                        "1 = uncertain / not enough context.\n"
                        "2 = 100 % certain it IS related to Singapore."
                    ),
                },
                {"role": "user", "content": text},
            ],
            temperature=0,
            max_tokens=1,
        )
        score = int(response.choices[0].message.content.strip())
        logger.debug("llm_sg_score: %d for image_id=%s", score, rec["image_id"])
        return score
    except Exception as e:
        logger.warning("llm_sg_score failed: %s; treating as uncertain", e)
        return 1

# -----------------------------------------------------------------------------
#                      IMAGE Based Helpers for SG and NSFW
# -----------------------------------------------------------------------------

def passes_resolution(path: Path) -> bool:
    try:
        with Image.open(path) as im:
            w, h = im.size
            ok = min(w, h) >= MIN_SHORT_EDGE
            logger.debug("passes_resolution: %s for %s", "pass" if ok else "fail", path.name)
            return ok
    except Exception as e:
        logger.debug("passes_resolution failed: %s", e)
        return False


def passes_size(path: Path) -> bool:
    try:
        ok = path.stat().st_size >= MIN_FILE_SIZE_B
        logger.debug("passes_size: %s for %s", "pass" if ok else "fail", path.name)
        return ok
    except Exception as e:
        logger.debug("passes_size failed: %s", e)
        return False


def passes_edge_density(path: Path) -> bool:
    try:
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return False
        edges = cv2.Canny(img, 50, 150)
        density = edges.sum() / 255.0 / (img.shape[0] * img.shape[1])
        ok = density >= EDGE_DENSITY_THRESH
        logger.debug("passes_edge_density: %.4f %s for %s", density, "pass" if ok else "fail", path.name)
        return ok
    except Exception as e:
        logger.debug("passes_edge_density failed: %s", e)
        return False


def _parse_vlm_response(response_text: str) -> Tuple[int, str]:
    """
    Parses the response string to extract score and explanation.
    Expected format:
        ## Score: 1
        ## Explanation: The image shows a Merlion statue.
    """
    score_match = re.search(r"## Score:\s*(-?\d+)", response_text)
    expl_match = re.search(r"## Explanation:\s*(.+)", response_text, re.DOTALL)

    score = int(score_match.group(1)) if score_match else 0
    explanation = expl_match.group(1).strip() if expl_match else "No explanation provided."

    return score, explanation


@functools.lru_cache(maxsize=None)
def _timed(func, timeout_s):
    @functools.wraps(func)
    def wrapper(*args, **kw):
        return func_timeout(timeout_s, func, args=args, kwargs=kw)
    return wrapper


def _load_processed_ids(processed_ids_file: Path) -> set:
    if processed_ids_file.exists():
        with open(processed_ids_file, "r") as f:
            return set(line.strip() for line in f)
    return set()

def vlm_sg_score(rec: dict, img_path: Path) -> Tuple[int, str]:
    """
    Returns (score, explanation)
    - 1 = 100% certain Singapore-related
    - 0 = uncertain
    - -1 = definitely NOT Singapore related
    """
    # Check if image exists first
    if not img_path.exists():
        return 0, "Image file not found."

    SYSTEM = """
        You are a Singapore based intelligent classifier. You will be given an image plus textual hints scraped with it. Decide if the image contains anything uniquely identifiable to Singapore.

        ## Instructions:
        1. Respond in the following format: 
            - ## Score:   
            - ## Explanation: 

        2. For the score, respond only 1, 0, or -1
            - 1 = 100 certain the image is uniquely identifiable to Singapore
            - 0 = uncertain, not sure, maybe
            - -1 = definitely NOT Singapore related 

        3. For the explanation, explain briefly the reason for your score, make sure it is short and brief. 
    """

    try:
        with open(img_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("utf-8")

        response = vision_client.chat.completions.create(
            model=VISION_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"{gather_text(rec)[:2000]}"
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
                        }
                    ],
                },
            ],
            temperature=0,
            max_tokens=100,
        )

        raw_response = response.choices[0].message.content.strip()
        score, explanation = _parse_vlm_response(raw_response)

        logger.debug("vlm_sg_score: %d for image_id=%s", score, rec["image_id"])
        return score, explanation

    except Exception as e:
        logger.warning("vlm_sg_score failed: %s; treating as uncertain (0)", e)
        return 0, "Vision model error or invalid response."


###############################################################################
###                           Main Entry Function                           ###
###############################################################################

def find_image_file(img_dir: Path, img_id: str) -> Path | None:
    sub_dir = img_id[:2]
    base_path = img_dir / sub_dir / img_id
    extensions = [".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".bmp"]
    for ext in extensions:
        path = base_path.with_suffix(ext)
        if path.exists():
            return path
    return None


def _inner_process(rec, img_dir, accepted_img_dir, rejected_img_dir):
    img_id = rec["image_id"]
    logger.debug("Started processing image_id=%s", img_id)

    img_path = find_image_file(img_dir, img_id)
    if not img_path:
        rec["reject_reason"] = "missing"
        return "rejected", rec, img_path

    checks = [
        ("resolution",   not passes_resolution(img_path)),
        ("size",         not passes_size(img_path)),
        ("edge_density", not passes_edge_density(img_path)),
        ("nsfw_regex",   not quick_nsfw_regex(rec)),
        ("nsfw_llm",     llm_nsfw_score(rec) >= 2),
        ("sg_text_llm",  not quick_sg_regex(rec) and llm_sg_score(rec) == 0),
    ]

    for reason, failed in checks:
        if failed:
            rec["reject_reason"] = reason
            return "rejected", rec, img_path

    v_score, v_explanation = vlm_sg_score(rec, img_path)
    logger.debug(f"VLM score for {rec['image_id']}: {v_score}")
    if v_score != 1:
        rec["reject_reason"] = "vision_sg"
        rec["reject_explanation"] = v_explanation
        logger.debug(f"Rejected by VLM: {rec['image_id']} - {v_explanation}")
        return "rejected", rec, img_path

    logger.debug(f"Accepted by VLM: {rec['image_id']}")
    return "accepted", rec, img_path

    
def process_one(arg_t):
    rec, img_dir, accepted_img_dir, rejected_img_dir = arg_t
    img_id = rec["image_id"]
    sub_dir = img_id[:2]
    img_path = img_dir / sub_dir / f"{img_id}.jpg"

    try:
        result = func_timeout(150, _inner_process, args=arg_t)
        return result  # This will be (status, rec, img_path)
    except FunctionTimedOut:
        logger.warning("image_id=%s timed out after 150 s", img_id)

        reason = "timeout"
        rec["reject_reason"] = reason
        return "rejected", rec, img_path  # Ensure 3 values returned
    except Exception as e:
        logger.error("Unexpected error processing image_id=%s: %s", img_id, e)
        rec["reject_reason"] = "error"
        return "rejected", rec, img_path  # Ensure 3 values returned


###############################################################################
###                                  Main                                   ###
###############################################################################

def main():
    parser = argparse.ArgumentParser(
        description="Filter images based on NSFW, Singapore relevance, resolution, size, and edge density using LLMs and CV."
    )
    parser.add_argument(
        "images_dir",
        help="Directory containing downloaded images (named by image_id.jpg)"
    )   
    parser.add_argument(
        "metadata_jsonl",
        help="Path to input metadata file (JSONL format)"
    )
    parser.add_argument(
        "output_dir",
        help="Directory where filtered results will be saved (created if missing)."
    )

    args = parser.parse_args()

    img_dir   = Path(args.images_dir).expanduser().resolve()
    meta_in   = Path(args.metadata_jsonl).expanduser().resolve()
    out_dir   = Path(args.output_dir).expanduser().resolve()

    # 👇 CRITICAL: Create root output directory if missing
    out_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"📁 Using output directory: {out_dir}")

    accepted_dir = out_dir / "accepted"
    rejected_dir = out_dir / "rejected"

    accepted_img = accepted_dir / "images"
    rejected_img = rejected_dir / "images"

    accepted_img.mkdir(parents=True, exist_ok=True)
    rejected_img.mkdir(parents=True, exist_ok=True)

    accepted_meta = accepted_dir / "metadata.jsonl"
    rejected_meta = rejected_dir / "metadata.jsonl"

    # Set up processed IDs file
    global PROCESSED_IDS_FILE
    PROCESSED_IDS_FILE = out_dir / "processed_ids.txt"

    # Load previously processed IDs
    print("Loading previously processed IDs...")
    processed_ids = _load_processed_ids(PROCESSED_IDS_FILE)
    print(f"✅ Found {len(processed_ids)} previously processed records.")

    print("Loading metadata …")
    with meta_in.open("rt", encoding="utf-8") as f:
        records = [json.loads(line) for line in f]

    print(f"✅ Loaded {len(records)} records")

    # Filter out already processed records
    print("Checking for already processed records...")
    records = [
        rec for rec in records
        if rec["image_id"] not in processed_ids
    ]
    print(f"🔄 Resuming with {len(records)} unprocessed records.")

    def write_result(status: str, rec: dict):
        target_meta = accepted_meta if status == "accepted" else rejected_meta
        with target_meta.open("at", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        # Log this image as processed
        if PROCESSED_IDS_FILE:
            with open(PROCESSED_IDS_FILE, "a", encoding="utf-8") as f:
                f.write(rec["image_id"] + "\n")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(process_one, (rec, img_dir, accepted_img, rejected_img)): rec
            for rec in records
        }

        for fut in tqdm(as_completed(futures), total=len(futures), desc="🔍 Filtering images"):
            try:
                status, rec, img_path = fut.result()
            except Exception as e:
                logger.error("Error processing future: %s", e)
                continue

            # Write metadata
            write_result(status, rec)

            # -----------------------------------------------------------------
            # 🔧 Updated logic to create subdirectories by first two hash chars
            # -----------------------------------------------------------------
            reason = rec.get("reject_reason", "accepted")
            subdir = rec["image_id"][:2]  # <-- NEW

            if status == "accepted":
                target_dir = accepted_img / subdir
            else:
                target_dir = rejected_img / reason / subdir

            target_dir.mkdir(parents=True, exist_ok=True)

            if img_path and img_path.exists():
                try:
                    symlink_path = target_dir / img_path.name
                    if not symlink_path.exists():
                        symlink_path.symlink_to(img_path.resolve())
                        logger.debug(f"Created symlink: {symlink_path} -> {img_path}")
                    else:
                        logger.debug(f"Symlink already exists: {symlink_path}")
                except Exception as e:
                    logger.warning("Failed to symlink image %s: %s", rec["image_id"], e)
            else:
                logger.warning(f"Image file does not exist: {img_path}")

    print("\n🎉 Finished filtering!")
    # Count images recursively
    accepted_count = len(list(accepted_img.rglob("*.jpg")))
    rejected_count = len(list(rejected_img.rglob("*.jpg")))
    print(f"   Accepted: {accepted_count}")
    print(f"   Rejected: {rejected_count}")
    print(f"   Output: {out_dir}")

if __name__ == "__main__":
    main()