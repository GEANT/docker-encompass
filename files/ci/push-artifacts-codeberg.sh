#!/bin/bash
#
set -euo pipefail
#set -x

TOOL_NAME="$1"
TOOL_DIR="$2"
DELETE_EXISTING="${3:-}"

# Read CI-provided variables directly from the environment.
CODEBERG_OWNER="${CODEBERG_OWNER:?missing CODEBERG_OWNER}"
CODEBERG_HOST="${CODEBERG_HOST:?missing CODEBERG_HOST}"
CODEBERG_USER="${CODEBERG_USER:?missing CODEBERG_USER}"
CODEBERG_TOKEN="${CODEBERG_TOKEN:?missing CODEBERG_TOKEN}"
CI_COMMIT_TAG="${CI_COMMIT_TAG:?missing CI_COMMIT_TAG}"
export GOTOOLCHAIN="${GOTOOLCHAIN:-local}"

if ! command -v upx >/dev/null 2>&1; then
    echo "ERROR: upx is required to compress linux artifacts but was not found in PATH" >&2
    exit 1
fi

mkdir -p "dist/${TOOL_NAME}"
pushd "$TOOL_DIR" >/dev/null

go mod download

function build_artifact {
    local goos="$1"
    local goarch="$2"
    local binary_path="../../dist/${TOOL_NAME}/${TOOL_NAME}-${goos}-${goarch}"
    GOOS="$goos" GOARCH="$goarch" CGO_ENABLED=0 \
        go build -trimpath -ldflags "-s -w" -o "$binary_path" .

    if [ "$TOOL_NAME" = "encryptor" ] && [ "$goos" = "linux" ]; then
        upx -q -9 "$binary_path"
    fi
}

build_artifact linux amd64
build_artifact linux arm64
build_artifact darwin arm64

popd >/dev/null

chmod +x "dist/${TOOL_NAME}/${TOOL_NAME}-"*
sha256sum "dist/${TOOL_NAME}/${TOOL_NAME}-"* >"dist/${TOOL_NAME}/SHA256SUMS"

CODEBERG_OWNER_LC="$(printf '%s' "$CODEBERG_OWNER" | tr '[:upper:]' '[:lower:]')"
PACKAGE_BASE="https://${CODEBERG_HOST}/api/packages/${CODEBERG_OWNER_LC}/generic/${TOOL_NAME}"

for package_version in "$CI_COMMIT_TAG" latest; do
    if [ "$DELETE_EXISTING" = "true" ]; then
        delete_url="${PACKAGE_BASE}/${package_version}"
        delete_status_code="$(curl -sS -o "/tmp/codeberg-delete-${TOOL_NAME}.log" -w "%{http_code}" \
            --user "${CODEBERG_USER}:${CODEBERG_TOKEN}" \
            -X DELETE \
            "$delete_url")"

        if [ "$delete_status_code" = "200" ] || [ "$delete_status_code" = "202" ] || [ "$delete_status_code" = "204" ]; then
            echo "Deleted existing package version ${TOOL_NAME}/${package_version} to allow re-upload"
        elif [ "$delete_status_code" = "404" ]; then
            echo "Package version ${TOOL_NAME}/${package_version} does not exist; proceeding with upload"
        else
            echo "ERROR: failed to delete existing package version ${TOOL_NAME}/${package_version} (HTTP ${delete_status_code})" >&2
            cat "/tmp/codeberg-delete-${TOOL_NAME}.log" >&2 || true
            exit 1
        fi
    fi

    for file in "dist/${TOOL_NAME}"/*; do
        asset_name="$(basename "$file")"
        upload_url="${PACKAGE_BASE}/${package_version}/${asset_name}"

        status_code="$(curl -sS -o "/tmp/codeberg-upload-${TOOL_NAME}.log" -w "%{http_code}" \
            --user "${CODEBERG_USER}:${CODEBERG_TOKEN}" \
            --upload-file "$file" \
            "$upload_url")"

    if [ "$status_code" = "201" ] || [ "$status_code" = "200" ]; then
        echo "Uploaded ${asset_name} to Codeberg package ${TOOL_NAME}/${package_version}"
        continue
    fi

    if [ "$status_code" = "409" ]; then
        echo "Package file ${asset_name} already exists in ${TOOL_NAME}/${package_version}; skipping"
        continue
    fi

    echo "ERROR: failed to upload ${asset_name} to Codeberg package ${TOOL_NAME}/${package_version} (HTTP ${status_code})" >&2
    cat "/tmp/codeberg-upload-${TOOL_NAME}.log" >&2 || true
    exit 1
  done
done
