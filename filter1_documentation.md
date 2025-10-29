# 📄 `filter1.py` 
 - corresponds to stage 1 of the filtering pipeline (see https://github.com/Leeeef552/VLM_Image_Filtering/blob/main/filtering_pipeline_documentation.md)
 - contains the logic for the filtering, as well as some file and data management logic

### 🔍 Purpose
Filters images based on:
- **Technical quality** (resolution, file size, edge density)
- **NSFW content** (regex + LLM text classifier)
- **Singapore relevance** (regex + LLM text classifier + **VLM image classifier**)

Only images **confirmed as Singapore-related by the VLM** are accepted.

### ✅ Acceptance Criteria
An image is **accepted only if**:
1. Passes all technical checks (`resolution`, `size`, `edge_density`)
2. Passes NSFW filters (`quick_nsfw_regex` and `llm_nsfw_score < 2`)
3. Either:
   - Matches Singapore keywords via regex **OR**
   - LLM text classifier returns score `2` (certainly Singapore-related)
4. VLM image + text classifier returns score `1` (100% certain Singapore-related)

> ⚠️ If VLM returns `0` (uncertain) or `-1` (not Singapore), it’s **rejected**.

### 🧠 Models Used
- can plug and play, but generally try to use models that are up to date, relatively fast and would likely have stronger Singapore knowledge (good at general real world knowledge)
- **Text LLM**: `google/gemma-3-12b-it` (port 8124)
- **Vision LLM**: `Qwen/Qwen2.5-VL-72B-Instruct-AWQ` (port 8125)

---

# Usage Guide

### 📁 Input files, folders and configurations

- The filepath to the `metadata.jsonl` obtained from the `download_images.py` script
- Other configurations below, in which filepaths are CLI arguements and other parameters are script variables
- also ensure the models required are running on vllm at the respective endpoints 

```bash
CUDA_VISIBLE_DEVICES=0 vllm serve Qwen/Qwen2.5-VL-72B-Instruct-AWQ --tensor-parallel-size 2 --port 8125 --gpu-memory-utilization 0.9 --max-model-len 32k

CUDA_VISIBLE_DEVICES=1 vllm serve google/gemma-3-12b-it --port 8124 --gpu-memory-utilization 0.9 --max-model-len 24k
```

|  | Script Variables parameters – adjust within the script  |  |
|----------------------|-------------|-------------------|
|  | *These parameters are given by ChatGPT as well as with reference to research paper implementationsfor the image quality filtering process*||
| **Variable / Parameter** | **Description** | **Default / Example** |
| `MIN_SHORT_EDGE` | Minimum image short edge (width or height) in pixels | `256` |
| `MIN_FILE_SIZE_B` | Minimum file size in bytes (to exclude near-empty files) | `5120` (5 KB) |
| `EDGE_DENSITY_THRESH` | Minimum edge density (Canny edges / total pixels) to avoid blurry/blank images | `0.02` |
| `NSFW_REGEX_THRESHOLD` | Cumulative weighted regex score above which content is auto-rejected as NSFW | `10.0` |
| `TEXT_MODEL_BASE_URL` | The vllm API URL using OpenAI compatible server for text LLM (used for NSFW + Singapore text classification) | `http://localhost:8124/v1` |
| `VISION_MODEL_BASE_URL` | The vllm API URL for VLM (used for image + text classification) | `http://localhost:8125/v1` |
| `MAX_WORKERS` | Max concurrent threads for filtering | `72` |
| `PROCESSED_IDS_FILE` | Auto-generated file to track processed `image_id`s (for resumability) | `{output_dir}/processed_ids.txt` |

---

|  | CLI arguements – passed during script run |  |
|----------------------|-------------|-------------------|
|  | *Mainly just filepaths, to be passed during the script run as CLI arguements* ||
| **Variable / Parameter**   | **Description**                                                                  | **Default / Example**                           |
| `images_dir`| Path to the `./image` directory containing downloaded images, same path as the one specified and outputted in `download_images.py` | `/workspace/eefun/webscraping/filtering/images`|
| `metadata_jsonl`| Path to the input `metadata.jsonl` file, same path as the one specified and outputted in `download_images.py`| `./metadata.jsonl`|
| `output_dir`| Specified path to your output directory to hold the result from filter, contains accepted/rejected results| `./filtered_output/`|


### ✅ Example CLI Usage:
```bash
python filter.py /workspace/eefun/webscraping/filtering/images /workspace/eefun/webscraping/filtering/metadata.jsonl /workspace/eefun/webscraping/filtering/filtered_010925
```

### 📄 Expected output and behaviour
```bash
    /workspace/eefun/webscraping/filtering/filtered_010925/
    ├── accepted/
    │   ├── images/                 ← accepted images, split by sub-directories, **symlinks**
    │   └── metadata.jsonl          ← Metadata of accepted images
    ├── rejected/
    │   ├── images/                 ← All rejected images (by reason), , split by sub-directories, **symlinks**
    │   │   ├── missing/
    │   │   ├── resolution/
    │   │   ├── size/
    │   │   ├── edge_density/
    │   │   ├── nsfw_regex/
    │   │   ├── nsfw_llm/
    │   │   ├── sg_text_llm/
    │   │   └── vision_sg/
    │   │   └── timeout/
    │   └── metadata.jsonl          ← Metadata of rejected images
    └── processed_ids.txt           ← IDs of all processed images (for resume)
```


### 🔗 File Handling

*   Uses **symbolic links** (not copies) to save space.
*   Organizes by first 2 chars of `image_id` (e.g., `a3/abc123.jpg`).

**⚠️ Warning:** Since symbolic links are used, if the **original base image file** is deleted, the corresponding symlink will break (become a "dangling" link). An alternative would be to use hard links, but that is not currently implemented.
