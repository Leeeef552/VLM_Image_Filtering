# Image Dataset Storage (`storage (processed)`)

- This guide will go through how the image dataset is currently stored for each specfic batch of webscraping and filtering run. 
- It will also go through which folders to find the most filtered batch of images as well as recommended next actions to take 

### Overview of total filtered images per batch:
- **230825**: 19,999 images with metadata 
- **180925**: 306,598 images with metadata
- **051025**: 304,369 images with metadata

---

# `230825`
This was the earliest batch of webscraping and filtering. Additinally, this batch of images was scraped without being very targetted -->  they were scraped from random queries with no particular end in mind but still rooted in Singapore and as a result it may contain the least relevant images. 

> NOTE: The NSFW folders contain real NSFW images, generally the rejected images are still retained in the event trest another filtering run needs to be done to address false negatives or to study the effectiveness of the pipeline. Later batches have much less NSFW due to more targetted search and adjusting the NSFW strictness in searXNG 


> NOTE: As this was the earliest run, this batch of filtering may have the highest errors, refer to the total useful dataset size to get an idea


## Storage directory
- each image directory contains real image files, no symlinks
- some images are split into sub-directories
```
storage (processed)
│
├── 230825
│   ├── 1
│   │   ├── accepted
│   │   │   ├── images
│   │   │   └── metadata.jsonl
│   │   └── rejected
│   │       ├── images
│   │       │   ├── edge_density    
│   │       │   ├── missing
│   │       │   ├── nsfw_llm
│   │       │   ├── nsfw_regex
│   │       │   ├── resolution
│   │       │   ├── sg_text_llm
│   │       │   ├── size
│   │       │   ├── timeout
│   │       │   └── vision_sg
│   │       ├── metadata.jsonl
│   │       └── processed_ids.txt
│   └── 2
│       ├── accepted
│       │   ├── images
│       │   └── metadata.jsonl
│       ├── error
│       │   ├── images
│       │   └── metadata.jsonl
│       └── rejected
│           ├── images
│           └── metadata.jsonl
|
```

- stage 2 filtering was done through 3 models 
- 3 models (gpt-4o, Qwen2.5-VL-72B-AWQ, Qwen2.5-VL-32B)
- Accepted as long as either 1 of the models says the image is relevant

## Usefulness:
- You should refer to the `2/accepted/images` subfolder as it is the most filtered set of images for the 230825 batch

- Can consider doing additional filtering on the rejected/error for resolving false negatives depending on the effectivenss of the filtering process

## Total useful dataset size:
- Some images might have been lost or not properly tracked due to crashes and re-runs
- Properly tracked would mean found in the `./images` directory and has corresponding metadata tracked in the `metadata.jsonl` file
- There are instances where images are there but have no corresponding metadata, as well as `image_id` found in `metadata.jsonl` but not found in the `./images` folder
    - stage 2 Accepted: **19,999 images (all properly tracked )**
    - stage 2 Rejected: **Correctly tracked : 7076 images**
        - In metadata but NOT on disk: 930
        - On disk but NOT in metadata: 2 
    - stage 2 Errors: **61 images (all properly tracked)**

--- 


# `180925`

This batch represents a **more targeted web scraping effort** compared to the earliest runs (e.g., `230825`), with queries refined to emphasize **Singapore-related content**, leading to **higher overall relevance and quality** of collected images.

> **Key Filtering Strategy**:  
> Stage 2 filtering for this batch employed a **4-model ensemble**:
> - `mistralai/Mistral-Small-3.2-24B-Instruct-2506`  
> - `Qwen/Qwen3-VL-30B-A3B-Instruct`  
> - `Qwen2.5-VL-72B-AWQ`  
> - `InternVL3_5-30B-A3B`  

> An image was **accepted if at least 2 out of 4 models voted “relevant”**. This balanced approach **reduced false negatives** compared to stricter consensus rules. The idea is we want to capture as much Singapore related embedded image knowledge across all 4 of the models while reducing false posititves (hence the criteria of at least 2 aggrement).

