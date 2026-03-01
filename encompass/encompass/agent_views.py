"""Read-only ENC API endpoints for encapsule runtime."""

from __future__ import annotations

import logging
import os
import subprocess

from django.http import HttpResponse
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from . import enc_data


logger = logging.getLogger(__name__)


def _yaml_http_response(data, status=200):
    return HttpResponse(
        enc_data.yaml_response_payload(data),
        status=status,
        content_type="text/yaml",
    )


def _method_not_allowed(_request, allowed):
    response = HttpResponse(status=405)
    response["Allow"] = ", ".join(allowed)
    return response


def _request_client_ip(request) -> str:
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


@csrf_exempt
def healthz(_request):
    """
    Simple health check endpoint to verify that encapsule runtime is up and responsive.
    """
    return JsonResponse({"ping": "pong!", "status": "encapsule is up!"}, status=200)


@csrf_exempt
def hosts_collection(request):
    """
    Endpoint to retrieve the collection of hosts.
    """
    if request.method != "GET":
        return _method_not_allowed(request, ["GET"])

    hosts = enc_data.load_map("hosts")
    return _yaml_http_response(list(hosts.keys()))


@csrf_exempt
def hosts_item(request, fqdn):
    """
    Endpoint to retrieve a specific host by its fully qualified domain name (FQDN).
    """
    if request.method != "GET":
        return _method_not_allowed(request, ["GET"])

    hosts = enc_data.load_map("hosts")
    groups = enc_data.load_map("groups")
    host = enc_data.resolve_host(hosts, groups, fqdn)
    return _yaml_http_response(host)


@csrf_exempt
def groups_collection(request):
    """
    Endpoint to retrieve the collection of groups.
    """
    if request.method != "GET":
        return _method_not_allowed(request, ["GET"])

    groups = enc_data.load_map("groups")
    return _yaml_http_response(list(groups.keys()))


@csrf_exempt
def groups_item(request, name):
    """
    Endpoint to retrieve a specific group by its name.
    """
    if request.method != "GET":
        return _method_not_allowed(request, ["GET"])

    groups = enc_data.load_map("groups")
    if name not in groups:
        return HttpResponse(status=404)
    return _yaml_http_response(groups.get(name))


@csrf_exempt
def sync_from_git(request):
    """
    Endpoint to trigger a sync from the git repository.
    """
    token = str(os.environ.get("ENCAPSULE_SYNC_TOKEN", "")).strip()
    client_ip = _request_client_ip(request)
    if request.method != "POST":
        return _method_not_allowed(request, ["POST"])
    if not token:
        logger.error("enCapsule sync trigger rejected from %s: token not configured", client_ip)
        return JsonResponse(
            {"error": "Forbidden", "message": "Sync token is not configured"},
            status=403,
        )

    request_token = request.headers.get("X-Encapsule-Token", "")
    if request_token != token:
        logger.warning("enCapsule sync trigger rejected from %s: invalid token", client_ip)
        return JsonResponse(
            {"error": "Forbidden", "message": "Invalid encapsule sync token"},
            status=403,
        )

    logger.info("enCapsule sync trigger received from %s", client_ip)

    result = subprocess.run(  # nosec B603
        ["/usr/local/bin/git-setup.sh"],
        check=False,
        capture_output=True,
        text=True,
    )
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    if stdout:
        logger.info("enCapsule sync git-setup stdout:\n%s", stdout)
    if stderr:
        if result.returncode == 0:
            logger.warning("enCapsule sync git-setup stderr:\n%s", stderr)
        else:
            logger.error("enCapsule sync git-setup stderr:\n%s", stderr)

    if result.returncode != 0:
        logger.error(
            "enCapsule sync failed from %s with return code %s",
            client_ip,
            result.returncode,
        )
        return JsonResponse(
            {
                "status": "error",
                "returncode": result.returncode,
                "stderr": stderr,
            },
            status=500,
        )

    logger.info("enCapsule sync completed successfully for trigger from %s", client_ip)

    return JsonResponse(
        {
            "status": "ok",
            "message": "ENC data synced from git",
            "stdout": stdout,
        },
        status=200,
    )
