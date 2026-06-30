# Auto-detect host IP for no_proxy
HOST_IP=$(ip route get 1 2>/dev/null | awk '{print $7; exit}')
export no_proxy=localhost,127.0.0.1,vllm-ipex-serving,multilevel-video-understanding,${HOST_IP}

# =========================================================================
# Service: vllm-ipex-serving
# =========================================================================
export VIDEO_GROUP_ID=$(getent group video | awk -F: '{printf "%s\n", $3}')
export RENDER_GROUP_ID=$(getent group render | awk -F: '{printf "%s\n", $3}')

# HF_HOME is the host directory mounted into the container at /llm/.cache/huggingface.
HF_HOME=${HF_HOME:=~/models/huggingface}
export HF_HOME

export MAX_MODEL_LEN=61440  # 32k:32768, 48k:49152, 96k:98304, 60k: 61440
# Qwen/Qwen3.5-9B, Qwen/Qwen3.5-35B-A3B, QuantTrio/Qwen3.5-9B-AWQ, QuantTrio/Qwen3.5-35B-A3B-AWQ
export LLM_MODEL=Qwen/Qwen3.5-35B-A3B
export MODEL_PATH=${LLM_MODEL}
export SERVED_MODEL_NAME=${LLM_MODEL}

if echo "${LLM_MODEL}" | grep -qi "awq"; then
    export LOAD_QUANTIZATION=awq
else
    export LOAD_QUANTIZATION=fp8  # sym_int4,fp8
fi
export VLLM_SERVICE_PORT=41091
export GPU_MEM_UTIL=0.7  

# =========================================================================
# Service: multilevel-video-understanding
# =========================================================================
export REGISTRY_URL=intel/
export REGISTRY=${REGISTRY_URL}
export TAG=smarthome
# Use app-network sharing with `vllm-ipex-serving`
export VLM_BASE_URL="http://10.67.116.201:41091/v1"
export LLM_BASE_URL="http://10.67.116.201:41091/v1"
export SMARTHOME_DATA_DIR=/mnt/disk1/projects/intel-innersource/openclaw-demo/agent-ai.smarthome/phase2-prototype-demo/data 
export VLM_MODEL_NAME=${LLM_MODEL}
export LLM_MODEL_NAME=${LLM_MODEL}
export SERVICE_PORT=8192

export DEFAULT_MAX_TOKENS=512
export ENABLE_THINKING=false
export VIDEO_FRAME_HEIGHT=378
export VIDEO_FRAME_WIDTH=504
export DEFAULT_TEMPERATURE=0.0

# Runtime prompt registry cache. Must exist as a user-owned dir BEFORE
# `docker compose up`, else docker creates it as root.
export VIDEO_SUMMARY_CACHE_HOST=${VIDEO_SUMMARY_CACHE_HOST:-${HOME}/.cache/.multilevel-video-understanding}
mkdir -p "$VIDEO_SUMMARY_CACHE_HOST/tasks"

# clean up mem fragments
# $ sync
# $ sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'
