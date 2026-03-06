"""Django-native ENC API endpoints."""

from __future__ import annotations

import os

from django.http import HttpResponse
from django.http import JsonResponse
from django.http import QueryDict
from django.views.decorators.csrf import csrf_exempt
import yaml
from csr_store import csr_attributes

from . import enc_data


def _yaml_http_response(data, status=200):
    """
    Helper to return a YAML response with the given data and HTTP status.
    """
    return HttpResponse(
        enc_data.yaml_response_payload(data),
        status=status,
        content_type="text/yaml",
    )


def _request_form(request):
    """
    Helper to extract form data from a request.
    """
    if request.method == "POST":
        return request.POST
    return QueryDict(request.body.decode("utf-8"), mutable=False)


def _is_public_proxy_request(request):
    """
    Helper to determine if the request is coming from a public proxy.
    """
    return bool(request.headers.get("X-External-Proxy"))


def _csr_attributes_yaml_response(entity_name: str):
    """Build YAML payload for CSR custom_attributes response."""
    challenge_password, _created = csr_attributes.get_or_create(entity_name)
    payload = {
        "custom_attributes": {
            "challengePassword": challenge_password,
        }
    }
    return HttpResponse(
        yaml.safe_dump(payload, sort_keys=False, explicit_start=True),
        status=200,
        content_type="text/yaml",
    )


def _require_csr_api_token(request):
    """Validate CSR API token for externally exposed CSR endpoints."""
    configured_token = str(os.environ.get("CSR_API_KEY", "")).strip()
    if not configured_token:
        return JsonResponse(
            {"error": "Forbidden", "message": "CSR API token is not configured"},
            status=403,
        )

    request_token = str(request.headers.get("X-CSR-API-KEY", "")).strip()
    if request_token != configured_token:
        return JsonResponse(
            {"error": "Forbidden", "message": "Invalid CSR API token"},
            status=403,
        )

    return None


@csrf_exempt
def healthz(_request):
    """
    Health check endpoint for Kubernetes and other monitoring tools.
    """
    return JsonResponse({"ping": "pong!", "status": "ENC is up!"}, status=200)


@csrf_exempt
def hosts_collection(request):
    """
    Handle GET and POST requests for the /hosts collection endpoint.
    GET returns a YAML list of all host FQDNs.
    """
    if request.method == "GET":
        hosts = enc_data.load_map("hosts")
        return _yaml_http_response(list(hosts.keys()))

    if request.method != "POST":
        return HttpResponse(status=405)

    if _is_public_proxy_request(request):
        return JsonResponse(
            {
                "error": "Forbidden",
                "message": "This endpoint is only accessible internally",
            },
            status=403,
        )

    form = _request_form(request)
    fqdn = form.get("fqdn")
    payload_raw = form.get("data")
    if not fqdn or not payload_raw:
        return HttpResponse(status=400)

    payload = yaml.safe_load(payload_raw)
    try:
        with enc_data.data_lock("hosts"):
            hosts = enc_data.load_map("hosts")
            hosts[fqdn] = payload
            enc_data.save_map("hosts", hosts)
        csr_attributes.get_or_create(csr_attributes.host_entity_name(fqdn))
    except enc_data.EncDataLockTimeout:
        return JsonResponse(
            {"error": "Conflict", "message": "Hosts data is currently locked"},
            status=409,
        )
    return _yaml_http_response(payload)


