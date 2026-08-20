# Historical Note

This file formerly contained machine-specific manual commands. They are
superseded by the portable workflow in [README.md](README.md): package the
snapshot, extract it, and run `bash deploy.sh`.

For component-wide prerequisites and service setup, see the public [Get Started
guide](https://github.com/open-edge-platform/edge-ai-suites/blob/main/metro-ai-suite/agentic-smart-community/docs/user-guide/get-started.md).

## Package
```bash
bash demo/snapshot_0818/package.sh /tmp/snapshot_0818.tar.gz
```

## Deploy
```bash
tar -xzf snapshot_0818.tar.gz
cd snapshot_0818
bash deploy.sh
```