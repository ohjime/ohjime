#!/usr/bin/env python3
"""Apply vLLM PR #39018 (fix for issue #38918: Gemma4 on Turing GPUs).

Gemma4's full-attention layers use head_size 512 (sliding layers use 256).
On pre-Ampere GPUs (SM < 8.0, e.g. RTX 2080 Ti / T4) shared memory is
capped at 64 KB per block, but the Triton unified-attention kernel's
default 32-wide KV tile needs 96 KB for head_size 512, so every backend
fails: FLASH_ATTN needs SM >= 8.0, FlashInfer only supports head sizes
up to 256, and TRITON_ATTN / FLEX_ATTENTION die with
``triton.runtime.errors.OutOfResources`` (Required: 98304, limit: 65536).

This applies the maintainer-approved but (as of v0.25.0) unmerged fix
from https://github.com/vllm-project/vllm/pull/39018 verbatim:

* ``triton_unified_attention.py`` — when the padded head size is >= 512
  and the device has < 96 KB of shared memory, drop TILE_SIZE 32 -> 16
  ("Solution 2" in the issue; validated on an RTX 2080 Ti).
* ``flex_attention.py`` — clamp block_m/block_n to 16 in the same case,
  so the fallback backend works too.

Each edit is verify-and-replace on the exact v0.25.0 source: if the base
image no longer matches (tag bump, or the PR finally merged), the build
fails loudly with instructions instead of silently mis-patching.
"""

import sys
from pathlib import Path

import vllm

VLLM_ROOT = Path(vllm.__file__).parent
SENTINEL = "[pr39018]"


def patch_file(path: Path, replacements: list[tuple[str, str]]) -> None:
    src = path.read_text()
    if SENTINEL in src:
        print(f"already patched: {path}")
        return
    for old, new in replacements:
        n = src.count(old)
        if n != 1:
            sys.exit(
                f"ERROR: patch target found {n} times (expected 1) in {path}.\n"
                "The vLLM source no longer matches PR #39018 as vendored here.\n"
                "Check https://github.com/vllm-project/vllm/issues/38918 — if the\n"
                "fix has merged, drop this patch; otherwise update it to the new\n"
                "upstream code."
            )
        src = src.replace(old, new, 1)
    path.write_text(src)

    import py_compile

    py_compile.compile(str(path), doraise=True)  # fail at build, not first request
    print(f"patched: {path}")


# --- vllm/v1/attention/ops/triton_unified_attention.py -------------------

TRITON_FILE = VLLM_ROOT / "v1" / "attention" / "ops" / "triton_unified_attention.py"

TRITON_IMPORT_OLD = "from vllm.triton_utils import tl, triton\n"
TRITON_IMPORT_NEW = (
    "from vllm.triton_utils import tl, triton\n"
    "from vllm.utils.mem_utils import get_max_shared_memory_bytes  # [pr39018]\n"
)

TILE_SIZE_OLD = '''\
    """Select tile size with Gemma3-specific optimization."""
    if _is_gemma3_attention(head_size, sliding_window):
        # Gemma3: use 32 for decode (default is 16)
        return 32

    # Default behavior
    if is_prefill:
        return 32
    # Note: tile size must be at least 32 for fp8 (element_size == 1).
    return 16 if element_size >= 2 else 32
'''

TILE_SIZE_NEW = '''\
    """Select tile size with Gemma3-specific optimization."""
    head_size_padded = triton.next_power_of_2(head_size)

    if _is_gemma3_attention(head_size, sliding_window):
        # Gemma3: use 32 for decode (default is 16)
        tile_size = 32
    else:
        # Note: tile size must be at least 32 for fp8 (element_size == 1).
        tile_size = 32 if is_prefill else 16 if element_size >= 2 else 32

    # Hardware-aware safety check for padded large-head configurations on
    # older GPUs. Triton kernels use the padded head size when determining
    # resource usage, so apply the fallback based on head_size_padded.
    if tile_size == 32 and head_size_padded >= 512 and element_size >= 2:
        if current_platform.is_cuda():
            max_shared_memory = get_max_shared_memory_bytes()
        else:
            # Fallback for non-CUDA platforms (e.g., Intel XPU, ROCm)
            max_shared_memory = 65536

        if max_shared_memory < 98304:
            tile_size = 16

    return tile_size
'''

# --- vllm/v1/attention/backends/flex_attention.py -------------------------

FLEX_FILE = VLLM_ROOT / "v1" / "attention" / "backends" / "flex_attention.py"

FLEX_OLD = '''\
            if max_shared_memory < 144 * 1024:
'''

FLEX_NEW = '''\
            head_dim = query.shape[-1]  # [pr39018]
            if head_dim >= 512 and max_shared_memory < 98304:
                block_m_candidate = min(block_m_candidate, 16)
                block_n_candidate = min(block_n_candidate, 16)
            elif max_shared_memory < 144 * 1024:
'''


def main() -> None:
    patch_file(
        TRITON_FILE,
        [(TRITON_IMPORT_OLD, TRITON_IMPORT_NEW), (TILE_SIZE_OLD, TILE_SIZE_NEW)],
    )
    patch_file(FLEX_FILE, [(FLEX_OLD, FLEX_NEW)])


if __name__ == "__main__":
    main()
