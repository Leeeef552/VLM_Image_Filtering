# 🧠 Filtering Pipeline Document

#### Note:
*The scripts are often adjusted incrementally based on new findings and available GPU resources, so the pipeline may not be fully reproducible. The primary focus of this document is to help you understand the current state of the image dataset and how it was filtered. Additionally, I hope the logic underlying the filtering process is clear and well-documented and can be adapted further to improve the filtering process.*

## Objectives of Filtering
The filtering pipeline generally consists of two main stages designed to ensure the collected images are **high-quality** and **relevant to Singapore**. It operates on the below primary objectives:

1. **Image Quality**: Images scraped need to be checked for their quality first, we filter out for poor quality images which include too low resolution, image dimensions are too small etc.

2. **Singapore relevance**: Images scraped must be relevant to Singapore domain, as this dataset is meant to be used for domain pretraining of VLMs 

3. **Feasibility for training**: Not all kinds of images are useful for training despite being relevant to Singapore. For example, an image containing not entities but only a text mentioning Singapore may be "singapore" relevant, but not useful for training. 
  
The filtering pipeline employs a tiered approach that combines heuristic-based rules, LLM-as-a-judge, and VLM-as-a-judge to evaluate samples. The design prioritizes efficiency: to minimize overall processing time, the pipeline is structured to avoid model-based judgment whenever possible, especially VLM inference, which is the most time-consuming step.

## Filtering logic:

### **Stage 1:** `./scripts/filter1_py`
On a high level, this is the stage 1 of filtering that handles image quality + Singapore relevance check. 

1. Image Quality filtering through heuristics:
    - Reject the images if
    min(short_edge) < 256 → resolution
    - file_size < 5KB → size
    - edge_density < 0.02 → edge_density

2. NSFW filtering through heuristics and LLM:
    - Reject the image if the accompany text:
        - Fails the predefined regex (profanity)
        - NSFW check using a medium size text only LLM (gemma3-12B-it) to check metadata + accompanying text 

3. Text based Singapore relevance:
    - Auto accept if: 
        - Website link or accompanying text or metadata contains Singapore relevant words (small predefined regex pattern check)
        - Pass all text data (link, website name, page summary, etc) to a medium size text only LLM (gemma3-12B-it) to check for Singapore relevance check

4. Signapore relevance (image + text):
    - Pass the image + accompanying text + metadata to the VLM to check if the image is relevant to Singapore
    - Short coming is that sometimes the image alone is not informative but because the text content is strong, image is accepted. So the image is not actually being properly evaluated as relevant, and the sample is wrongly accepted due to the text bias. Thus a second layer of filtering is required.

### **Stage 2:** `./scripts/filter2_py`
On a high level, this is the stage 2 that handles pure image relevance check by VLM only. To ensure a more robust dataset, this stage generally uses more than 1 VLM to do the check. This is because if we relied on a single model, the dataset would only be as good as that model, in which the dataset becomes limited by its blind spots, biases, and mistakes. Using several models together helps catch more relevant images and reduces the risk of unfairly rejecting good data based on one model's decision boundary. 

Below is the decision making rules I employed depending on the number of gpu resources and the number models i could host on the server:

1. Filtering with 2 VLM models
    - follow the decision made when both models agree (ie. if both models decide the image is relevant, then it is relevant, and if both decide it is not relevant, then it is rejected)
    - when there is contention (one model accepts, the other rejects), then the image is placed in the pending folder

2. Filtering with 2 VLM models
    - take the majority vote (ie. as long as 1 of the 3 models accept, then we will accept that the image is relevant, vice versa)

3. Filtering with 4 VLM models
    - as long as any 2 models accepts we will accept that the image is relevant. 


## Pipeline considerations
During development and scaling of the image filtering pipeline, several practical lessons emerged that significantly impact reliability, performance, and maintainability:

1. File System Organization & Scalability: 
    - Storing millions of images in a single directory can overwhelm the file system, causing slow access, crashes, or failure to list contents. To mitigate this, shard images into subdirectories early in the pipeline (e.g., using the first two characters of a hashed filename as the subfolder name: ab/abcdef1234.jpg). This structure should be applied from initial download through all filtering stages to ensure consistent and scalable access.

2. Efficient Data Handling with Links
    - Images are large (often resulting in 100+ GB directories), so copying files during filtering stages consumes excessive storage and time. Moving files risks data loss or corruption if a process crashes mid-operation. The safest and most space-efficient approach is to use symbolic or hard links to reference images across stages. This preserves the original data while enabling lightweight “copies” for downstream processing—implemented in later filtering batches of this repository.

3. Idempotency and Resumability
    - Given the long runtimes and scale of web-scale image processing, idempotent operations (re-running yields the same result) and resumable workflows are essential. A simple but effective pattern is to log processed image IDs to a .txt or .jsonl file after each successful step. This allows the pipeline to skip already-processed items on restart.

*⚠️ Caution: Idempotency becomes harder with concurrent or parallel execution—ensure atomic writes or use file locking if needed. Always test scripts on a small subset before full-scale runs. A bug in filtering or file handling can corrupt or delete irreplaceable data, potentially requiring re-scraping from scratch.*
