import os
import json

# --- CONFIGURE THESE PATHS ---
METADATA_PATH = "storage (processed)/180925/2/error/metadata.jsonl"
IMAGE_ROOT_DIR = "storage (processed)/180925/2/error/images"  # root folder containing subdirs like "a1", "b2", etc.

# --- Step 1: Load image_ids from metadata ---
metadata_ids = set()
with open(METADATA_PATH, "r", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            record = json.loads(line)
            metadata_ids.add(record["image_id"])

print(f"✅ Loaded {len(metadata_ids)} image IDs from metadata.")

# --- Step 2: Collect image IDs from disk ---
disk_ids = set()
valid_exts = {".jpg", ".jpeg"}

for subdir in os.listdir(IMAGE_ROOT_DIR):
    subdir_path = os.path.join(IMAGE_ROOT_DIR, subdir)
    if not os.path.isdir(subdir_path):
        continue
    for filename in os.listdir(subdir_path):
        name, ext = os.path.splitext(filename.lower())
        if ext in valid_exts:
            disk_ids.add(name)

print(f"🖼️  Found {len(disk_ids)} image files on disk.")

# --- Step 3: Compare ---
only_in_metadata = metadata_ids - disk_ids
only_on_disk = disk_ids - metadata_ids
in_both = metadata_ids & disk_ids  # intersection

print("\n🔍 Summary:")
print(f"- In metadata but NOT on disk: {len(only_in_metadata)}")
print(f"- On disk but NOT in metadata: {len(only_on_disk)}")
print(f"- ✅ Correctly tracked (in both): {len(in_both)}")

# Optional: sanity check
assert len(in_both) + len(only_in_metadata) == len(metadata_ids)
assert len(in_both) + len(only_on_disk) == len(disk_ids)