@csrf_exempt
def hosts_item(request, fqdn):
    """
    Handle GET, PUT and DELETE requests for the /hosts/{fqdn} item endpoint.
    """
    hosts = enc_data.load_map("hosts")
    groups = enc_data.load_map("groups")

    if request.method == "GET":
        host = enc_data.resolve_host(hosts, groups, fqdn)
        return _yaml_http_response(host)

    if request.method == "DELETE":
        if _is_public_proxy_request(request):
            return JsonResponse(
                {
                    "error": "Forbidden",
                    "message": "This endpoint is only accessible internally",
                },
                status=403,
            )
        try:
            with enc_data.data_lock("hosts"):
                hosts = enc_data.load_map("hosts")
                if fqdn not in hosts:
                    return HttpResponse(status=404)
                deleted = hosts[fqdn]
                del hosts[fqdn]
                enc_data.save_map("hosts", hosts)
                csr_attributes.delete(csr_attributes.host_entity_name(fqdn))
                return _yaml_http_response(deleted)
        except enc_data.EncDataLockTimeout:
            return JsonResponse(
                {"error": "Conflict", "message": "Hosts data is currently locked"},
                status=409,
            )

    if request.method != "PUT":
        return HttpResponse(status=405)

    if _is_public_proxy_request(request):
        return JsonResponse(
            {
                "error": "Forbidden",
                "message": "This endpoint is only accessible internally",
            },
            status=403,
        )

    form = _request_form(request)
    try:
        with enc_data.data_lock("hosts"):
            hosts = enc_data.load_map("hosts")
            host = hosts.get(fqdn)
            if not host:
                return HttpResponse(status=404)

            if not isinstance(host.get("parameters"), dict):
                host["parameters"] = {}

            for key in form.keys():
                if key == "fqdn":
                    continue
                if key == "environment":
                    host[key] = form.get(key)
                elif key == "classes":
                    if isinstance(host.get("classes"), dict):
                        host["classes"] = list(host["classes"].keys())
                    elif not isinstance(host.get("classes"), list):
                        host["classes"] = []

                    for value in form.getlist(key):
                        if value.startswith("-"):
                            if value[1:] in host["classes"]:
                                host["classes"].remove(value[1:])
                        elif value not in host["classes"]:
                            host["classes"].append(value)
                else:
                    if isinstance(host["parameters"].get(key, None), list):
                        for value in form.getlist(key):
                            if value.startswith("-"):
                                if value[1:] in host["parameters"][key]:
                                    host["parameters"][key].remove(value[1:])
                            elif value not in host["parameters"][key]:
                                host["parameters"][key].append(value)
                    else:
                        value = form.get(key)
                        if value.startswith("-"):
                            if (
                                key in host["parameters"]
                                and value[1:] == host["parameters"][key]
                            ):
                                del host["parameters"][key]
                        else:
                            host["parameters"][key] = value

            hosts[fqdn] = host
            enc_data.save_map("hosts", hosts)
            csr_attributes.get_or_create(csr_attributes.host_entity_name(fqdn))
            return _yaml_http_response(host)
    except enc_data.EncDataLockTimeout:
        return JsonResponse(
            {"error": "Conflict", "message": "Hosts data is currently locked"},
            status=409,
        )


@csrf_exempt
def groups_collection(request):
    """
    Handle GET and POST requests for the /groups collection endpoint.
    """
    if request.method == "GET":
        groups = enc_data.load_map("groups")
        return _yaml_http_response(list(groups.keys()))

    if request.method != "POST":
        return HttpResponse(status=405)

    if _is_public_proxy_request(request):
        return JsonResponse(
            {
                "error": "Forbidden",
                "message": "This endpoint is only accessible internally",
            },
            status=403,
        )

    form = _request_form(request)
    name = form.get("name")
    payload_raw = form.get("data")
    if not name or not payload_raw:
        return HttpResponse(status=400)

    payload = yaml.safe_load(payload_raw)
    try:
        with enc_data.data_lock("groups"):
            groups = enc_data.load_map("groups")
            groups[name] = payload
            enc_data.save_map("groups", groups)
        csr_attributes.get_or_create(csr_attributes.group_entity_name(name))
    except enc_data.EncDataLockTimeout:
        return JsonResponse(
            {"error": "Conflict", "message": "Groups data is currently locked"},
            status=409,
        )
    return _yaml_http_response(payload)


