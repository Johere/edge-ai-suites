# videostream-analytics

RTSP capture and motion segmentation service with an optional OpenVINO™
detector as a prefilter. Posts motion/static/recording events to a webhook
(the smart-community MCP server in the full stack).

## Quick start (standalone)

```bash
bash setup_vsa.sh        # validate/prepare the prefilter model, seed your config
bash setup_vsa.sh up     # docker compose up
curl -s localhost:8999/capabilities/prefilter | jq '.models[].name'
bash setup_vsa.sh down
```

`setup_vsa.sh` needs nothing from the rest of the smart-community repository.
Pre-exported environment (`MODEL_DIR`, `PREFILTER_MODEL`,
`VIDEOSTREAM_CACHE_HOST`) is honored; sourcing the script instead defines the
`vsa_*` functions without running anything (this is how the full stack's
`setup_docker.sh` reuses it).

## Your configuration

The live configuration is `${VIDEOSTREAM_CACHE_HOST}/config.yaml` (default
`~/.cache/.videostream-analytics/config.yaml`). It is seeded once from
`config/config.yaml.example` and never overwritten by re-running setup — your
`prefilter_models` entries and tuned `defaults` blocks are safe. The
`config/config.yaml` symlink in this directory points at the same file, so the
familiar in-tree path keeps working for edits.

A plain `docker compose -f docker/docker-compose.yaml up` without setup still
works: it mounts the example template (defaults only, edits not persisted).

## Tests

```bash
.venv/bin/python -m pytest tests/unit -q   # unit suite
bash tests/test_setup_vsa.sh               # setup_vsa.sh contract tests
```
