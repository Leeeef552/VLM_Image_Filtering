
# Downloader Script (`./scripts/download.py`)

This script downloads and processes images from the web-scraped data at scale. It handles both image URLs and base64-encoded images (including data URIs), saves them in a filesystem-friendly structure, while supporting **resumable**, **idempotent**, and **high-concurrency** execution.

The script should be run from the image_metadata.json from the vlm webscraping pipeline. (https://github.com/Leeeef552/vlm_webscrape_2.git)

---

## ✅ Key Features

- **Supports multiple image sources**: Handles different file formats and converts all to jpeg/jpg formats 

- **Deduplication**: Skips already-processed URLs or identical base64 images (using content hash)

- **Scalable storage**: Images are sharded into subdirectories (e.g., `ab/abcdef1234.jpg`) to avoid OS limits

- **Resumable & idempotent**:Safe to re-run; won’t re-download or duplicate

- **Parallel downloading**: Async I/O with concurrent downloads

---

## Usage Guide:

### 📁 Input files, folders and configurations
- One or more `.jsonl` files in `METADATA_DIR`
    - the file format from the webscraping pipeline (https://github.com/Leeeef552/vlm_webscrape_2.git) is in json, so you should convert to jsonl if you want to use this download script. 
    - You can refer to `./utils/json_to_jsonl.py` for template code to convert json to jsonl

- Edit the top of the script to adjust paths and behavior:

| Variable | Description | Default |
|--------|-------------|--------|
| `METADATA_DIR` | Folder containing input `.jsonl` files | `/workspace/eefun/webscraping/filtering/raw` |
| `IMAGE_OUTPUT_DIR` | specify the path to images folder in which all the downloaded images are saved | `/workspace/eefun/webscraping/filtering/images` |
| `METADATA_OUTPUT_FILE` | specify the path to `metadata.jsonl` which will track the image_id together with the image metadata | `.../metadata.jsonl` |
| `SEEN_URLS_FILE` | Just a tracker .txt deduplication index file | `.../index/seen_urls.txt` |
| `MAX_CONCURRENCY` | control number of concurrent downloads | `128` |
| `REQUEST_TIMEOUT` | Timeout per HTTP request (seconds) | `25` |

---

### ⚙️ How to run
- ensure all the above configurations and file/folder path is configured in the script
- run the following (may need to pip install missing directories)
    ```bash
    python download_images.py
    ```

---

### ⚙️ Output and expected behaviour
- should see a `./image` directory (or one that corresponds to how you configured `IMAGE_OUTPUT_DIR` in the above) containing the sub-directories, each holding the image files
- `metadata.jsonl` that contains the metadata for each image, also containing the image_id 
- an `./index` folder containing the `seen_url.txt` for the urls that have gone through image download
- `download.log` (can ignore this)
```
/workspace/eefun/webscraping/filtering/
├── images/                     # Sharded image storage (by image_id prefix)
│   ├── ab/
│   ├── cd/
│   └── ...
├── metadata.jsonl             # Enriched metadata (one record per downloaded image)
├── index/
│   └── seen_urls.txt          # Deduplication index (URLs + base64 hashes)
└── download.log               # Runtime warnings and errors
```

Each metadata record includes:
```json
{
  "image_id": "abcdef1234...",
  "source_type": "url" | "base64",
  "image_url": "https://example.com/image.jpg",
  "file_path": "images/ab/abcdef1234.jpg",
  "image_size_bytes": 245678,
  "image_dimensions": {"width": 1920, "height": 1080},
  "file_ext": ".jpg",
  "page_url": "...",
  "raw_caption": "...",
  "downloaded_at": "2025-10-29T12:34:56.789Z",
  ...
}
```

---

## 🧪 Testing & Debugging

- Test on a small `.jsonl` subset first!
- Check `download.log` for skipped/failed URLs
- Validate output metadata with:
  ```bash
  head -n 5 metadata.jsonl | jq .
  ```
