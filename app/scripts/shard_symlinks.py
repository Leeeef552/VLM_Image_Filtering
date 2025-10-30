import argparse
import shutil
from pathlib import Path
import re

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.avif'}

def is_image_file(p: Path) -> bool:
    return p.suffix.lower() in IMAGE_EXTENSIONS

def extract_image_id(filename: str) -> str | None:
    stem = Path(filename).stem
    if re.match(r"^[a-f0-9]{32,}$", stem):  # assume MD5/SHA-like hash
        return stem
    if re.match(r"^[a-zA-Z0-9_\-]{4,}$", stem):
        return stem
    return None

def main():
    parser = argparse.ArgumentParser(description="Reorganize filter2.py symlink output into real files in xx/ subdirs.")
    parser.add_argument("--input-dir", type=Path, required=True, help="Flat input dir with symlinks (e.g., accepted/images)")
    parser.add_argument("--new-base", type=str, required=True, help="New base path where real images live (with subdirs)")
    parser.add_argument("--output-dir", type=Path, required=True, help="New output dir to create (organized with xx/ subdirs)")
    args = parser.parse_args()

    input_dir = args.input_dir.resolve()
    new_base = Path(args.new_base).resolve()
    output_dir = args.output_dir.resolve()

    if not input_dir.is_dir():
        raise ValueError(f"Input dir does not exist: {input_dir}")
    if not new_base.is_dir():
        raise ValueError(f"New base image dir does not exist: {new_base}")
    if output_dir.exists():
        raise ValueError(f"Output dir already exists: {output_dir}")

    output_dir.mkdir(parents=True, exist_ok=False)
    print(f"📁 Input: {input_dir}")
    print(f"📂 New base images: {new_base}")
    print(f"📦 Output: {output_dir}")

    processed = 0
    skipped = 0

    for item in input_dir.iterdir():
        if not item.is_symlink() or not is_image_file(item):
            skipped += 1
            continue

        img_id = extract_image_id(item.name)
        if not img_id or len(img_id) < 2:
            print(f"⚠️ Invalid image ID in filename: {item.name}")
            skipped += 1
            continue

        # Construct expected path in new base
        expected_path = new_base / img_id[:2] / item.name
        if not expected_path.exists():
            print(f"⚠️ Real image not found at new location: {expected_path}")
            skipped += 1
            continue

        # Create target subdir and copy
        subdir = output_dir / img_id[:2]
        subdir.mkdir(parents=True, exist_ok=True)
        target_path = subdir / item.name

        try:
            shutil.copy2(expected_path, target_path)
            processed += 1
        except Exception as e:
            print(f"❌ Failed to copy {item.name}: {e}")
            skipped += 1

    print(f"\n✅ Done!")
    print(f"   Copied: {processed}")
    print(f"   Skipped: {skipped}")
    print(f"   Output: {output_dir}")

if __name__ == "__main__":
    main()