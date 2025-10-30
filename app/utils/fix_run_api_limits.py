# find_and_fix_quota_errors.py
import re
from pathlib import Path

def find_error_images(log_file: Path):
    """Find images that had errors in VLM processing"""
    error_images = set()
    
    if not log_file.exists():
        print(f"Log file not found: {log_file}")
        return error_images
    
    with open(log_file, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Split by the separator lines to get individual image entries
    entries = content.split("-" * 60)
    
    for entry in entries:
        if not entry.strip():
            continue
            
        # Check if this entry contains any errors
        if "Error occurred" in entry:
            # Extract the image ID from this entry
            lines = entry.strip().split('\n')
            for line in lines:
                if line.startswith("Image ID:"):
                    img_id = line.split("Image ID:")[1].strip()
                    error_images.add(img_id)
                    print(f"Found error image: {img_id}")
                    break
    
    return error_images

def create_new_tracker_file(original_tracker: Path, new_tracker: Path, images_to_remove: set):
    """Create a new tracker file excluding error images"""
    if not original_tracker.exists():
        print(f"Original tracker file not found: {original_tracker}")
        return 0
    
    # Read current tracker content
    with open(original_tracker, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    # Filter out lines containing images to remove
    remaining_lines = []
    removed_count = 0
    
    for line in lines:
        line_stripped = line.strip()
        if line_stripped and line_stripped in images_to_remove:
            print(f"Excluding from new tracker: {line_stripped}")
            removed_count += 1
        else:
            remaining_lines.append(line)
    
    # Write the filtered content to new file
    with open(new_tracker, "w", encoding="utf-8") as f:
        f.writelines(remaining_lines)
    
    return removed_count

def create_new_log_file(original_log: Path, new_log: Path, error_images: set):
    """Create a new log file excluding error image entries"""
    if not original_log.exists():
        print(f"Original log file not found: {original_log}")
        return 0
    
    with open(original_log, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Split by separator lines
    entries = content.split("-" * 60)
    
    # Filter out entries for error images
    clean_entries = []
    removed_count = 0
    
    for entry in entries:
        if not entry.strip():
            continue
            
        # Check if this entry is for an error image
        is_error_entry = False
        lines = entry.strip().split('\n')
        for line in lines:
            if line.startswith("Image ID:"):
                img_id = line.split("Image ID:")[1].strip()
                if img_id in error_images:
                    print(f"Excluding from new log: {img_id}")
                    is_error_entry = True
                    removed_count += 1
                break
        
        if not is_error_entry:
            clean_entries.append(entry)
    
    # Write clean entries to new log file
    with open(new_log, "w", encoding="utf-8") as f:
        for i, entry in enumerate(clean_entries):
            if i > 0:
                f.write("-" * 60 + "\n")
            f.write(entry.strip() + "\n")
        if clean_entries:  # Add final separator if there are entries
            f.write("-" * 60 + "\n")
    
    return removed_count

def main():
    # Update these paths to match your files
    original_log = Path("/workspace/eefun/webscraping/filtering/output_061025/vlm_results.log")
    original_tracker = Path("/workspace/eefun/webscraping/filtering/output_061025/processed_tracker.txt")
    
    # New file names (you can change these)
    new_log = Path("vlm_results_clean.log")
    new_tracker = Path("processed_tracker_clean.txt")
    
    print("🔍 Finding images with VLM errors...")
    error_images = find_error_images(original_log)
    
    if not error_images:
        print("✅ No error images found in log file")
        return
    
    print(f"\n📊 Found {len(error_images)} images with errors:")
    for img_id in sorted(error_images):
        print(f"  - {img_id}")
    
    print(f"\n📝 Creating new files...")
    
    # Create new tracker file
    removed_from_tracker = create_new_tracker_file(original_tracker, new_tracker, error_images)
    
    # Create new log file
    removed_from_log = create_new_log_file(original_log, new_log, error_images)
    
    print(f"\n✅ Done! Created new files:")
    print(f"   New log file: {new_log}")
    print(f"   New tracker file: {new_tracker}")
    
    print(f"\n📊 Summary:")
    print(f"   - Error images identified: {len(error_images)}")
    print(f"   - Entries removed from tracker: {removed_from_tracker}")
    print(f"   - Entries removed from log: {removed_from_log}")
    print(f"   - Next run should use the new files for clean reprocessing")

if __name__ == "__main__":
    main()