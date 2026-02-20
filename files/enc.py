#!/usr/bin/env python3
"""
Puppet ENC server implementation in Flask.

The script originates from https://github.com/ncsa/puppet-enc
It’s been modified to:

1. add versioning: changes are pushed to a git repository.
2. add feature branching.
3. authentication and authorisation have been removed and moved to Django.
   The application runs behind HAProxy and listens only on a UNIX socket. 
   HAProxy will set a specific header to indicate that the request is coming from the network.
   Django will connect to the ENC server through the UNIX socket and will not set this header, 
   so the ENC server can distinguish between internal and external requests.
"""
import os
import logging
from time import strftime
from typing import Literal
from functools import wraps
from flask import Flask, request, abort, Response, jsonify
import yaml

_hosts = {}
_groups = {}
logger = logging.getLogger(__name__)


def _reload_yaml_map(path: str, target: dict):
    """Reload a YAML map from disk into target dict, keeping previous data on transient parse errors."""
    try:
        with open(path, "r", encoding="utf8") as stream:
            loaded = yaml.safe_load(stream.read()) or {}
    except FileNotFoundError:
        target.clear()
        return
    except yaml.YAMLError as err:
        logger.error("Failed parsing YAML file '%s': %s", path, err)
        return
    except OSError as err:
        logger.error("Failed reading YAML file '%s': %s", path, err)
        return

    if not isinstance(loaded, dict):
        logger.error("Ignoring non-mapping YAML in '%s' (type: %s)", path, type(loaded).__name__)
        return

    target.clear()
    target.update(loaded)


def load_data():
    """Reload hosts and groups from disk."""
    _reload_yaml_map("data/hosts.yaml", _hosts)
    _reload_yaml_map("data/groups.yaml", _groups)


load_data()

app = Flask(__name__)


@app.before_request
def refresh_data():
    """Ensure manual file edits are picked up without restart."""
    load_data()


