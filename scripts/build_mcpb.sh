#!/usr/bin/env bash
# Build dist/mysql-audit.mcpb: the manifest plus the package sources, run by uv.
set -euo pipefail
cd "$(dirname "$0")/.."
stage=$(mktemp -d)
cp mcpb/manifest.json pyproject.toml README.md LICENSE "$stage"/
cp -r src "$stage"/
find "$stage" -name __pycache__ -prune -exec rm -rf {} +
mkdir -p dist
npx -y @anthropic-ai/mcpb@2 validate "$stage/manifest.json"
npx -y @anthropic-ai/mcpb@2 pack "$stage" dist/mysql-audit.mcpb