> **Special Handling – Stage 3 (`filter3`)**:  
> A subset of images underwent an additional **Stage 3 filtering pass** using the `filter3` pipeline as an experimental stage. This stage applies relevance scores VLM data feasibility check. For full details on `filter3` logic and criteria, refer to the [filter3 documentation](https://github.com/Leeeef552/VLM_Image_Filtering/blob/main/filter3_documentation.md).


### Storage Directory Structure

- All image files are **real copies** (no symlinks).
for filesystem performance.
- `1`: Stage 1 contains symbolic links (not actual image files) and includes images that were rejected during initial filtering. Images are also categorise by rejection reasons (low edge density, blur, inappropriate content)
- `2`: Starting from Stage 2 (and continuing through Stage 3), the images are real files (not symlinks) and are organized into sharded subdirectories based on their image IDs for efficient filesystem access and management.


>  NOTE: There was an issue with the symbolic links in the `1/` directory—specifically, the target files were no longer accessible, rendering the symlinks broken. As a result, the original images referenced in Stage 1 are currently unavailable and will need to be re-downloaded and re-linked.
> Fortunately, this does **not** impact the integrity of the filtering pipeline or the final outputs. All **Stage 2 (and Stage 3) results contain real image files** that were already copied during processing, so the **core filtered dataset remains intact**. Only the **intermediate Stage 1 artifacts** (used for initial triage) are missing.
> Since the filtering decisions have already been recorded in the `metadata.jsonl` files and the accepted images are preserved in later stages, this is a recoverable issue. Re-downloading the original images and restoring the symlinks in `1/` will fully restore the intermediate layer—but is **not required** for using or validating the main filtered dataset.
```
storage (processed)
└── 180925
    ├── 1
    │   ├── accepted
    │   │   ├── images/          # symlinks
    │   │   └── metadata.jsonl
    │   └── rejected
    │       ├── images/          # symlinks (categorized by reason)
    │       └── metadata.jsonl   # includes rejection_reason field
    ├── 2
    │   ├── accepted
    │   │   ├── images/          # real files, sharded (aa/, bb/, ...)
    │   │   └── metadata.jsonl
    │   ├── rejected
    │   │   ├── images/          # real files, sharded
    │   │   └── metadata.jsonl
    │   └── pending
    │       ├── images/          # real files, sharded
    │       └── metadata.jsonl
    └── 3                       # ← experimental
        ├── accepted
        │   ├── images/         # real files, sharded
        │   └── metadata.jsonl
        └── rejected
            ├── images/         # real files, sharded
            └── metadata.jsonl
```

> Note: The `images/` directories under each stage are **sharded** (e.g., `aa/`, `bb/`, etc.), but this is omitted in the tree above for brevity.


### Usefulness & Best Practices

- ✅ **Primary usable data**:  
  Use `180925/2/accepted/images` as the **main dataset**—it reflects the 2-out-of-4 model consensus and offers a strong balance of relevance and recall.


## Total useful dataset size:
- Some images might have been lost or not properly tracked due to crashes and re-runs
- Properly tracked would mean found in the `./images` directory and has corresponding metadata tracked in the `metadata.jsonl` file
- There are instances where images are there but have no corresponding metadata, as well as `image_id` found in `metadata.jsonl` but not found in the `./images` folder
    - stage 2 Accepted: **306,598 images (all properly tracked )**
    - stage 2 Rejected: **175,683 images (all properly tracked )**
    - stage 2 Errors: **5359 images**
        - 6 found in `./images` folder but not found on `metadata.jsonl`
---

# `051025`

This is the most recent batch of web scraping and filtering. Compared to earlier runs like `230825`, this batch used **more targeted queries** focused on Singapore-related content, resulting in likely **higher relevance and quality** overall.

> **Important Note**:  
> Stage 2 filtering for this batch was performed using **only two models** due to GPU constraint at the time of filtering (mistralai/Mistral-Small-3.2-24B-Instruct-2506 & Qwen/Qwen3-VL-30B-A3B-Instruct, only accept if both models agree). This resulted in **increased the false negative rate**. Many potentially relevant images were incorrectly placed into `rejected` or `pending` categories.

> **Recommendation**:  
> Given the higher false negative rate, I recommend to run an **additional round of Stage 2 filtering** on the `rejected` (and any `pending`, if present) images using a **broader set of models**. This will help **recover useful images** that were mistakenly filtered out and **maximize dataset yield** without compromising quality.


### Storage Directory Structure

- All image directories contain **real image files** (no symlinks).
- Due to the large volume of data, **Stage 1 rejected images are not categorized by rejection reason**. Instead, they are **sharded into subdirectories** (e.g., `aa/`, `bb/`, `fg/`, etc.) for filesystem efficiency.
- Stage 2 outputs follow a clean structure:

```
storage (processed)
└── 051025
    ├── 1
    │   ├── accepted
    │   │   ├── images/
    │   │   │   ├── aa/
    │   │   │   ├── bb/
    │   │   │   └── ...
    │   │   └── metadata.jsonl
    |   |
    │   └── rejected
    │       ├── images/
    │       │   ├── aa/
    │       │   ├── bb/
    │       │   └── ...
    │       └── metadata.jsonl
    └── 2
        ├── accepted
        │   ├── images/
        │   │   ├── aa/
        │   │   ├── bb/
        │   │   └── ...
        │   └── metadata.jsonl
        | 
        ├── rejected
        │   ├── images/
        │   │   ├── aa/
        │   │   ├── bb/
        │   │   └── ...
        │   └── metadata.jsonl
        |
        ├── pending
        │   ├── images/
        │   │   ├── aa/
        │   │   ├── bb/
        │   │   └── ...
        │   └── metadata.jsonl
```


### Usefulness & Best Practices

- ✅ **Primary usable data**: Use the `051025/2/accepted/images/` folder—it contains the **most filtered and relevant images** for this batch.
- ⚠️ **High-potential secondary data**: The `051025/2/rejected/` folder likely contains **many false negatives** due to the limited two-model consensus.  
  → **Action**: Re-run Stage 2 filtering on this set with **3-model voting** (accept if **any one model** says “relevant”) to recover valid images.

## Total useful dataset size:
- An image is **“properly tracked”** only if:
  - It exists on disk **and**
  - Has a corresponding entry in `metadata.jsonl` with matching `image_id`.
    - stage 2 Accepted: **304,369 images (all properly tracked )**
    - stage 2 Rejected: **402,396 images (all properly tracked)**
    - stage 2 Pending: **176,770 images (all properly tracked)**

> many false negatives in rejected and pending, strongly recommend to run stage 2 filtering with more models on these folders 

