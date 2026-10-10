"""Offline GPT-OSS BPE estimate; framing/schema overhead is still an estimate.

Pattern and ranks: OpenAI tiktoken (MIT, assets/tokenizer/LICENSE.txt).
GPT-OSS uses the o200k_base ordinary-text vocabulary in o200k_harmony.
"""

import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path

import tiktoken
from tiktoken.load import load_tiktoken_bpe

PATTERN = "|".join([
    r"[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]*[\p{Ll}\p{Lm}\p{Lo}\p{M}]+(?i:'s|'t|'re|'ve|'m|'ll|'d)?",
    r"[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]+[\p{Ll}\p{Lm}\p{Lo}\p{M}]*(?i:'s|'t|'re|'ve|'m|'ll|'d)?",
    r"\p{N}{1,3}", r" ?[^\s\p{L}\p{N}]+[\r\n/]*", r"\s*[\r\n]+", r"\s+(?!\S)", r"\s+",
])


@lru_cache(maxsize=1)
def encoding():
    path = Path(__file__).parent / "assets/tokenizer/o200k_base.tiktoken"
    if hashlib.sha256(path.read_bytes()).hexdigest() != "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d":
        raise ValueError("모델 입력량 계산 자료를 확인해 주세요.")
    return tiktoken.Encoding(name="career_o200k", pat_str=PATTERN,
                             mergeable_ranks=load_tiktoken_bpe(str(path)), special_tokens={})


def gpt_oss_input_tokens(request_data: dict) -> int:
    payload = json.dumps(request_data, ensure_ascii=False, separators=(",", ":"), default=str)
    # Count the entire messages AND schema; do not discard facts to meet the cap.
    # A 15% margin plus framing allowance covers provider-side formatting differences.
    return math.ceil(len(encoding().encode_ordinary(payload)) * 1.15) + 256
