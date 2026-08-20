#!/usr/bin/env bash
# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#
# Create the standalone archive. The package omits local runtime state and
# generated media, while retaining the source scripts, timelines, and prompts.
set -euo pipefail

SNAPSHOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_PATH="${1:-$(dirname "$SNAPSHOT_DIR")/snapshot_0818.tar.gz}"
PACKAGE_NAME="snapshot_0818"

tar --create --gzip --file "$OUTPUT_PATH" \
  --directory "$(dirname "$SNAPSHOT_DIR")" \
  --exclude-from="$SNAPSHOT_DIR/.packageignore" \
  "$PACKAGE_NAME"

echo "Created standalone package: $OUTPUT_PATH"