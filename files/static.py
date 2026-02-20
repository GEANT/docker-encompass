#!/usr/bin/env python3
"""
Serve static files for enCompass. 
This is a simple Flask application that serves files from the "static" directory
and provides a health check endpoint. 
It also logs all requests to the console.
"""
import os
import re
from time import strftime
import logging
from flask import Flask, request, jsonify
from flask import send_from_directory

logger = logging.getLogger(__name__)

STATIC_ROOT = os.environ.get("STATIC_ROOT", "/code/static/static")
FINGERPRINTED_RE = re.compile(r"\.[0-9a-f]{8,}(?=\.[^./]+$)", re.IGNORECASE)


app = Flask(__name__, static_folder=None)


def _cache_ttl(path):
    if FINGERPRINTED_RE.search(path):
        return 31536000

    if path.endswith((".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2", ".ttf")):
        return 86400

    return 300


@app.route('/static/<path:asset_path>')
def serve_static(asset_path):
    """
    Serve static files from the configured STATIC_ROOT directory.
    """
    ttl = _cache_ttl(asset_path)
    response = send_from_directory(STATIC_ROOT, asset_path, max_age=ttl, conditional=True)
    response.cache_control.public = True
    if ttl >= 31536000:
        response.cache_control.immutable = True
    return response


@app.after_request
def after_request(response):
    """
    Log all requests.
    """
    if request.path != "/healthz":
        logline = f"{request.remote_addr} -"
        logline = f"{logline} -"
        srv_proto = request.environ.get("SERVER_PROTOCOL", "-")
        logline = f"{logline}{strftime(' [%Y/%b/%d:%H:%M:%S]')}"
        logline = f'{logline} "{request.method} {request.path} {srv_proto}"'
        logline = f"{logline} {response.status_code} {response.content_length}"
        logger.info(logline)
    return response


@app.route("/healthz")
def healthz():
    """
    Health check endpoint
    """
    return jsonify(ping="pong!", status="Static server is up!"), 200


if __name__ == "__main__":
    app.run(debug=True, port=8004, host="127.0.0.1")
