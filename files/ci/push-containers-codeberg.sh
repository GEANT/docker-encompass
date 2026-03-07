#!/bin/bash
set -euo pipefail

# Read CI-provided variables directly from the environment.
AFACTORY_TOKEN="${AFACTORY_TOKEN:?missing AFACTORY_TOKEN}"
AFACTORY_USER="${AFACTORY_USER:?missing AFACTORY_USER}"
AFACTORY_HOST="${AFACTORY_HOST:?missing AFACTORY_HOST}"
CODEBERG_OWNER="${CODEBERG_OWNER:?missing CODEBERG_OWNER}"
CODEBERG_HOST="${CODEBERG_HOST:?missing CODEBERG_HOST}"
CODEBERG_USER="${CODEBERG_USER:?missing CODEBERG_USER}"
CODEBERG_TOKEN="${CODEBERG_TOKEN:?missing CODEBERG_TOKEN}"
CODEBERG_REPO="${CODEBERG_REPO:?missing CODEBERG_REPO}"
CI_COMMIT_TAG="${CI_COMMIT_TAG:?missing CI_COMMIT_TAG}"
SERVICE_NAME="${SERVICE_NAME:?missing SERVICE_NAME}"
export GOTOOLCHAIN="${GOTOOLCHAIN:-local}"

[ "$SERVICE_NAME" = "encompass" ] && bash ./files/deployment-stuff/pre-build.sh
printf '%s' "$AFACTORY_TOKEN" | docker login -u "$AFACTORY_USER" --password-stdin "$AFACTORY_HOST"
printf '%s' "$CODEBERG_TOKEN" | docker login -u "$CODEBERG_USER" --password-stdin "$CODEBERG_HOST"

docker build --no-cache --build-arg CACHEBUST="$(date +%s)" -f Dockerfiles/"$SERVICE_NAME" -t "$SERVICE_NAME:$CI_COMMIT_TAG" .

LOCAL_IMAGE="$SERVICE_NAME:$CI_COMMIT_TAG"
if ! docker image inspect "$LOCAL_IMAGE" >/dev/null 2>&1; then
  echo "ERROR: built image '$LOCAL_IMAGE' not found" >&2
  exit 1
fi

REMOTE_BASE="$AFACTORY_HOST/geant-devops-docker/$SERVICE_NAME"
URL_BASE="${AFACTORY_HOST}/artifactory/geant-devops-docker/${SERVICE_NAME}"
CODEBERG_REMOTE_BASE="${CODEBERG_HOST}/${CODEBERG_OWNER}/${CODEBERG_REPO}/${SERVICE_NAME}"

for DOCKER_TAG in "$CI_COMMIT_TAG" latest; do
  curl -u "${AFACTORY_USER}:${AFACTORY_TOKEN}" -X DELETE "https://${URL_BASE}:${DOCKER_TAG}" || true
  docker tag "$LOCAL_IMAGE" "${REMOTE_BASE}:${DOCKER_TAG}"
  docker push "${REMOTE_BASE}:${DOCKER_TAG}"

  docker tag "$LOCAL_IMAGE" "${CODEBERG_REMOTE_BASE}:${DOCKER_TAG}"
  docker push "${CODEBERG_REMOTE_BASE}:${DOCKER_TAG}"
done
