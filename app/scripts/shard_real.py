import argparse
import shutil
from pathlib import Path
import re
from tqdm.auto import tqdm

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.avif'}

def is_image_file(p: Path) -> bool:
    return p.suffix.lower() in IMAGE_EXTENSIONS

def extract_image_id(filename: str) -> str | None:
    stem = Path(filename).stem
    if re.match(r"^[a-f0-9]{32,}$", stem):
        return stem
    if re.match(r"^[a-zA-Z0-9_\-]{4,}$", stem):
        return stem
    return None

def main():
    parser = argparse.ArgumentParser(
        description="Reorganize a flat image directory into xx/ subdirs by image ID."
    )
    parser.add_argument(
        "--input-dir", type=Path, required=True,
        help="Flat input directory containing real image files (e.g., ./images)"
    )
    parser.add_argument(
        "--output-dir", type=Path, required=True,
        help="New output directory to create (organized as xx/filename.ext)"
    )
    args = parser.parse_args()

    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()

    if not input_dir.is_dir():
        raise ValueError(f"Input directory does not exist: {input_dir}")
    if output_dir.exists():
        raise ValueError(f"Output directory already exists: {output_dir}")

    output_dir.mkdir(parents=True, exist_ok=False)
    print(f"📁 Input: {input_dir}")
    print(f"📦 Output: {output_dir}")

    # Get list of all items to enable progress bar with total
    all_items = list(input_dir.iterdir())
    total = len(all_items)

    processed = 0
    skipped = 0

    for item in tqdm(all_items, desc="Processing images", unit="file", total=total):
        if not item.is_file() or not is_image_file(item):
            skipped += 1
            continue

        img_id = extract_image_id(item.name)
        if not img_id or len(img_id) < 2:
            tqdm.write(f"⚠️ Invalid image ID in filename: {item.name}")
            skipped += 1
            continue

        subdir = output_dir / img_id[:2]
        subdir.mkdir(parents=True, exist_ok=True)
        target_path = subdir / item.name

        try:
            shutil.copy2(item, target_path)
            processed += 1
        except Exception as e:
            tqdm.write(f"❌ Failed to copy {item.name}: {e}")
            skipped += 1

    print(f"\n✅ Done!")
    print(f"   Copied: {processed}")
    print(f"   Skipped: {skipped}")
    print(f"   Output: {output_dir}")

if __name__ == "__main__":
    main()