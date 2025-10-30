#!/usr/bin/env python3
"""
Convert all images in a dataset to JPEG and update metadata (parallel + resumable).

Features:
- Converts or copies images to JPEG
- Organizes output images into subdirectories by first two chars of image_id
- Updates JSONL metadata with new paths, sizes, and dimensions
- Removes keys: source_type, source_ref, original_mime
- Supports raster and vector formats (SVG, PNG, WEBP, GIF, HEIC, AVIF, etc.)
- Adds resume, idempotency, and parallel processing
"""

import json
import shutil
import mimetypes
from pathlib import Path
from io import BytesIO
from PIL import Image
from tqdm import tqdm
from concurrent.futures import ProcessPoolExecutor, as_completed
import pillow_avif


SUPPORTED_IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif",
    ".gif", ".svg", ".heic", ".heif", ".avif"
}

VECTOR_FORMATS = {".svg", ".ai", ".eps"}


# ------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------
def detect_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path)
    return mime or "application/octet-stream"


def is_supported_image(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_IMAGE_EXTS


def convert_to_jpg(src_path: Path, dst_path: Path) -> bool:
    try:
        with Image.open(src_path) as img:
            if getattr(img, "is_animated", False):
                img.seek(0)

            if img.mode in ("RGBA", "LA", "P"):
                if img.mode == "P":
                    img = img.convert("RGBA")
                background = Image.new("RGB", img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[-1])
                img = background
            elif img.mode != "RGB":
                img = img.convert("RGB")

            img.save(dst_path, "JPEG", quality=95)
        return True
    except Exception as e:
        print(f"❌ Failed to convert {src_path}: {e}")
        return False


def rasterize_svg_to_jpg(src_path: Path, dst_path: Path) -> bool:
    try:
        import cairosvg
        png_bytes = cairosvg.svg2png(url=str(src_path))
        img = Image.open(BytesIO(png_bytes))
        img.convert("RGB").save(dst_path, "JPEG", quality=95)
        return True
    except ImportError:
        print(f"⚠️  Skipping SVG {src_path} (cairosvg not installed).")
        return False
    except Exception as e:
        print(f"❌ Failed to rasterize SVG {src_path}: {e}")
        return False


def safe_convert_image(src_path: Path, dst_path: Path) -> bool:
    ext = src_path.suffix.lower()

    if ext in (".jpg", ".jpeg"):
        try:
            shutil.copy2(src_path, dst_path)
            return True
        except Exception as e:
            print(f"❌ Failed to copy {src_path}: {e}")
            return False

    if ext == ".svg":
        return rasterize_svg_to_jpg(src_path, dst_path)

    return convert_to_jpg(src_path, dst_path)


def get_image_info(path: Path):
    try:
        with Image.open(path) as img:
            width, height = img.size
        size_bytes = path.stat().st_size
        return {"width": width, "height": height}, size_bytes
    except Exception as e:
        print(f"⚠️  Could not read image info for {path}: {e}")
        return None, None


# ------------------------------------------------------------
# Checkpoint helpers
# ------------------------------------------------------------
def load_processed_ids(checkpoint_path: Path) -> set[str]:
    if checkpoint_path.exists():
        with open(checkpoint_path, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()


def append_processed_id(checkpoint_path: Path, img_id: str):
    with open(checkpoint_path, "a", encoding="utf-8") as f:
        f.write(f"{img_id}\n")


# ------------------------------------------------------------
# Worker function
# ------------------------------------------------------------
def process_record(args):
    rec, image_root, new_image_root = args
    img_id = rec.get("image_id")

    if not img_id:
        return None, img_id, False

    orig_ext = rec.get("file_ext", ".jpg").lower()
    if "file_path" in rec and rec["file_path"]:
        src_img = Path(rec["file_path"])
    else:
        src_img = image_root / f"{img_id}{orig_ext}"

    if not src_img.exists():
        return None, img_id, False

    if not is_supported_image(src_img):
        return None, img_id, False

    subdir = img_id[:2]
    dst_subdir = new_image_root / subdir
    dst_subdir.mkdir(exist_ok=True)
    dst_img = dst_subdir / f"{img_id}.jpg"

    # Idempotent check: skip if destination already exists
    if dst_img.exists():
        dims, size_bytes = get_image_info(dst_img)
        rec["file_ext"] = ".jpg"
        rec["file_path"] = str(dst_img)
        if dims and size_bytes:
            rec["image_dimensions"] = dims
            rec["image_size_bytes"] = size_bytes
        rec.pop("source_type", None)
        rec.pop("source_ref", None)
        rec.pop("original_mime", None)
        return json.dumps(rec, ensure_ascii=False), img_id, True

    if not safe_convert_image(src_img, dst_img):
        return None, img_id, False

    rec["file_ext"] = ".jpg"
    rec["file_path"] = str(dst_img)
    rec.pop("source_type", None)
    rec.pop("source_ref", None)
    rec.pop("original_mime", None)

    dims, size_bytes = get_image_info(dst_img)
    if dims and size_bytes:
        rec["image_dimensions"] = dims
        rec["image_size_bytes"] = size_bytes

    return json.dumps(rec, ensure_ascii=False), img_id, True


# ------------------------------------------------------------
# Main logic with resume + parallelism
# ------------------------------------------------------------
def main(metadata_path: Path, image_root: Path, output_dir: Path, num_workers: int = 8):
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = output_dir / "processed_ids.txt"
    new_metadata_path = output_dir / "metadata_jpg.jsonl"
    new_image_root = output_dir / "images"
    new_image_root.mkdir(exist_ok=True)

    processed_ids = load_processed_ids(checkpoint_path)

    # Preload metadata
    with open(metadata_path, encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]

    records_to_process = [r for r in records if r.get("image_id") not in processed_ids]
    total = len(records_to_process)
    print(f"🟢 Resuming conversion: {len(processed_ids)} done, {total} remaining.")

    with open(new_metadata_path, "a", encoding="utf-8") as f_out:
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            futures = [
                executor.submit(process_record, (r, image_root, new_image_root))
                for r in records_to_process
            ]

            for fut in tqdm(as_completed(futures), total=total, desc="Converting", ncols=100):
                try:
                    rec_str, img_id, ok = fut.result()
                    if ok and rec_str:
                        f_out.write(rec_str + "\n")
                        append_processed_id(checkpoint_path, img_id)
                        f_out.flush()
                except Exception as e:
                    print(f"⚠️ Worker error: {e}")

    print("\n✅ Conversion complete!")
    print(f"   Metadata: {new_metadata_path}")
    print(f"   Images:   {new_image_root}")
    print(f"   Checkpoint: {checkpoint_path}")


# ------------------------------------------------------------
# Entry point
# ------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Convert all images in a dataset to JPEG format with updated metadata (parallel + resumable)."
    )
    parser.add_argument("metadata_file", type=Path, help="Input JSONL metadata file")
    parser.add_argument("image_root", type=Path, help="Root directory of original images")
    parser.add_argument("output_dir", type=Path, help="Output directory for cleaned dataset")
    parser.add_argument("--workers", type=int, default=8, help="Number of parallel workers")

    args = parser.parse_args()
    main(args.metadata_file, args.image_root, args.output_dir, args.workers)
