import os
import re
import json
import asyncio
import aiohttp
import hashlib
import logging
import base64
from pathlib import Path
from datetime import datetime
from PIL import Image
from io import BytesIO
from urllib.parse import urlparse
from tqdm import tqdm
from typing import Optional, Tuple, Dict, Any, Iterable

# ==========================
# 🛠️ LOGGING SETUP (low verbosity)
# ==========================
LOG_DIR = "/workspace/eefun/webscraping/filtering"
Path(LOG_DIR).mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.WARNING,  # reduced verbosity
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "download.log")),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==========================
# 🔧 CONFIG (edit as needed)
# ==========================
METADATA_DIR = "/workspace/eefun/webscraping/filtering/raw"           # folder of .jsonl files
IMAGE_OUTPUT_DIR = "/workspace/eefun/webscraping/filtering/images"    # where images go
METADATA_OUTPUT_FILE = "/workspace/eefun/webscraping/filtering/metadata.jsonl"  # aggregated metadata
SEEN_URLS_FILE = "/workspace/eefun/webscraping/filtering/index/seen_urls.txt"   # dedupe index
MAX_CONCURRENCY = 128
REQUEST_TIMEOUT = 25  # seconds
QUEUE_MULTIPLIER = 4  # how many queue items per worker (helps memory usage)

# ==========================
# 🧰 HELPERS
# ==========================
def _hash_to_subdir(image_id: str) -> str:
    return image_id[:2]

def _ext_from_mime(mime: Optional[str]) -> str:
    if not mime:
        return ".jpg"
    mime = mime.lower().strip()
    mapping = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/bmp": ".bmp",
        "image/tiff": ".tiff",
        "image/x-icon": ".ico",
        "image/svg+xml": ".svg",  # rarely useful for PIL, but we keep it
        "application/octet-stream": ".jpg",
    }
    return mapping.get(mime, ".jpg")

def _ext_from_url(url: str) -> Optional[str]:
    try:
        path = urlparse(url).path
        _, ext = os.path.splitext(path)
        if ext and len(ext) <= 6:
            return ext
    except Exception:
        pass
    return None

