# 📄 `filter2.py`  
- corresponds to **stage 2** of the filtering pipeline (see [filtering_pipeline_documentation.md](https://github.com/Leeeef552/VLM_Image_Filtering/blob/main/filtering_pipeline_documentation.md))  
- performs **consensus-based VLM classification** using two strong vision-language models  
- **no quality or NSFW filtering** — assumes input has already passed stage 1 (`filter1.py`)

### 🔍 Purpose
Classifies images as **Singapore-related** using **two independent VLMs**:
- Only accepts images where **both models agree** the image is Singapore-related.
- Disagreements are placed in a **`pending`** folder for manual review
> this is the current implementation, it was tweaked from a 3 model / 4 model filter to use 2 models only, due to gpu constraint
- Errors (e.g., model crash, timeout, image problems) go to **`error`**.


### ✅ Acceptance/Rejection/Pending Logic
1. An image is **accepted only if**: Both VLMs return a score of **`1`** (100% certain Singapore-related).
2. An image is **rejected**: Both VLMs return a score of **`0`** (100% certain NOT Singapore-related). 
3. If models **disagree** (`1` vs `0`), the image is marked **`PENDING`**.  
> ⚠️ If **either model fails**, the image goes to **`ERROR`**.

### 🧠 Models Used
- Generally try to pick different model families but strong VLMs, medium size preferred due to latency-accuracy trade-off
- **Mistral**: `mistralai/Mistral-Small-3.2-24B-Instruct-2506` (port 8125)
- **InternVL**: `Qwen/Qwen3-VL-30B-A3B-Instruct` (port 8124)

> 💡 Ensure both models are running via **vLLM** on the specified ports before execution.

```
# Example vLLM launch commands
CUDA_VISIBLE_DEVICES=0 vllm serve Qwen/Qwen3-VL-30B-A3B-Instruct --port 8122 --gpu-memory-utilization 0.9 --max-model-len 24k

CUDA_VISIBLE_DEVICES=1 vllm serve mistralai/Mistral-Small-3.2-24B-Instruct-2506 --port 8124 --gpu-memory-utilization 0.9 --max-model-len 24k --tokenizer_mode mistral --config_format mistral --load_format mistral --tool-call-parser mistral --enable-auto-tool-choice --limit-mm-per-prompt '{"image":1}' --tensor-parallel-size 1
```
---

# Usage Guide

### 📁 Input files, folders and configurations
- All the file paths included for `filter2.py` should be from the accepted output from the stage 1 filter process
> the file/folder path for `./accepted/images`, `accepted/metadata.jsonl` that was outputed from `filter1.py`



|  | CLI arguments – passed during script run |  |
|----------------------|-------------|-------------------|
|  | *Filepaths only — all other config is in-script* ||
| **Variable / Parameter**   | **Description**                                                                  | **Default / Example**                           |
| `images_dir`| Base image directory containing all the accepted images from stage 1 filtering `filter1.py` | `./images` |
| `metadata_file`| Path to the `metadata.jsonl` containing metadata of the accepted images (from stage 1 filtering `filter1.py` output) | `./metadata.jsonl` |
| `output_dir`| Specified output root directory to collect stage 2 `filter2.py` results (accepted/rejected/pending/error) | `./filtered_stage2/` |

### ✅ Example CLI Usage:
```bash
python filter2.py /workspace/eefun/webscraping/filtering/images ./filtered_010925/accepted/metadata.jsonl ./filtered_stage2_010925
```

---

### 📄 Expected output and behaviour
```bash
./filtered_stage2_010925/
├── accepted/
│   ├── images/{image_id}.jpg → symlink
│   └── metadata.jsonl
├── rejected/
│   ├── images/{image_id}.jpg → symlink
│   └── metadata.jsonl
├── pending/
│   ├── images/{image_id}.jpg → symlink   ← model disagreement
│   └── metadata.jsonl
├── error/
│   ├── images/{image_id}.jpg → symlink   ← model crash / quota error
│   └── metadata.jsonl
├── vlm_results.log                       ← Detailed per-model scores & explanations
└── processed_tracker.txt                 ← Resumability tracker (image_id list)
```

### 🔗 File Handling

*   Uses **symbolic links** (not copies) to reference original images.
*   **Overwrites existing symlinks** safely (unlinks before creating new).

**⚠️ Warning:** Symlinks depend on the **original image files remaining in place**. If the source images are moved or deleted, symlinks will break. Alternative is hardlinks