@csrf_exempt
def groups_item(request, name):
    """
    Handle GET, PUT and DELETE requests for the /groups/{name} item endpoint.
    """
    groups = enc_data.load_map("groups")

    if request.method == "GET":
        if name not in groups:
            return HttpResponse(status=404)
        return _yaml_http_response(groups.get(name))

    if request.method == "DELETE":
        if _is_public_proxy_request(request):
            return JsonResponse(
                {
                    "error": "Forbidden",
                    "message": "This endpoint is only accessible internally",
                },
                status=403,
            )
        try:
            with enc_data.data_lock("groups"):
                groups = enc_data.load_map("groups")
                if name not in groups:
                    return HttpResponse(status=404)
                if name == "default":
                    return HttpResponse(status=403)
                deleted = groups[name]
                del groups[name]
                enc_data.save_map("groups", groups)
                csr_attributes.delete(csr_attributes.group_entity_name(name))
                return _yaml_http_response(deleted)
        except enc_data.EncDataLockTimeout:
            return JsonResponse(
                {"error": "Conflict", "message": "Groups data is currently locked"},
                status=409,
            )

    if request.method != "PUT":
        return HttpResponse(status=405)

    if _is_public_proxy_request(request):
        return JsonResponse(
            {
                "error": "Forbidden",
                "message": "This endpoint is only accessible internally",
            },
            status=403,
        )

    form = _request_form(request)
    try:
        with enc_data.data_lock("groups"):
            groups = enc_data.load_map("groups")
            data = groups.get(name, {})
            if not data:
                return HttpResponse(status=404)

            if not isinstance(data.get("parameters"), dict):
                data["parameters"] = {}

            for key in form.keys():
                if key == "name":
                    continue
                if key == "environment":
                    data[key] = form.get(key)
                elif key == "classes":
                    if not isinstance(data.get("classes"), list):
                        if isinstance(data.get("classes"), dict):
                            data["classes"] = list(data["classes"].keys())
                        else:
                            data["classes"] = []

                    for value in form.getlist(key):
                        if value.startswith("-"):
                            class_to_remove = value[1:]
                            if class_to_remove in data["classes"]:
                                data["classes"].remove(class_to_remove)
                        elif value not in data["classes"]:
                            data["classes"].append(value)
                elif key == "hosts":
                    if not isinstance(data.get("hosts"), list):
                        data["hosts"] = list(data.get("hosts", []))

                    for value in form.getlist(key):
                        if value.startswith("-"):
                            host_to_remove = value[1:]
                            if host_to_remove in data["hosts"]:
                                data["hosts"].remove(host_to_remove)
                        elif value not in data["hosts"]:
                            data["hosts"].append(value)
                else:
                    if isinstance(data.get("parameters", {}).get(key, None), list):
                        for value in form.getlist(key):
                            if value.startswith("-"):
                                param_to_remove = value[1:]
                                if param_to_remove in data["parameters"][key]:
                                    data["parameters"][key].remove(param_to_remove)
                            elif value not in data["parameters"][key]:
                                data["parameters"][key].append(value)
                    else:
                        value = form.get(key)
                        if value.startswith("-"):
                            param_to_remove = value[1:]
                            if (
                                key in data["parameters"]
                                and param_to_remove == data["parameters"][key]
                            ):
                                del data["parameters"][key]
                        else:
                            data["parameters"][key] = value

            groups[name] = data
            enc_data.save_map("groups", groups)
            csr_attributes.get_or_create(csr_attributes.group_entity_name(name))
            return _yaml_http_response(data)
    except enc_data.EncDataLockTimeout:
        return JsonResponse(
            {"error": "Conflict", "message": "Groups data is currently locked"},
            status=409,
        )


@csrf_exempt
def host_csr_attributes(request, fqdn):
    """Return CSR custom_attributes for a host entity."""
    if request.method != "GET":
        return HttpResponse(status=405)

    token_error = _require_csr_api_token(request)
    if token_error:
        return token_error

    return _csr_attributes_yaml_response(csr_attributes.host_entity_name(fqdn))


@csrf_exempt
def group_csr_attributes(request, name):
    """Return CSR custom_attributes for a group entity."""
    if request.method != "GET":
        return HttpResponse(status=405)

    token_error = _require_csr_api_token(request)
    if token_error:
        return token_error

    return _csr_attributes_yaml_response(csr_attributes.group_entity_name(name))