#
# shared functions
#
def internal_only(f):
    """
    Check if the request is coming from internal network
    by looking for a specific header set by haproxy.

    :param f: The function to decorate
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        haproxy_header = request.headers.get("X-Haproxy-Proxy")
        if haproxy_header:
            return (
                jsonify(
                    error="Forbidden",
                    message="This endpoint is only accessible internally",
                ),
                403,
            )

        return f(*args, **kwargs)

    return decorated_function


def data_list(what: Literal["hosts", "groups"]) -> dict:
    """
    Return data list for what
    :param what: "hosts" or "groups"
    """
    if what not in ["hosts", "groups"]:
        abort(500)
    return yaml.safe_load(open(f"data/{what}.yaml", encoding="utf-8"))


def make_response(data):
    """Create yaml response."""
    if data:
        resp = Response(response=yaml.dump(data), status=200, mimetype="text/yaml")
    else:
        resp = Response(response="", status=200, mimetype="text/yaml")
    # resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp


def save_data(what, key, value):
    """Save value to the file, and return respone with value."""
    if what == "hosts":
        data = _hosts
    elif what == "groups":
        data = _groups
    else:
        abort(500)
        data = {}

    if value:
        data[key] = value
    else:
        del data[key]

    destination = os.path.join("data", f"{what}.yaml")
    temporary = f"{destination}.tmp"
    with open(temporary, "w", encoding="utf-8") as fp:
        yaml.dump(data, fp)
    os.replace(temporary, destination)

    return make_response(value)


#
# logging
#
@app.after_request
def after_request(response):
    """Log all requests."""
    if request.path != "/healthz":
        logline = f"{request.remote_addr} -"
        logline = f"{logline} -"
        srv_proto = request.environ.get("SERVER_PROTOCOL", "-")
        logline = f"{logline}{strftime(' [%Y/%b/%d:%H:%M:%S]')}"
        logline = f'{logline} "{request.method} {request.path} {srv_proto}"'
        logline = f"{logline} {response.status_code} {response.content_length}"
        logger.info(logline)
    return response


#
# health-check endpoint
#
@app.route("/healthz")
def healthz():
    """Health check endpoint."""
    return jsonify(ping="pong!", status="ENC is up!"), 200


#
# hosts endpoints
#
@app.route("/hosts", methods=["GET"])
def list_hosts():
    """
    List all hosts.
    Authorized users: admin, user, viewer
    """
    return make_response(list(_hosts.keys()))


@app.route("/hosts/<fqdn>", methods=["GET"])
def get_host(fqdn):
    """
    Get host data for fqdn, or from group if not found.
    Authorized users: admin, user, viewer

    :param fqdn: host fqdn
    """
    host = _hosts.get(fqdn)
    if host:
        return make_response(host)

    for k, v in _groups.items():
        if k == "default":
            continue
        for h in v.get("hosts", []):
            if fqdn.startswith(h):
                host = v.copy()
                host.pop("hosts", None)
                return make_response(host)

    v = _groups.get("default")
    if v:
        host = v.copy()
        host.pop("hosts", None)
        return make_response(host)

    return make_response(None)


@app.route("/hosts", methods=["POST"])
@internal_only
def add_host():
    """
    Add a new host (fqdn) with specified data (yaml format).
    Authorized users: admin, user
    """
    fqdn = request.form.get("fqdn")
    if not fqdn:
        abort(400)
    data = request.form.get("data")
    if not data:
        abort(400)
    return save_data("hosts", fqdn, yaml.safe_load(data))


@app.route("/hosts/<fqdn>", methods=["PUT"])
@internal_only
def update_host(fqdn):
    """
    Update host data for fqdn.
    Authorized users: admin, user

    :param fqdn: host fqdn
    """
    host = _hosts.get(fqdn)
    if not host:
        abort(404)

    if not isinstance(host.get("parameters"), dict):
        host["parameters"] = {}

    for k in request.form.keys():
        if k == "fqdn":
            continue
        if k == "environment":
            host[k] = request.form.get(k)
        elif k == "classes":
            # Ensure classes is a list (support both dict and list formats)
            if isinstance(host.get("classes"), dict):
                host["classes"] = list(host["classes"].keys())
            elif not isinstance(host.get("classes"), list):
                host["classes"] = []

            for v in request.form.getlist(k):
                if v.startswith("-"):
                    if v[1:] in host["classes"]:
                        host["classes"].remove(v[1:])
                elif v not in host["classes"]:
                    host["classes"].append(v)
        else:
            if isinstance(host["parameters"].get(k, None), list):
                for v in request.form.getlist(k):
                    if v.startswith("-"):
                        if v[1:] in host["parameters"][k]:
                            host["parameters"][k].remove(v[1:])
                    elif v not in host["parameters"][k]:
                        host["parameters"][k].append(v)
            else:
                v = request.form.get(k)
                if v.startswith("-"):
                    if k in host["parameters"] and v[1:] == host["parameters"][k]:
                        del host["parameters"][k]
                else:
                    host["parameters"][k] = v

    return save_data("hosts", fqdn, host)


@app.route("/hosts/<fqdn>", methods=["DELETE"])
@internal_only
def delete_host(fqdn):
    """
    Delete host data for fqdn.
    Authorized users: admin

    :param fqdn: host fqdn
    """
    if fqdn not in _hosts:
        abort(404)
    return save_data("hosts", fqdn, None)


#
# groups endpoints
#
@app.route("/groups", methods=["GET"])
def list_groups():
    """
    List all groups.
    Authorized users: admin, user, viewer
    """
    return make_response(list(_groups.keys()))


@app.route("/groups/<name>", methods=["GET"])
def get_group(name):
    """
    Get group data for name.
    Authorized users: admin, user, viewer

    :param name: group name
    """
    if name not in _groups:
        abort(404)
    return make_response(_groups.get(name))


@app.route("/groups", methods=["POST"])
@internal_only
def add_group():
    """
    Add a new group with name and with specified data (yaml format)
    Authorized users: admin
    """
    name = request.form.get("name")
    if not name:
        abort(400)
    data = request.form.get("data")
    if not data:
        abort(400)
    return save_data("groups", name, yaml.safe_load(data))


@app.route("/groups/<name>", methods=["PUT"])
@internal_only
def update_group(name):
    """
    Update group data for name.
    Authorized users: admin

    :param name: group name
    """
    data = _groups.get(name, {})
    if not data:
        abort(404)

    if not isinstance(data.get("parameters"), dict):
        data["parameters"] = {}

    for k in request.form.keys():
        if k == "name":
            continue
        if k == "environment":
            data[k] = request.form.get(k)
        elif k == "classes":
            # Normalize classes to list format
            if not isinstance(data.get("classes"), list):
                data["classes"] = list(data.get("classes", {}).keys()) if isinstance(data.get("classes"), dict) else []

            for v in request.form.getlist(k):
                if v.startswith("-"):
                    class_to_remove = v[1:]
                    if class_to_remove in data["classes"]:
                        data["classes"].remove(class_to_remove)
                elif v not in data["classes"]:
                    data["classes"].append(v)
        elif k == "hosts":
            if not isinstance(data.get("hosts"), list):
                data["hosts"] = list(data.get("hosts", []))

            for v in request.form.getlist(k):
                if v.startswith("-"):
                    host_to_remove = v[1:]
                    if host_to_remove in data["hosts"]:
                        data["hosts"].remove(host_to_remove)
                elif v not in data["hosts"]:
                    data["hosts"].append(v)
        else:
            if isinstance(data.get("parameters", {}).get(k, None), list):
                for v in request.form.getlist(k):
                    if v.startswith("-"):
                        param_to_remove = v[1:]
                        if param_to_remove in data["parameters"][k]:
                            data["parameters"][k].remove(param_to_remove)
                    elif v not in data["parameters"][k]:
                        data["parameters"][k].append(v)
            else:
                v = request.form.get(k)
                if v.startswith("-"):
                    param_to_remove = v[1:]
                    if k in data["parameters"] and param_to_remove == data["parameters"][k]:
                        del data["parameters"][k]
                else:
                    data["parameters"][k] = v

    return save_data("groups", name, data)


@app.route("/groups/<name>", methods=["DELETE"])
@internal_only
def delete_group(name):
    """
    Delete group data for name.
    Authorized users: admin

    :param name: group name
    """
    if name not in _groups:
        abort(404)
    if name == "default":
        abort(403)
    return save_data("groups", name, None)


#
# yaml representation
#
def represent_none(self, _):
    """Represent None as empty value in yaml."""
    return self.represent_scalar("tag:yaml.org,2002:null", "")


# set yaml.dump to print empty value for None
yaml.add_representer(type(None), represent_none)

if __name__ == "__main__":
    app.run(debug=True, port=8000, host="0.0.0.0")
