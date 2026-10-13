#!/bin/bash

# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#
# videostream-analytics standalone setup: prepares the prefilter model, seeds
# your own persistent configuration, and optionally drives docker compose.
#
# Usage:
#   bash setup_vsa.sh              prepare model + seed config, print exports
#   bash setup_vsa.sh up|down|logs prepare, then pass through to docker compose
#   source setup_vsa.sh            define vsa_* functions + defaults, no actions
#                                  (this is how setup_docker.sh reuses it)
#
# Environment (all optional; pre-exported values — e.g. from docker/set_env.sh
# in the full smart-community stack — are honored):
#   MODEL_DIR               read-only model root bind-mounted into the container.
#                           Default ${HOME}/models/openvino.
#   PREFILTER_MODEL         OpenVINO IR .xml, must live under MODEL_DIR.
#                           Default ${MODEL_DIR}/yolo11s/FP16/yolo11s.xml.
#   VIDEOSTREAM_CACHE_HOST  your config home. Seeded once, never overwritten.
#                           Default ${HOME}/.cache/.videostream-analytics.
#   VIDEOSTREAM_CONFIG_FILE default ${VIDEOSTREAM_CACHE_HOST}/config.yaml.

VSA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Inherit the caller's colors when sourced (setup_docker.sh sets these).
RED="${RED:-\033[0;31m}"
YELLOW="${YELLOW:-\033[0;33m}"
NC="${NC:-\033[0m}"

MODEL_DIR="${MODEL_DIR:-${HOME}/models/openvino}"
DEFAULT_PREFILTER_MODEL="${MODEL_DIR}/yolo11s/FP16/yolo11s.xml"
VIDEOSTREAM_CACHE_HOST="${VIDEOSTREAM_CACHE_HOST:-${HOME}/.cache/.videostream-analytics}"
VIDEOSTREAM_CONFIG_FILE="${VIDEOSTREAM_CONFIG_FILE:-${VIDEOSTREAM_CACHE_HOST}/config.yaml}"

# Validate (and auto-prepare if missing) the prefilter IR pair. Sets the
# script-level VSA_PREFILTER_MODEL / VSA_MODEL_DIR to resolved absolute paths.
vsa_prepare_model() {
  local prefilter_bin prefilter_model model_dir

  prefilter_model="${PREFILTER_MODEL:-$DEFAULT_PREFILTER_MODEL}"
  case "$prefilter_model" in
    '~') prefilter_model="$HOME" ;;
    '~/'*) prefilter_model="$HOME/${prefilter_model#~/}" ;;
  esac

  if [[ "$prefilter_model" != *.xml ]]; then
    echo "PREFILTER_MODEL must reference a .xml OpenVINO IR; using ${DEFAULT_PREFILTER_MODEL}."
    prefilter_model="$DEFAULT_PREFILTER_MODEL"
  fi

  prefilter_model="$(realpath -m "$prefilter_model")"
  prefilter_bin="${prefilter_model%.xml}.bin"
  if [[ ! -s "$prefilter_model" || ! -s "$prefilter_bin" ]]; then
    echo "Prefilter model is missing or incomplete: ${prefilter_model}"
    echo "Preparing the YOLO11s OpenVINO IR automatically..."
    PREFILTER_MODEL="$prefilter_model" bash "${VSA_DIR}/scripts/helpers/prepare_yolo11s.sh"
  fi

  if [[ ! -s "$prefilter_model" || ! -s "$prefilter_bin" ]]; then
    echo -e "${RED}Error: prefilter preparation did not create a complete IR pair: ${prefilter_model}${NC}"
    return 1
  fi
  prefilter_model="$(realpath -e "$prefilter_model")"

  model_dir="$(realpath -m "$MODEL_DIR")"
  if [[ "$prefilter_model" != "$model_dir/"* ]]; then
    echo -e "${RED}Error: PREFILTER_MODEL must be under MODEL_DIR (${model_dir}) so the container can read it.${NC}"
    return 1
  fi

  VSA_PREFILTER_MODEL="$prefilter_model"
  VSA_MODEL_DIR="$model_dir"
}

