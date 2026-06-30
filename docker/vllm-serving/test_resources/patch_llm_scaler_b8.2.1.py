import re
import os

file_path = "/usr/local/lib/python3.12/dist-packages/vllm/model_executor/models/qwen2_vl.py"

# In llm-scaler-vllm:0.14.0-b8.2.1 there are TWO call sites that read
# `image_processor.min_pixels` / `image_processor.max_pixels`. The newer
# Qwen2VLImageProcessor only exposes the limits as `size["shortest_edge"]` /
# `size["longest_edge"]`, so any access to those attributes raises
# AttributeError on engine startup. We rewrite both sites in place.

# Site 1 (around line 844-845, inside smart_resize() call):
#     min_pixels=image_processor.min_pixels,
#     max_pixels=image_processor.max_pixels,
PATTERN_1 = re.compile(
    r"min_pixels=image_processor\.min_pixels,\s*\n"
    r"(\s*)max_pixels=image_processor\.max_pixels,"
)
REPLACEMENT_1 = (
    'min_pixels=image_processor.size["shortest_edge"],\n'
    r'\1max_pixels=image_processor.size["longest_edge"],'
)

# Site 2 (around line 944, inside get_image_size_with_most_features()):
#     max_pixels = image_processor.max_pixels or image_processor.size["longest_edge"]
# The `or` fallback never triggers because attribute access fails first.
PATTERN_2 = re.compile(
    r"max_pixels = image_processor\.max_pixels or image_processor\.size\[\"longest_edge\"\]"
)
REPLACEMENT_2 = 'max_pixels = image_processor.size["longest_edge"]'


def patch(content: str, label: str, pattern: re.Pattern, replacement: str,
          already_marker: str) -> tuple[str, str]:
    if already_marker in content and pattern.search(content) is None:
        return content, f"[{label}] already patched"
    if pattern.search(content) is None:
        return content, f"[{label}] target not found"
    new_content, n = pattern.subn(replacement, content, count=1)
    return new_content, f"[{label}] patched ({n} occurrence)"


if not os.path.exists(file_path):
    print(f"{file_path} does not exist, skipping", flush=True)
else:
    with open(file_path, "r") as f:
        content = f.read()
    original = content

    content, msg1 = patch(
        content,
        "site1:smart_resize",
        PATTERN_1,
        REPLACEMENT_1,
        already_marker='min_pixels=image_processor.size["shortest_edge"]',
    )
    print(msg1, flush=True)

    content, msg2 = patch(
        content,
        "site2:get_image_size_with_most_features",
        PATTERN_2,
        REPLACEMENT_2,
        already_marker=(
            'max_pixels = image_processor.size["longest_edge"]\n'
        ),
    )
    print(msg2, flush=True)

    if content != original:
        with open(file_path, "w") as f:
            f.write(content)
        print(f"Wrote patched {file_path}", flush=True)
    else:
        print(f"No changes written to {file_path}", flush=True)
