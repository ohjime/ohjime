# vLLM with Gemma 4 support for Turing GPUs (SM 7.5, e.g. RTX 2080 Ti).
#
# Stock vLLM cannot run Gemma 4 on pre-Ampere GPUs: its full-attention
# layers use head_size 512, and every attention backend either requires
# SM >= 8.0 (FlashAttention), tops out at head size 256 (FlashInfer), or
# needs 96 KB of shared memory per block against Turing's 64 KB limit
# (TRITON_ATTN / FLEX_ATTENTION) — see
# https://github.com/vllm-project/vllm/issues/38918.
#
# This image bakes in the maintainer-approved but not-yet-merged upstream
# fix (https://github.com/vllm-project/vllm/pull/39018): shrink the
# Triton KV tile from 32 to 16 when head_size >= 512 on GPUs with less
# than 96 KB of shared memory. Validated on an RTX 2080 Ti.
#
# The patch script fails the build if the vLLM sources stop matching, so
# bumping the base tag below surfaces immediately instead of silently
# shipping an unpatched image. If PR #39018 has merged into the new tag,
# delete this patch layer instead.
FROM vllm/vllm-openai:v0.25.0

COPY patches/apply_pr39018.py /opt/turing-patch/apply_pr39018.py
RUN python3 /opt/turing-patch/apply_pr39018.py

# Entrypoint stays `vllm serve`; model and flags come from compose.yaml.
