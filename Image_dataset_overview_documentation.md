# Image Dataset Storage Documentation
This guide will help you understand the structure and organization of the image dataset stored in the `storage (processed)` directory. 

For a more specific guide for each batch of image data webscraping and filtering run, refer to the individual guides here: ()

> ❗NOTE: *Be careful: The nsfw folders do contain nsfw images, can consider just deleting. I originally retained the entire rejected folders in case there is a need to run another filtering, to resolve false negatives. Later batches of runs tend to have significantly less nsfw as I tweaked the searXNG engine to have a more strict nsfw filter*

---

## 📁 Root Directory: `storage (processed)`

This is the main holding folder for all processed image datasets. Inside this directory, you'll find subdirectories named using the format **`DDMMYY`**, which indicates the approximate date (day, month, year) when the data was scraped and filtered.

Example:
```
storage (processed)/
├── 051025/
├── 180925/
├── 230825/
└── ...
```

---

## 🗂️ Structure Within Each DDMMYY Folder

Each date-named folder contains numbered subdirectories (`1`, `2`, `3`, etc.) representing the results of sequential filtering stages:

- **`1`** → Results after Stage 1 filtering
- **`2`** → Results after Stage 2 filtering
- **`3`** → Experimental results from Stage 3 (only applied to batch `180925` — see [filter3_documentation.md](https://github.com/Leeeef552/VLM_Image_Filtering/blob/main/filter3_documentation.md) for details)

---

## NOTE: 📦 Image Organization: Splitting Large Folders

To avoid performance issues or system limitations with large directories, image folders (especially under `accepted/images/` and `rejected/images/`) may be split into subdirectories using the **first 2 characters of the image ID hash**.

---

Example:
```
images/
├── ab/
│   ├── ab12345.jpg
│   └── ab67890.jpg
├── cd/
│   └── cd11223.jpg
└── ...
```

This ensures no single folder becomes too large and maintains efficient file system navigation.

---

## 🧹 Stage 1 Filtering (`1/`)

Stage 1 produces two main folders:

### ✅ `accepted/`
Contains images that passed Stage 1 filtering.

- `images/` → All accepted images.
    - *(Optional)* If there are many images, they may be split into subfolders based on the **first 2 characters of the image ID hash** to prevent folder overload.
        ```
        images/
        ├── ab/
        │   ├── ab12345.jpg
        │   └── ab67890.jpg
        ├── cd/
        │   └── cd11223.jpg
        └── ...
        ```
- `metadata.jsonl` → Line-delimited JSON file containing metadata for each accepted image.

### ❌ `rejected/`
Contains images that failed Stage 1 filtering.

- `images/` → Images grouped by rejection reason in subfolders:
    - `edge_density/`
    - `nsfw_llm/`
    - `nsfw_regex/`
    - `resolution/`
    - `sg_text_llm/`
    - `size/`
    - `timeout/`
    - `vision_sg/`
    - *(Other reasons as needed)*
- `metadata.jsonl` → Metadata for rejected images.

> 💡 *Note: Rejected images are categorized by reason to help diagnose filtering behavior.* 
---

## 🧹 Stage 2 Filtering (`2/`)

Stage 2 follows a similar structure but simplifies the rejected folder:

### ✅ `accepted/`
Same as Stage 1:
- `images/` → Accepted images (possibly split by first 2 chars of image ID hash)
- `metadata.jsonl` → Metadata for accepted images

### ❌ `rejected/`
Simplified structure:
- `images/` → All rejected images directly in this folder (no subfolders by reason)
- `metadata.jsonl` → Metadata for rejected images

> 💡 *Note: Stage 2 does not categorize rejections by reason — all rejected images are stored together.*

---

## 🧪 Stage 3 Filtering (`3/`) — Experimental

⚠️ **Important**: Stage 3 was only applied to the batch `180925`. It represents an experimental run using script 3.

For detailed information about Stage 3, including its purpose, methodology, and output structure, please refer to:
👉 [filter3_documentation.md](https://github.com/Leeeef552/VLM_Image_Filtering/blob/main/filter3_documentation.md)


---

## 🧭 Navigation Summary

| Path | Purpose |
|------|---------|
| `storage (processed)/DDMMYY/1/accepted/images/` | Stage 1 accepted images |
| `storage (processed)/DDMMYY/1/rejected/images/` | Stage 1 rejected images, categorized by reason |
| `storage (processed)/DDMMYY/2/accepted/images/` | Stage 2 accepted images |
| `storage (processed)/DDMMYY/2/rejected/images/` | Stage 2 rejected images (uncategorized) |
| `storage (processed)/180925/3/` | Experimental Stage 3 results (see [filter3_documentation.md](https://github.com/Leeeef552/VLM_Image_Filtering/blob/main/filter3_documentation.md) for details) |

---

## 📁 `metadata.jsonl`: within each accepted/rejected/pending
- Within each folder, there will likely be a `metadata.jsonl` that contains the relevant metadata corresponding to the images within the `./images` folder (within each `accepted/rejected/pending` folder)
- The data structure within of each `metadata.jsonl` may vary depending on the filtering stage as well as across batches of webscrape/fitlering runs due to incremental updates to the filtering logic and webscraping scripts
- Besides minor deviations, the general structure of the `metadata.jsonl` is as follows:
```
{
  "image_id": "image id",                               // corresponds to the img_id in the image folder
  "image_url": "https://image_url.com/image.jpg",       // raw image URL
  "page_url": "https://example.com/source/page",        // the actual website scraped
  "page_title": "Title",                                // metadata extracted from the website
  "raw_caption": "accompanying caption",                // surrounding text scraped by my code
  "page_summary": "Brief summary",                      // summary metadata from the website
  "extracted_at": "time",                               // when the data was extracted
  "downloaded_at": "time",                              // when the image was downloaded
  "image_size_bytes": 84121,                            // file size in bytes
  "image_dimensions": {
    "width": 500,
    "height": 375
  },
  "vlm_sg_score": 1,                                    // 1 if Singapore-relevant, 0 otherwise
  "vlm_sg_explanation": some explation                  //"Short explanation or justificationby the VLM
}
```
> NOTE: some of the metadata.jsonl may contain `image_path`, generally these are unreliable as the folder names and file paths may have been altered. To find the image path, you should rely on the image_id as this is generally the ground truth pointer. The path should be resolved by referring to the `./images` folder in the same directory as each `metadata.jsonl`
