"""Opt-in live Bedrock smoke test. NOT run by pytest (it makes real, billable AWS calls).

Usage (from the project root, venv active):
    python scripts/test_bedrock.py --all
    python scripts/test_bedrock.py --embed
    python scripts/test_bedrock.py --llm

Exit code 0 only if every requested check actually succeeded.
Credentials are resolved by boto3's default chain and are never printed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.bedrock import BedrockError, BedrockRuntime  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.exceptions import ConfigurationError  # noqa: E402

SAMPLE_TEXT = "How do I reset my account password?"
SAMPLE_PROMPT = "Reply with exactly one short sentence confirming you are working."


def check_embeddings(rt: BedrockRuntime) -> bool:
    s = rt.settings
    print(f"[embed] model={s.bedrock_embed_model_id} region={s.aws_region} dim={s.bedrock_embed_dim}")
    body = json.dumps({"inputText": SAMPLE_TEXT, "dimensions": s.bedrock_embed_dim, "normalize": True})
    raw = rt.invoke_model(s.bedrock_embed_model_id, body)
    vec = json.loads(raw).get("embedding")
    if not isinstance(vec, list):
        print("[embed] FAIL: response contained no 'embedding' list")
        return False
    if len(vec) != s.bedrock_embed_dim:
        print(f"[embed] FAIL: got dimension {len(vec)}, expected BEDROCK_EMBED_DIM={s.bedrock_embed_dim}")
        return False
    print(f"[embed] PASS: dimension={len(vec)}, first values={[round(x, 4) for x in vec[:3]]}")
    return True


def check_llm(rt: BedrockRuntime) -> bool:
    s = rt.settings
    print(f"[llm] model={s.bedrock_llm_model_id} region={s.aws_region} (Converse API)")
    resp = rt.converse(
        s.bedrock_llm_model_id,
        messages=[{"role": "user", "content": [{"text": SAMPLE_PROMPT}]}],
        inferenceConfig={"maxTokens": 64, "temperature": 0.0},
    )
    try:
        text = resp["output"]["message"]["content"][0]["text"]
    except (KeyError, IndexError, TypeError):
        print("[llm] FAIL: unexpected Converse response shape")
        return False
    print(f"[llm] PASS: {text.strip()}")
    return True


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--embed", action="store_true", help="live Titan embeddings check")
    p.add_argument("--llm", action="store_true", help="live Nova Lite Converse check")
    p.add_argument("--all", action="store_true", help="run both checks")
    args = p.parse_args(argv)
    if not (args.embed or args.llm or args.all):
        p.print_help()
        print("\nNo checks requested; nothing was run (live tests are opt-in).")
        return 2

    try:
        rt = BedrockRuntime(get_settings())
    except ConfigurationError as exc:
        print(exc)
        return 1

    results: dict[str, bool] = {}
    for name, enabled, fn in (("embed", args.embed or args.all, check_embeddings),
                              ("llm", args.llm or args.all, check_llm)):
        if not enabled:
            continue
        try:
            results[name] = fn(rt)
        except BedrockError as exc:
            print(f"[{name}] FAIL ({type(exc).__name__}): {exc}")
            results[name] = False

    print("\nSummary: " + ", ".join(f"{k}={'PASS' if v else 'FAIL'}" for k, v in results.items()))
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
