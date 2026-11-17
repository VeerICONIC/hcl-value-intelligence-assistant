"""
Bedrock access (Titan embeddings + Nova Lite via Converse) with safe fallbacks.

- Credentials come only from the boto3 default chain (never from code).
- If Bedrock is unavailable, embeddings fall back to a local hashing embedder and
  generation falls back to extractive answers, so the demo keeps working.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from nimbus import settings

_state = {"titan": None, "nova": None, "error": ""}
LOCAL_DIMS = 512
TITAN_INDEX_BUDGET_S = 40          # if indexing with Titan takes longer, fall back to local embeddings
_client_lock = threading.Lock()
_client_obj = None
_cache_lock = threading.Lock()
_CACHE_FILE = settings.ROOT / "data" / "embedding_cache.json"
_cache: dict | None = None


def _client():
    """One shared Bedrock Runtime client (creating a client per call is slow, especially with `aws login` profiles)."""
    global _client_obj
    with _client_lock:
        if _client_obj is None:
            import boto3
            from botocore.config import Config

            _client_obj = boto3.client("bedrock-runtime", region_name=settings.AWS_REGION,
                                       config=Config(connect_timeout=5, read_timeout=20, retries={"max_attempts": 2},
                                                     max_pool_connections=16))
        return _client_obj


def _load_cache() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            _cache = {}
    return _cache


def _save_cache() -> None:
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _cache_lock:
            _CACHE_FILE.write_text(json.dumps(_cache), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _key(text: str) -> str:
    return hashlib.sha256(f"{settings.EMBED_MODEL_ID}|{text}".encode()).hexdigest()


# --------------------------------------------------------------------------- embeddings
STOP = set("a an the and or of to in on for by with about which what who whom whose is are was were be been "
           "do does did has have had it its this that these those there their they them as at from into than then "
           "initiative initiatives section charter".split())


def _stem(w: str) -> str:
    for suf in ("ations", "ation", "ings", "ing", "ies", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def _local_embed(text: str) -> list[float]:
    """Deterministic hashing bag-of-words embedder (offline fallback): stopwords removed, light stemming."""
    vec = [0.0] * LOCAL_DIMS
    words = [_stem(w) for w in re.findall(r"[a-z]+", text.lower()) if w not in STOP]
    for w in words + [a + "_" + b for a, b in zip(words, words[1:])]:
        h = int(hashlib.md5(w.encode()).hexdigest(), 16)
        vec[h % LOCAL_DIMS] += 1.0 if "_" not in w else 0.5
    n = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / n for v in vec]


def _titan_embed(text: str) -> list[float]:
    body = json.dumps({"inputText": text[:20000], "dimensions": 1024, "normalize": True})
    resp = _client().invoke_model(modelId=settings.EMBED_MODEL_ID, body=body,
                                  contentType="application/json", accept="application/json")
    return json.loads(resp["body"].read())["embedding"]


def embedding_mode() -> str:
    if settings.EMBED_MODE == "local":
        return "local"
    if _state["titan"] is None:
        try:
            _titan_embed("connectivity check")
            _state["titan"] = True
        except Exception as e:  # noqa: BLE001
            _state["titan"] = False
            _state["error"] = f"Titan unavailable: {type(e).__name__}"
    return "titan" if _state["titan"] else "local"


def _titan_cached(text: str) -> list[float]:
    cache = _load_cache()
    k = _key(text)
    if k in cache:
        return cache[k]
    v = _titan_embed(text)
    with _cache_lock:
        cache[k] = v
    return v


def embed(texts: list[str], mode: str, budget_s: float | None = None) -> list[list[float]]:
    """Embed texts. Titan calls run in parallel, use a disk cache, and respect an optional time budget."""
    if mode != "titan":
        return [_local_embed(t) for t in texts]
    if len(texts) == 1:
        return [_titan_cached(texts[0])]
    out: list = [None] * len(texts)
    deadline = time.monotonic() + budget_s if budget_s else None
    pool = ThreadPoolExecutor(max_workers=8)
    try:
        futures = {pool.submit(_titan_cached, t): i for i, t in enumerate(texts)}
        remaining = (deadline - time.monotonic()) if deadline else None
        for f in as_completed(futures, timeout=remaining):
            out[futures[f]] = f.result()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
        _save_cache()
    return out


# --------------------------------------------------------------------------- generation
def llm_available() -> bool:
    if settings.LLM_MODE == "extractive":
        return False
    if _state["nova"] is None:
        try:
            _converse("You reply with one word.", "Reply with the word ready.", max_tokens=5)
            _state["nova"] = True
        except Exception as e:  # noqa: BLE001
            _state["nova"] = False
            _state["error"] = f"Nova unavailable: {type(e).__name__}"
    return bool(_state["nova"])


def _converse(system: str, user: str, max_tokens: int = 400) -> str:
    resp = _client().converse(
        modelId=settings.LLM_MODEL_ID,
        system=[{"text": system}],
        messages=[{"role": "user", "content": [{"text": user}]}],
        inferenceConfig={"maxTokens": max_tokens, "temperature": 0.0},
    )
    return resp["output"]["message"]["content"][0]["text"].strip()


def generate(system: str, user: str) -> str:
    return _converse(system, user)


def status() -> dict:
    return {"region": settings.AWS_REGION, "llm_model": settings.LLM_MODEL_ID,
            "llm": "bedrock" if _state["nova"] else ("extractive" if _state["nova"] is False or settings.LLM_MODE == "extractive" else "not checked"),
            "embeddings": "titan" if _state["titan"] else ("local" if _state["titan"] is False or settings.EMBED_MODE == "local" else "not checked"),
            "note": _state["error"]}