# Seed the user-owned config once; never overwrite it afterwards. Then maintain
# the config/config.yaml symlink so the familiar in-tree path edits the same
# live file.
vsa_seed_config() {
  mkdir -p "$VIDEOSTREAM_CACHE_HOST"
  VIDEOSTREAM_CONFIG_FILE="$(realpath -m "$VIDEOSTREAM_CONFIG_FILE")"

  if [[ -f "$VIDEOSTREAM_CONFIG_FILE" ]]; then
    echo "Keeping your existing configuration: ${VIDEOSTREAM_CONFIG_FILE}"
  else
    # Pin the absolute, validated paths the container will see. The example
    # carries ${MODEL_DIR} placeholders; writing the resolved values here keeps
    # the deployment working even if the variable is not exported into the
    # container. The model the deployment defaults to is retargeted in the
    # registry, which is the only place a model path is accepted from.
    PREFILTER_MODEL="$VSA_PREFILTER_MODEL" MODEL_DIR="$VSA_MODEL_DIR" \
      python3 - "${VSA_DIR}/config/config.yaml.example" "$VIDEOSTREAM_CONFIG_FILE" <<'PY'
import os
import sys
import tempfile

import yaml

source_path, output_path = sys.argv[1:]
with open(source_path, encoding="utf-8") as source_file:
    config = yaml.safe_load(source_file) or {}

config["model_dir"] = os.environ["MODEL_DIR"]
defaults = config.setdefault("defaults", {}).setdefault("prefilter", {})
name = defaults.get("model") or "default"
defaults["model"] = name
registry = config.setdefault("prefilter_models", {})
entry = registry.setdefault(name, {})
entry.setdefault("kind", "detection")
entry.setdefault("backend", "openvino")
entry["model_path"] = os.environ["PREFILTER_MODEL"]

output_dir = os.path.dirname(output_path)
with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output_dir, delete=False) as output_file:
    yaml.safe_dump(config, output_file, default_flow_style=False, sort_keys=False)
    temporary_path = output_file.name
os.replace(temporary_path, output_path)
PY
    echo "Seeded configuration: ${VIDEOSTREAM_CONFIG_FILE} (from config/config.yaml.example — now yours, setup will not touch it again)"
  fi

  vsa_link_config
}

vsa_link_config() {
  local link="${VSA_DIR}/config/config.yaml"
  if [[ -L "$link" ]]; then
    if [[ "$(readlink "$link")" != "$VIDEOSTREAM_CONFIG_FILE" ]]; then
      ln -sfn "$VIDEOSTREAM_CONFIG_FILE" "$link"
      echo "Updated symlink: ${link} -> ${VIDEOSTREAM_CONFIG_FILE}"
    fi
  elif [[ -e "$link" ]]; then
    echo -e "${YELLOW}Warning: ${link} exists as a regular file; leaving it alone.${NC}"
    echo "Your live configuration is ${VIDEOSTREAM_CONFIG_FILE} — edit that file instead."
  else
    ln -s "$VIDEOSTREAM_CONFIG_FILE" "$link"
    echo "Linked ${link} -> ${VIDEOSTREAM_CONFIG_FILE} (edit either path; same file)"
  fi
}

vsa_prepare() {
  vsa_prepare_model || return 1
  vsa_seed_config || return 1
  export PREFILTER_MODEL="$VSA_PREFILTER_MODEL"
  export MODEL_DIR="$VSA_MODEL_DIR"
  export VIDEOSTREAM_CACHE_HOST VIDEOSTREAM_CONFIG_FILE
  echo "Using prefilter model: ${PREFILTER_MODEL}"
  echo "Using videostream configuration: ${VIDEOSTREAM_CONFIG_FILE}"
}

# Dual mode: sourced → definitions only; executed → prepare, then subcommand.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  set -e
  vsa_prepare
  case "${1:-}" in
    "")
      echo
      echo "To start videostream-analytics:  bash $0 up"
      ;;
    up | down | logs)
      docker compose -f "${VSA_DIR}/docker/docker-compose.yaml" "$@"
      ;;
    *)
      echo -e "${RED}Unknown subcommand: $1 (expected: up | down | logs)${NC}" >&2
      exit 2
      ;;
  esac
fi
