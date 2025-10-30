import ijson
import json

input_path = "archive/deduplicated_images_180925.json"
output_path = "archive/deduplicated_images_180925.jsonl"

with open(input_path, 'rb') as infile, open(output_path, 'w', encoding='utf-8') as outfile:
    for item in ijson.items(infile, 'item'):
        json.dump(item, outfile, ensure_ascii=False)
        outfile.write('\n')
