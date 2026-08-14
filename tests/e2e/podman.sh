#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ENGINE="${E2E_ENGINE:-podman}"
IMAGE="${E2E_IMAGE:-localhost/legion-powerctl-e2e:latest}"

if ! command -v "$ENGINE" >/dev/null 2>&1; then
    printf 'e2e: %s is not installed. Set E2E_ENGINE=docker, or install podman.\n' "$ENGINE" >&2
    exit 1
fi

"$ENGINE" build --tag "$IMAGE" --file "$ROOT_DIR/tests/e2e/Containerfile" "$ROOT_DIR"

exec "$ENGINE" run --rm --tty \
    --security-opt label=disable \
    --volume "$ROOT_DIR:/src:ro" \
    --tmpfs /tmp:exec,size=512m \
    --workdir /src \
    --env "E2E_TIMEOUT=${E2E_TIMEOUT:-300}" \
    --env "E2E_WAIT=${E2E_WAIT:-20}" \
    "$IMAGE" bash tests/e2e/run.sh "$@"
