import json
import glob
import os
from tqdm import tqdm  # 👈 Properly imported now!

def deduplicate_image_metadata(input_pattern, output_file):
    """
    Deduplicate image metadata JSON files by 'image_url'.
    Reads files one at a time, keeps only first occurrence of each image_url.
    Designed for large files (~2GB each).
    """
    seen_image_urls = set()
    deduplicated_data = []

    # Find all matching JSON files
    json_files = sorted(glob.glob(input_pattern))
    if not json_files:
        print("❌ No JSON files found matching pattern:", input_pattern)
        return

    print(f"✅ Found {len(json_files)} file(s) to process:")
    for f in json_files:
        print(f"   - {os.path.basename(f)}")

    # Process each file one at a time
    for file_path in json_files:
        print(f"\n📂 Processing: {file_path}")
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if not isinstance(data, list):
                print(f"⚠️ Warning: {file_path} is not a list. Skipping.")
                continue

            # Use tqdm to show progress through items in this file
            count_added = 0
            for item in tqdm(data, desc="  🕵️ Deduplicating", unit="item", leave=False):
                image_url = item.get('image_url')
                
                # Skip if no URL or invalid type
                if not isinstance(image_url, str) or not image_url.strip():
                    continue

                # Deduplicate: keep only first occurrence
                if image_url not in seen_image_urls:
                    seen_image_urls.add(image_url)
                    deduplicated_data.append(item)
                    count_added += 1

            print(f"   ➕ Added {count_added} new images from {os.path.basename(file_path)}")

        except json.JSONDecodeError as e:
            print(f"❌ JSON decode error in {file_path}: {e}")
        except Exception as e:
            print(f"❌ Error processing {file_path}: {e}")

    # Write final deduplicated output
    print(f"\n💾 Writing {len(deduplicated_data)} unique images to: {output_file}")
    try:
        with open(output_file, 'w', encoding='utf-8') as out_f:
            json.dump(deduplicated_data, out_f, indent=2, ensure_ascii=False)
        print(f"✅ Success! Output saved to: {output_file}")
    except Exception as e:
        print(f"❌ Failed to write output: {e}")

# ======================
# 🔧 CONFIGURE THESE PATHS
# ======================
INPUT_PATTERN = "/workspace/eefun/webscraping/filtering/images_metadata/*.json"
OUTPUT_FILE = "/workspace/eefun/webscraping/filtering/images_metadata/deduplicated_images.json"

# Run it!
if __name__ == "__main__":
    deduplicate_image_metadata(INPUT_PATTERN, OUTPUT_FILE)