def _sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def _md5_hex(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()

DATA_URI_RE = re.compile(r'^data:(?P<mime>[^;]+);base64,(?P<data>.+)$', re.IGNORECASE | re.DOTALL)

def is_data_uri(s: str) -> bool:
    return bool(DATA_URI_RE.match(s.strip()))

def parse_data_uri(s: str) -> Tuple[Optional[str], bytes]:
    """
    Returns (mime, bytes). Falls back to (None, b'') on failure.
    """
    m = DATA_URI_RE.match(s.strip())
    if not m:
        return None, b""
    mime = m.group("mime").strip()
    b64 = m.group("data")
    try:
        raw = base64.b64decode(b64, validate=True)
        return mime, raw
    except Exception:
        return mime, b""

BASE64_CHAR_RE = re.compile(r'^[A-Za-z0-9+/=\s]+$')

def looks_like_base64_blob(s: str) -> bool:
    s = s.strip()
    if len(s) < 64:  # tiny strings likely aren't full images
        return False
    if len(s) % 4 != 0:
        return False
    if not BASE64_CHAR_RE.match(s):
        return False
    # final validation
    try:
        base64.b64decode(s, validate=True)
        return True
    except Exception:
        return False

def decode_base64_blob(s: str) -> bytes:
    return base64.b64decode(s, validate=True)

def safe_open_append(path: str):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return open(path, "a", encoding="utf-8")

def load_seen(seen_file: str) -> set:
    if not os.path.exists(seen_file):
        return set()
    try:
        with open(seen_file, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    except Exception:
        return set()

def save_seen_sync(seen_file: str, key: str):
    Path(seen_file).parent.mkdir(parents=True, exist_ok=True)
    with open(seen_file, "a", encoding="utf-8") as f:
        f.write(key + "\n")

def image_dimensions_from_bytes(b: bytes) -> Tuple[int, int]:
    try:
        img = Image.open(BytesIO(b))
        return img.size
    except Exception:
        return (0, 0)

def build_metadata_entry(base_item: Dict[str, Any],
                         image_id: str,
                         source_type: str,
                         size_bytes: int,
                         width: int,
                         height: int,
                         file_path: str,
                         image_url: Optional[str],
                         source_ref: Optional[str],
                         original_mime: Optional[str],
                         ext: str) -> Dict[str, Any]:
    # Strip giant fields; never include raw base64
    md = {
        "image_id": image_id,
        "source_type": source_type,  # "url" | "base64"
        "image_url": image_url if source_type == "url" else None,
        "source_ref": source_ref,    # e.g., "b64:<sha256_prefix>"
        "original_mime": original_mime,
        "file_ext": ext,
        "file_path": file_path,
        "image_size_bytes": size_bytes,
        "image_dimensions": {"width": width, "height": height},
        "downloaded_at": datetime.utcnow().isoformat() + "Z",
        # Pass-through fields (use .get to avoid KeyErrors)
        "page_url": base_item.get("page_url"),
        "page_title": base_item.get("page_title"),
        "raw_caption": base_item.get("raw_caption"),
        "page_summary": base_item.get("page_summary"),
        "extracted_at": base_item.get("extracted_at"),
    }
    return md

# ==========================
# 📄 JSONL READING
# ==========================
def iter_jsonl_records(paths: Iterable[Path]) -> Iterable[Dict[str, Any]]:
    for p in paths:
        try:
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if isinstance(obj, dict):
                            yield obj
                        else:
                            # skip non-dict lines
                            continue
                    except Exception:
                        logger.warning(f"Skipping invalid JSONL line in {p.name}")
                        continue
        except Exception as e:
            logger.error(f"Error reading {p}: {e}")

def count_jsonl_records(paths: Iterable[Path]) -> int:
    total = 0
    for p in paths:
        try:
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        total += 1
        except Exception:
            continue
    return total

# ==========================
# 🌐 ASYNC DOWNLOAD / SAVE
# ==========================
class Downloader:
    def __init__(self,
                 image_dir: str,
                 metadata_path: str,
                 seen_file: str,
                 max_concurrency: int,
                 request_timeout: int):
        self.image_dir = image_dir
        self.metadata_path = metadata_path
        self.seen_file = seen_file
        self.request_timeout = request_timeout

        Path(self.image_dir).mkdir(parents=True, exist_ok=True)
        Path(self.metadata_path).parent.mkdir(parents=True, exist_ok=True)

        self.seen = load_seen(self.seen_file)
        self.seen_lock = asyncio.Lock()
        self.meta_lock = asyncio.Lock()

        timeout = aiohttp.ClientTimeout(total=self.request_timeout)
        connector = aiohttp.TCPConnector(limit=max_concurrency, force_close=False, ssl=False)
        self.session: Optional[aiohttp.ClientSession] = aiohttp.ClientSession(
            timeout=timeout, connector=connector, raise_for_status=False
        )

    async def close(self):
        if self.session:
            await self.session.close()

    async def _save_seen(self, key: str):
        if not key:
            return
        async with self.seen_lock:
            if key in self.seen:
                return
            self.seen.add(key)
            await asyncio.to_thread(save_seen_sync, self.seen_file, key)

    async def _append_metadata(self, entry: Dict[str, Any]):
        line = json.dumps(entry, ensure_ascii=False)
        async with self.meta_lock:
            await asyncio.to_thread(self._write_line_sync, self.metadata_path, line)

    @staticmethod
    def _write_line_sync(path: str, line: str):
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _image_path(self, image_id: str, ext: str) -> str:
        sub_dir = _hash_to_subdir(image_id)
        folder = os.path.join(self.image_dir, sub_dir)
        Path(folder).mkdir(parents=True, exist_ok=True)
        return os.path.join(folder, f"{image_id}{ext}")

    async def _download_bytes(self, url: str, retries: int = 2) -> Tuple[bytes, Optional[str]]:
        """
        Returns (content_bytes, content_type).
        Retries with headers for 403, 404, 405 responses.
        Logs failing URLs.
        """
        headers_list = [
            {},  # first try: no headers
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0 Safari/537.36"
                ),
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": url,
                "Connection": "keep-alive",
            }
        ]

        last_err = None
        for attempt in range(retries + 1):
            for headers in headers_list:
                try:
                    async with self.session.get(url, headers=headers) as resp:
                        if resp.status == 200:
                            ctype = resp.headers.get("Content-Type")
                            data = await resp.read()
                            return data, ctype
                        elif resp.status in (403, 405):
                            logger.warning(f"HTTP {resp.status} for {url} — retrying with headers.")
                            last_err = f"HTTP {resp.status}"
                            break  # try next header set
                        elif resp.status == 404:
                            logger.warning(f"HTTP 404 for {url} — not retrying.")
                            return b"", None
                        else:
                            last_err = f"HTTP {resp.status}"
                except Exception as e:
                    last_err = str(e)
            await asyncio.sleep(0.5 * (attempt + 1))

        # If we reached here, all attempts failed
        logger.warning(f"Failed to fetch URL: {url} — {last_err}")
        return b"", None


    async def process_item(self, item: Dict[str, Any]) -> None:
        """
        Handle a single record (URL or base64). Writes image + metadata if successful,
        updates seen file keyed by either URL or base64 hash-short ref.
        """
        raw = (item.get("image_url") or "").strip()
        if not raw:
            return

        # --- Branch 1: data URI (data:<mime>;base64,....)
        if is_data_uri(raw):
            mime, img_bytes = parse_data_uri(raw)
            if not img_bytes:
                return
            b64_digest = _sha256_hex(img_bytes)
            seen_key = f"b64:{b64_digest}"
            async with self.seen_lock:
                if seen_key in self.seen:
                    return
            image_id = b64_digest  # strong ID derived from content
            ext = _ext_from_mime(mime) if mime else ".jpg"
            width, height = image_dimensions_from_bytes(img_bytes)
            file_path = self._image_path(image_id, ext)
            try:
                await asyncio.to_thread(self._write_bytes_sync, file_path, img_bytes)
            except Exception:
                return
            await self._append_metadata(build_metadata_entry(
                item, image_id, "base64", len(img_bytes), width, height, file_path,
                image_url=None, source_ref=f"b64:{b64_digest[:12]}", original_mime=mime, ext=ext
            ))
            await self._save_seen(seen_key)
            return

        # --- Branch 2: naked base64 blob
        if looks_like_base64_blob(raw):
            try:
                img_bytes = decode_base64_blob(raw)
            except Exception:
                return
            b64_digest = _sha256_hex(img_bytes)
            seen_key = f"b64:{b64_digest}"
            async with self.seen_lock:
                if seen_key in self.seen:
                    return
            image_id = b64_digest
            ext = ".jpg"  # no mime info; fall back to jpg
            width, height = image_dimensions_from_bytes(img_bytes)
            file_path = self._image_path(image_id, ext)
            try:
                await asyncio.to_thread(self._write_bytes_sync, file_path, img_bytes)
            except Exception:
                return
            await self._append_metadata(build_metadata_entry(
                item, image_id, "base64", len(img_bytes), width, height, file_path,
                image_url=None, source_ref=f"b64:{b64_digest[:12]}", original_mime=None, ext=ext
            ))
            await self._save_seen(seen_key)
            return

        # --- Branch 3: regular URL
        url = raw
        seen_key = url  # keep as-is (no logging)
        async with self.seen_lock:
            if seen_key in self.seen:
                return

        data, content_type = await self._download_bytes(url)
        if not data:
            return

        image_id = _md5_hex(url)  # stable ID from URL
        url_ext = _ext_from_url(url)
        mime_ext = _ext_from_mime(content_type)
        ext = url_ext if url_ext else mime_ext
        if not ext:
            ext = ".jpg"

        width, height = image_dimensions_from_bytes(data)
        file_path = self._image_path(image_id, ext)
        try:
            await asyncio.to_thread(self._write_bytes_sync, file_path, data)
        except Exception:
            return

        await self._append_metadata(build_metadata_entry(
            item, image_id, "url", len(data), width, height, file_path,
            image_url=url, source_ref=None, original_mime=content_type, ext=ext
        ))
        await self._save_seen(seen_key)

    @staticmethod
    def _write_bytes_sync(path: str, data: bytes):
        Path(os.path.dirname(path)).mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)

