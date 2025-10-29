# 📄 `filter3.py` – Experimental script to check for image feasibility for VLM Training

### 🔍 Purpose
As outlined in the [filtering pipeline documentation](https://github.com/Leeeef552/VLM_Image_Filtering/blob/main/filtering_pipeline_documentation.md), **not all Singapore-related images are useful for VLM pretraining**—many lack **visually distinctive Singaporean entities or contextual cues**, even if they pass basic quality and relevance checks.

This script is an **experimental feasibility filter** that uses **4 vision-language models (VLMs)** to score each image on a **1–5 scale** of usefulness for **Singapore-focused VLM training**. It was tested on batch `./storage (processed)/180925`, with outputs saved to `./storage (processed)/180925/3`.

> 📌 **Goal**: Identify images that **visually represent Singapore-specific scenes, objects, or cultural cues**—not just textually mention them.

---

### 📊 Scoring Rubric (per model)
| Score | Meaning |
|------|--------|
| **5** | Extremely useful – clear, distinctive Singapore visuals (e.g., Merlion, HDB blocks, MRT signage, bilingual street signs, ERP gantries) |
| **4** | Very useful – strong local context with multiple recognizable Singapore elements |
| **3** | Moderately useful – some Singapore cues but partially generic or ambiguous |
| **2** | Slightly useful – weak or indirect cues (e.g., “Singapore” in caption but no visual evidence) |
| **1** | Not useful – no meaningful Singapore-related visual content |

> ⚠️ **Text-only references** (e.g., “Orchard Road” on a blank background) receive **low scores**—the focus is on **visual recognizability**, not metadata.

---

### 🧠 Models Used (4 VLMs)
All models are served via **vLLM** as OpenAI-compatible endpoints:

| Model | Port | Model Name |
|------|------|-----------|
| Mistral | 8124 | `mistralai/Mistral-Small-3.2-24B-Instruct-2506` |
| Qwen-VL | 8125 | `Qwen/Qwen2.5-VL-72B-Instruct-AWQ` |
| GLM-4.1V | 8123 | `zai-org/GLM-4.1V-9B-Base` |
| InternVL | 8122 | `OpenGVLab/InternVL3_5-30B-A3B-Instruct` |

> 💡 You can reduce the ensemble by editing `MODEL_KEYS = [...]` in the script.

---

# Usage Guide   

### 📁 Input files, folders and configurations
- Configure with the accepted image data and metadata file outputs from stage 2 of the filtering pipeline  
- `accepted/metadata.jsonl` from stage 2 `filter2.py` 
- `accepted/images` from stage 2 `filter2.py`
- Ensure all **4 VLMs are running via vLLM** on their respective ports

#### Example vLLM launch commands:
```bash
# Mistral
CUDA_VISIBLE_DEVICES=0 vllm serve mistralai/Mistral-Small-3.2-24B-Instruct-2506 --port 8124 --gpu-memory-utilization 0.9 --max-model-len 24k --tokenizer_mode mistral --config_format mistral --load_format mistral --tool-call-parser mistral --enable-auto-tool-choice --limit-mm-per-prompt '{"image":1}' --tensor-parallel-size 1

# InternVL
CUDA_VISIBLE_DEVICES=1 vllm serve OpenGVLab/InternVL3_5-30B-A3B-HF --port 8122 --gpu-memory-utilization 0.9 --max-model-len 24k --trust-remote-code --limit-mm-per-prompt '{"image":1}'

# Qwen-VL
CUDA_VISIBLE_DEVICES=2 vllm serve Qwen/Qwen3-VL-30B-A3B-Instruct --port 8122 --gpu-memory-utilization 0.9 --max-model-len 24k --trust-remote-code

# GLM-4.1V
CUDA_VISIBLE_DEVICES=3 vllm serve zai-org/GLM-4.1V-9B-Base --port 8123 --gpu-memory-utilization 0.9 --max-model-len 24k
```
---

### 🛠️ Script Variables – adjust within the script

| Variable / Parameter | Description | Default / Example |
|----------------------|-------------|-------------------|
| `MODEL_KEYS` | List of model keys to include in ensemble (subset of `["mistral", "qwen", "glm", "internvl"]`) | `["mistral", "qwen", "glm", "internvl"]` |
| `MAX_WORKERS` | Max concurrent threads for processing | `64` |
| `VLM_MAX_RETRIES` | Number of retry attempts per model on failure (total = 1 + retries) | `2` |
| `SYSTEM` prompt | Detailed instructions for scoring usefulness (see script) | Hardcoded in script |

> 🔍 The **scoring logic** computes the **average of valid model scores** (1–5). However, **no threshold is applied**—all non-error images are accepted. Currently this script is experimental, so it was mainly to explore the scoring pattern of the VLMs and also to identify if a suitable threshold / prompt can be used to get the most desirable and most stable results. You can see the notebook for the analysis in `./rough_working/vlm_filter_analysis.ipynb` 

---

### 🖥️ CLI Arguments – passed at runtime

| Parameter | Description | Example |
|----------|-------------|--------|
| `images_dir` | Directory containing the subdirectories and the images as `{sub-directory}/{image_id}.jpg` | `/workspace/eefun/webscraping/filtering/images` |
| `metadata_file` | Input metadata in JSONL format | `./metadata.jsonl` |
| `output_dir` | Specified output root directory for results | `./filtered_feasibility_180925` |

### ✅ Example CLI Usage:
```bash
python filter3.py \
  /workspace/eefun/webscraping/filtering/images \
  ./metadata_180925.jsonl \
  ./storage\ \(processed\)/180925/3
```

---

### 📤 Expected Output and Behavior

NOTE: This was an early script that did not push the images into sub-directories. So it copies and directly places the images in the `./images` directory

```
./output_dir/
├── accepted/
│   ├── images/{image_id}.jpg        ← **COPIED** (not symlinked)
│   └── metadata.jsonl               ← All non-error records (even score=1)
├── error/
│   ├── images/{image_id}.jpg        ← Images that caused model/runtime errors
│   └── metadata.jsonl
├── vlm_results.log                  ← Per-image model scores + explanations
└── processed_tracker.txt            ← Resume tracking (image_id per line)
```

> ❗ **Important**: This script **copies images**, not symlinks—so it uses more disk space but is **independent of source image deletion**.

---

### ⚠️ Known Limitations & Notes

- To **enforce a usefulness threshold** (e.g., only accept if `final_score ≥ 3.5`), you must modify the `process_single_image_wrapper` function.
- Designed for **analysis and ranking**, not final filtering—ideal for **manual review or downstream thresholding**.

---

### 💡 Recommendations

- Use `filter3.py` **after `filter2.py`** to further rank high-quality, Singapore-relevant images by **training usefulness**.
- Export `vlm_results.log` or `metadata.jsonl` to **analyze score distributions** (e.g., via Pandas or Google Sheets).
