#!/usr/bin/env python3
# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""Convert a `## SECTION` prompt markdown file into the anchored task format.

The video-summary service's `mode: full` registration requires Python-style
anchors:

    GLOBAL_PROMPT = '''
    ...
    '''

Prompts staged for the `use_case_register` MCP tool are written as markdown
headings instead (`## GLOBAL_PROMPT`), which POSTs straight to /v1/tasks as
HTTP 422 missing_anchors. This bridges the two so one file stays the source of
truth for both paths.

Splitting is done only on lines that are exactly one of the four known anchor
names: prompt bodies contain their own `## ...` headings (`## 任务:`,
`## 输出格式:`), and a generic "split on ##" would shred them.

A file that already uses anchors is passed through untouched, so the caller can
run everything through this filter without knowing which format it has.

Usage:
  prompt_md_to_task.py PATH            # converted text on stdout
"""

from __future__ import annotations

import re
import sys

ANCHORS = ("GLOBAL_PROMPT", "MACRO_CHUNK_PROMPT", "LOCAL_PROMPT", "T_MINUS_1_PROMPT")
HEADING_RE = re.compile(rf"^##\s+({'|'.join(ANCHORS)})\s*$")
# The service only insists on these two; the others are auto-filled when absent.
REQUIRED = ("GLOBAL_PROMPT", "LOCAL_PROMPT")


def convert(text: str) -> str:
    if any(re.search(rf"^{anchor}\s*=", text, re.MULTILINE) for anchor in ANCHORS):
        return text  # already in anchored form

    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.split("\n"):
        match = HEADING_RE.match(line)
        if match:
            current = match.group(1)
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)

    missing = [name for name in REQUIRED if not sections.get(name)]
    if missing:
        raise SystemExit(
            f"error: no '## {missing[0]}' heading and no anchored form found — "
            f"missing {', '.join(missing)}"
        )

    blocks = []
    for name in ANCHORS:
        if name not in sections:
            continue
        body = "\n".join(sections[name]).strip("\n")
        if not body:
            continue
        if "'''" in body:
            raise SystemExit(f"error: section {name} contains ''' and cannot be quoted")
        blocks.append(f"{name} = '''\n{body}\n'''")
    return "\n\n".join(blocks) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    with open(argv[1], encoding="utf-8") as handle:
        sys.stdout.write(convert(handle.read()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
