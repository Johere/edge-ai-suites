#!/bin/bash

MODEL_PATH="${MODEL_PATH:-Qwen/Qwen3.5-9B}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-${MODEL_PATH}}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-32768}"
LOAD_QUANTIZATION="${LOAD_QUANTIZATION:-fp8}"
TENSOR_PARALLEL_SIZE="${TENSOR_PARALLEL_SIZE:-1}"
GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.5}"

echo "HF_HUB_OFFLINE: $HF_HUB_OFFLINE"
echo "LOAD_QUANTIZATION is $LOAD_QUANTIZATION"
echo "TENSOR_PARALLEL_SIZE is $TENSOR_PARALLEL_SIZE"
echo "MODEL_PATH is $MODEL_PATH"
echo "SERVED_MODEL_NAME is $SERVED_MODEL_NAME"
echo "GPU_MEM_UTIL is $GPU_MEM_UTIL"
echo "MAX_MODEL_LEN is $MAX_MODEL_LEN"


python3 "$(dirname "$0")/patch_vllm_video.py"
# Warning:: workaround for image: intel/llm-scaler-vllm:0.14.0-b8.2.1
# `pip list | grep vllm` on that image prints:
#   vllm  0.14.1.dev0+gb17039bcc.d20260430.xpu
# Only that exact build needs the qwen2_vl.py min/max_pixels patch.
VLLM_VERSION="$(pip list 2>/dev/null | awk '/^vllm /{print $2; exit}')"
if [ "$VLLM_VERSION" = "0.14.1.dev0+gb17039bcc.d20260430.xpu" ]; then
    echo "Detected llm-scaler-vllm b8.2.1 (vllm=$VLLM_VERSION); applying patch_llm_scaler_b8.2.1.py"
    python3 "$(dirname "$0")/patch_llm_scaler_b8.2.1.py"
else
    echo "Skipping patch_llm_scaler_b8.2.1.py (vllm=$VLLM_VERSION)"
fi

TORCH_LLM_ALLREDUCE=1 \
VLLM_USE_V1=1 \
VLLM_ALLOW_LONG_MAX_MODEL_LEN=1 \
VLLM_WORKER_MULTIPROC_METHOD=spawn \
python3 -m vllm.entrypoints.openai.api_server \
    --model ${MODEL_PATH} \
    --dtype=float16 \
    --served-model-name ${SERVED_MODEL_NAME} \
    --enforce-eager \
    --port 8000 \
    --host 0.0.0.0 \
    --trust-remote-code \
    --gpu-memory-util=${GPU_MEM_UTIL} \
    --disable-log-requests \
    --max-model-len=${MAX_MODEL_LEN} \
    --block-size 64 \
    --max_num_batched_tokens=8192 \
    --quantization ${LOAD_QUANTIZATION} \
    -tp=${TENSOR_PARALLEL_SIZE} \
    --enable-prefix-caching  \
    --enable-auto-tool-choice \
    --tool-call-parser qwen3_coder \
    --reasoning-parser qwen3 \
    --default-chat-template-kwargs '{"enable_thinking": false}'



    # --allow-deprecated-quantization ipex_awq


# remove `--disable-sliding-window` for VLM models
# --disable-sliding-window \

# when test performance: --no-enable-prefix-caching \

# --kv-cache-dtype {auto,bfloat16,fp8,fp8_ds_mla,fp8_e4m3,fp8_e5m2,fp8_inc}