# ==========================
# 🏃 Orchestration (queue + workers + one global tqdm)
# ==========================
async def run_all():
    # collect *.jsonl files
    jsonl_files = sorted([p for p in Path(METADATA_DIR).glob("*.jsonl") if p.is_file()])
    if not jsonl_files:
        logger.warning(f"No JSONL files found in {METADATA_DIR}")
        return

    total = count_jsonl_records(jsonl_files)
    if total == 0:
        logger.warning("No records detected in JSONL files.")
        return

    downloader = Downloader(
        image_dir=IMAGE_OUTPUT_DIR,
        metadata_path=METADATA_OUTPUT_FILE,
        seen_file=SEEN_URLS_FILE,
        max_concurrency=MAX_CONCURRENCY,
        request_timeout=REQUEST_TIMEOUT
    )

    queue = asyncio.Queue(maxsize=MAX_CONCURRENCY * QUEUE_MULTIPLIER)

    async def producer():
        for rec in iter_jsonl_records(jsonl_files):
            await queue.put(rec)
        # poison pills
        for _ in range(MAX_CONCURRENCY):
            await queue.put(None)

    async def worker(pbar: tqdm):
        while True:
            item = await queue.get()
            if item is None:
                queue.task_done()
                break
            try:
                await downloader.process_item(item)
            except Exception:
                # fully suppressed; some items can be malformed
                pass
            finally:
                pbar.update(1)
                queue.task_done()

    with tqdm(total=total, desc="Downloading all images") as pbar:
        producers = [asyncio.create_task(producer())]
        workers = [asyncio.create_task(worker(pbar)) for _ in range(MAX_CONCURRENCY)]
        await asyncio.gather(*producers)
        await queue.join()
        for w in workers:
            w.cancel()
        # swallow cancellation
        await asyncio.gather(*workers, return_exceptions=True)

    await downloader.close()

# ==========================
# 🚀 ENTRYPOINT
# ==========================
if __name__ == "__main__":
    try:
        asyncio.run(run_all())
        logger.warning("✅ All done.")
        logger.warning(f"📁 Images saved to: {IMAGE_OUTPUT_DIR}")
        logger.warning(f"📄 Metadata saved to: {METADATA_OUTPUT_FILE}")
    except KeyboardInterrupt:
        logger.warning("Interrupted by user.")
