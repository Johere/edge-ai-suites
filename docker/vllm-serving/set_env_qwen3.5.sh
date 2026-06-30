export VIDEO_GROUP_ID=$(getent group video | awk -F: '{printf "%s\n", $3}')
export RENDER_GROUP_ID=$(getent group render | awk -F: '{printf "%s\n", $3}')

HF_HOME=${HF_HOME:=~/.cache/huggingface}
export HF_HOME

export MAX_MODEL_LEN=20000
# Qwen/Qwen3.5-35B-A3B-FP8
# Qwen/Qwen3.5-35B-A3B
# Qwen/Qwen3.5-9B 
# Qwen/Qwen3.5-4B 
export LLM_MODEL=Qwen/Qwen3-VL-8B-Instruct
export MODEL_PATH=${LLM_MODEL}
export SERVED_MODEL_NAME=${LLM_MODEL}

export LOAD_QUANTIZATION=fp8
export VLLM_SERVICE_PORT=41091
export GPU_MEM_UTIL=0.3

# base_dir=$(cd "$(dirname "$0")"; pwd)
# data_dir=$(cd "$base_dir/../test_resources"; pwd)
# export data_dir=/home/user/linjiaojiao/large-model-quickstart/vllm-ipex/test_resources
