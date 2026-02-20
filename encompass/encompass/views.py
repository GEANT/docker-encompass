"""
views definition
"""

# -*- coding: utf-8 -*-
import os
import ast
import json
import logging
from subprocess import Popen, PIPE, CalledProcessError
import yaml
import markdown
# import requests
import requests_unixsocket
from django.conf import settings
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.http import StreamingHttpResponse
from django.views.decorators.http import require_GET
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from . import tools

# Configure logging
logger = logging.getLogger(__name__)

# Contstants
MY_ENV = os.environ.copy()
MY_ENV["PYTHONUNBUFFERED"] = "TRUE"
MY_ENV["PATH"] = f"{settings.HOME_DIR}/bin:{os.environ['PATH']}"


def healthz(_):
    """
    Ping page
    Using underscore as function argument as we don't use the request object
    """
    data = {"ping": "pong!", "status": "enCompass success"}
    return JsonResponse(data, status=200, content_type="application/json")


@require_GET
@login_required(login_url="/encompass/login/")
def host_details(_request, hostname):
    """
    Retrieve details for a specific host from the enc.sock API and return as JSON response.
    
    :param _request: Django HttpRequest object (not used in this function, hence the underscore)
    :param hostname: Hostname for which to retrieve details
    """
    try:
        data = tools.get_host_details(hostname)
        return JsonResponse(data)
    except Exception as e:  # pylint: disable=broad-except
        logger.exception("host_details failed for host '%s'", hostname)
        return JsonResponse({"error": str(e)}, status=500)


@require_GET
@login_required(login_url="/encompass/login/")
def group_details(_request, groupname):
    """
    Retrieve details for a specific group from the enc.sock API and return as JSON response.
    
    :param _request: Django HttpRequest object (not used in this function, hence the underscore)
    :param groupname: Group name for which to retrieve details
    """
    try:
        data = tools.get_group_details(groupname)
        if not isinstance(data, dict):
            logger.error(
                "Malformed group payload for '%s': expected dict, got %s",
                groupname,
                type(data).__name__,
            )
            return JsonResponse({"error": "Malformed group data from ENC"}, status=502)
        return JsonResponse(data)
    except Exception as e:  # pylint: disable=broad-except
        logger.exception("group_details failed for group '%s'", groupname)
        return JsonResponse({"error": str(e)}, status=500)


@login_required(login_url="/encompass/login/")
def host_purge_confirmation(request):
    """Show delete confirmation for a host."""
    if request.method != "POST":
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": ["Invalid request method", settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
            },
        )

    hostname = request.POST.get("hostname", "").strip()
    if not hostname:
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": ["No host selected", settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
            },
        )

    encompass_email = request.user.ldap_user.attrs.get("mail", [None])[0]
    disp_name = request.user.ldap_user.attrs.get("displayName", [settings.UNLOGGED])[0]
    groups = request.user.ldap_user.attrs.get("memberOf", [])
    group_name = tools.get_groups_info(groups)

    context = {
        "hostname": hostname,
        "encompass_email": encompass_email,
        "disp_name": disp_name,
        "group_name": group_name,
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
    }

    return render(request, "host_purge_confirmation.html", context)


@login_required(login_url="/encompass/login/")
def host_purge_execute(request):
    """Delete a host from ENC and return to hosts list."""
    if request.method != "POST":
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": ["Invalid request method", settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
            },
        )

    hostname = request.POST.get("hostname", "").strip()
    if not hostname:
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": ["No host selected", settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
            },
        )

    try:
        tools.delete_host(hostname)
        messages.success(request, f"Host '{hostname}' deleted successfully!")
    except Exception as e:  # pylint: disable=broad-except
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": [str(e), settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
            },
        )

    return redirect("/encompass/hosts")


@login_required(login_url="/encompass/login/")
def host_save(request):
    """Save a host definition via ENC."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method"}, status=405)

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON payload"}, status=400)

    hostname = str(payload.get("hostname", "")).strip()
    if not hostname:
        return JsonResponse({"error": "No host selected"}, status=400)

    host_payload = {
        "environment": payload.get("environment", ""),
        "classes": payload.get("classes", []),
        "parameters": payload.get("parameters", {}),
    }

    try:
        tools.update_host(hostname, host_payload)
    except Exception as e:  # pylint: disable=broad-except
        logger.exception("host_save failed for host '%s'", hostname)
        return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"status": "ok"})


@login_required(login_url="/encompass/login/")
def host_add(request):
    """Add a new host to ENC."""
    encompass_email = request.user.ldap_user.attrs.get("mail", [None])[0]
    disp_name = request.user.ldap_user.attrs.get("displayName", [settings.UNLOGGED])[0]
    groups = request.user.ldap_user.attrs.get("memberOf", [])
    group_name = tools.get_groups_info(groups)

    if request.method == "GET":
        # Show the form
        context = {
            "encompass_email": encompass_email,
            "disp_name": disp_name,
            "group_name": group_name,
            "watermark": settings.WATERMARK,
            "current_version": settings.CURRENT_VERSION,
        }
        return render(request, "host_add.html", context)

    # POST: Create the host
    hostname = request.POST.get("hostname", "").strip()
    if not hostname:
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": ["Hostname is required", settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
            },
        )

    # Check if host already exists
    if tools.host_exists(hostname):
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": [f"Host '{hostname}' already exists", settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
            },
        )

    environment = request.POST.get("environment", "").strip()
    classes = [cls.strip() for cls in request.POST.getlist("classes[]") if cls.strip()]
    
    # Build parameters dict from keys and values
    param_keys = request.POST.getlist("param_keys[]")
    param_values = request.POST.getlist("param_values[]")
    parameters = {}
    for key, value in zip(param_keys, param_values):
        key = key.strip()
        if key:
            parameters[key] = value

    host_payload = {
        "environment": environment,
        "classes": classes,
        "parameters": parameters,
    }

    try:
        tools.create_host(hostname, host_payload)
        messages.success(request, f"Host '{hostname}' created successfully!")
    except Exception as e:  # pylint: disable=broad-except
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": [f"Failed to create host: {str(e)}", settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
            },
        )

    # Success - redirect to hosts list with a success message
    return redirect("/encompass/hosts")


@login_required(login_url="/encompass/login/")
def group_purge_confirmation(request):
    """Show confirmation page for deleting a group."""
    groupname = request.GET.get("name", "").strip()
    if not groupname:
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": ["No group specified", settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
            },
        )

    try:
        group_details = tools.get_group_details(groupname)
    except Exception as e:  # pylint: disable=broad-except
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": [f"Failed to retrieve group details: {str(e)}", settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
            },
        )

    encompass_email = request.user.ldap_user.attrs.get("mail", [None])[0]
    disp_name = request.user.ldap_user.attrs.get("displayName", [settings.UNLOGGED])[0]
    groups = request.user.ldap_user.attrs.get("memberOf", [])
    group_name = tools.get_groups_info(groups)

    context = {
        "groupname": groupname,
        "group_details": group_details,
        "encompass_email": encompass_email,
        "disp_name": disp_name,
        "group_name": group_name,
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
    }
    return render(request, "group_purge_confirmation.html", context)


@login_required(login_url="/encompass/login/")
def group_purge_execute(request):
    """Execute deletion of a group."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method"}, status=405)

    groupname = request.POST.get("groupname", "").strip()
    if not groupname:
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": ["No group specified", settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
            },
        )

    try:
        tools.delete_group(groupname)
        messages.success(request, f"Group '{groupname}' deleted successfully!")
    except Exception as e:  # pylint: disable=broad-except
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": [f"Failed to delete group: {str(e)}", settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
            },
        )

    return redirect("/encompass/groups")


@login_required(login_url="/encompass/login/")
def group_save(request):
    """Save a group definition via ENC."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method"}, status=405)

    try:
        payload = json.loads(request.body or "{}")
        logger.info(f"group_save received payload: {payload}")
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        return JsonResponse({"error": "Invalid JSON payload"}, status=400)

    groupname = str(payload.get("groupname", "")).strip()
    if not groupname:
        logger.warning("group_save called without groupname")
        return JsonResponse({"error": "No group selected"}, status=400)

    group_payload = {
        "environment": payload.get("environment", ""),
        "classes": payload.get("classes", []),
        "hosts": payload.get("hosts", []),
        "parameters": payload.get("parameters", {}),
    }

    try:
        logger.info(f"Calling update_group for '{groupname}' with payload: {group_payload}")
        tools.update_group(groupname, group_payload)
        logger.info(f"Successfully updated group '{groupname}'")
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Error updating group '{groupname}': {e}", exc_info=True)
        return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"status": "ok"})


@login_required(login_url="/encompass/login/")
def group_add(request):
    """Add a new group to ENC."""
    encompass_email = request.user.ldap_user.attrs.get("mail", [None])[0]
    disp_name = request.user.ldap_user.attrs.get("displayName", [settings.UNLOGGED])[0]
    groups = request.user.ldap_user.attrs.get("memberOf", [])
    group_name = tools.get_groups_info(groups)

    if request.method == "GET":
        # Show the form
        context = {
            "encompass_email": encompass_email,
            "disp_name": disp_name,
            "group_name": group_name,
            "watermark": settings.WATERMARK,
            "current_version": settings.CURRENT_VERSION,
        }
        return render(request, "group_add.html", context)

    # POST: Create the group
    groupname = request.POST.get("groupname", "").strip()
    if not groupname:
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": ["Group name is required", settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
            },
        )

    # Check if group already exists
    if tools.group_exists(groupname):
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": [f"Group '{groupname}' already exists", settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
            },
        )

    environment = request.POST.get("environment", "").strip()
    classes = [cls.strip() for cls in request.POST.getlist("classes[]") if cls.strip()]
    hosts = [host.strip() for host in request.POST.getlist("hosts[]") if host.strip()]
    
    # Validate that at least one class is provided
    if not classes:
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": ["At least one class is required", settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
            },
        )
    
    # Build parameters dict from keys and values
    param_keys = request.POST.getlist("param_keys[]")
    param_values = request.POST.getlist("param_values[]")
    parameters = {}
    for key, value in zip(param_keys, param_values):
        key = key.strip()
        if key:
            parameters[key] = value

    group_payload = {
        "environment": environment,
        "classes": classes,
        "hosts": hosts,
        "parameters": parameters,
    }

    try:
        tools.create_group(groupname, group_payload)
        messages.success(request, f"Group '{groupname}' created successfully!")
    except Exception as e:  # pylint: disable=broad-except
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": [f"Failed to create group: {str(e)}", settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
            },
        )

    # Success - redirect to groups list with a success message
    return redirect("/encompass/groups")


def group_required_ldap(group_dn: str | list):
    """group(s) required"""
    group_dn_list = group_dn if isinstance(group_dn, list) else [group_dn]

    def in_group_ldap(user):
        ldap_groups = user.ldap_user.attrs.get("memberOf", [])
        if any(group in ldap_groups for group in group_dn_list):
            return True
        return False

    def decorator(view_func):
        def wrapper(request, *args, **kwargs):
            if in_group_ldap(request.user):
                return view_func(request, *args, **kwargs)

            uid = request.user.ldap_user.attrs.get("sAMAccountName", [])[0]
            display_name = request.user.ldap_user.attrs.get("displayName", [])[0]
            encompass_email = request.user.ldap_user.attrs.get("mail", [None])[0]
            groups = request.user.ldap_user.attrs.get("memberOf", [])
            group_name = tools.get_groups_info(groups)
            return render(
                request,
                settings.ERROR_HTML,
                {
                    "results": [
                        f"Username {uid} is not authorized to access this feature",
                        "Try with a different user",
                    ],
                    "card_header": "Authorization Error",
                    "disp_name": display_name,
                    "encompass_email": encompass_email,
                    "group_name": group_name,
                },
            )

        return wrapper

    return decorator


def help_page(request):
    """
    Docstring for help_page

    :param request: Django HttpRequest object
    :return: Rendered help page with content from help.md
    """
    try:
        encompass_email = request.user.ldap_user.attrs.get("mail", [None])[0]
        disp_name = request.user.ldap_user.attrs.get(
            "displayName", [settings.UNLOGGED]
        )[0]
        groups = request.user.ldap_user.attrs.get("memberOf", [])
    except AttributeError:
        encompass_email = None
        disp_name = settings.UNLOGGED
        groups = []

    group_name = tools.get_groups_info(groups)

    with open("templates/help.md", encoding="utf-8") as f:
        content = f.read()

    html = markdown.markdown(content, extensions=["fenced_code", "tables"])
    context = {
        "encompass_email": encompass_email,
        "group_name": group_name,
        "disp_name": disp_name,
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
        "content": html,
    }

    return render(request, "help.html", context)


# def help_page(request):
#    """Dynamic Help page (fetches remote HTML content)"""
#    try:
#        encompass_email = request.user.ldap_user.attrs.get("mail", [None])[0]
#        disp_name = request.user.ldap_user.attrs.get(
#            "displayName", [settings.UNLOGGED]
#        )[0]
#        groups = request.user.ldap_user.attrs.get("memberOf", [])
#    except AttributeError:
#        encompass_email = None
#        disp_name = settings.UNLOGGED
#        groups = []
#
#    group_name = tools.get_groups_info(groups)
#    url = "https://cds.geant.org/tformator/help.html"
#    try:
#        response = requests.get(url, timeout=5)
#        if response.status_code == 200:
#            remote_html = markdown.markdown(response.text)
#        else:
#            remote_html = "<p>Help page temporarily unavailable.</p>"
#    except Exception:  # pylint: disable=broad-except
#        remote_html = "<p>Help page could not be loaded.</p>"
#
#    context = {
#        "encompass_email": encompass_email,
#        "group_name": group_name,
#        "disp_name": disp_name,
#        "watermark": settings.WATERMARK,
#        "current_version": settings.CURRENT_VERSION,
#        "remote_html": remote_html,
#    }
#
#    return render(request, "help.html", context)


def about_page(request):
    """About page"""
    try:
        encompass_email = request.user.ldap_user.attrs.get("mail", [None])[0]
        disp_name = request.user.ldap_user.attrs.get(
            "displayName", [settings.UNLOGGED]
        )[0]
        groups = request.user.ldap_user.attrs.get("memberOf", [])
    except AttributeError:
        encompass_email = None
        disp_name = settings.UNLOGGED
        groups = []

    group_name = tools.get_groups_info(groups)
    context = {
        "encompass_email": encompass_email,
        "group_name": group_name,
        "disp_name": disp_name,
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
    }
    return render(request, "about.html", context)


def run_selfupdate(template_name, cmd, context):
    """self update terraformware with context variables"""
    template_path = os.path.join(settings.TEMPLATES_DIR, template_name)
    with open(template_path, "r", encoding="utf-8") as f:
        for line in f:
            # Render variables from the Django context in the template
            if "I_AM_A_VARIABLE_MATCHER" in line:
                yield line.format(**context)
            else:
                yield line

        with Popen(
            cmd,
            shell=True,
            stdout=PIPE,
            bufsize=1,
            universal_newlines=True,
            env=MY_ENV,
        ) as p:
            for line in p.stdout:
                try:
                    decoded_line = line.decode(
                        "utf-8", errors="ignore"
                    )  # Decode bytes using UTF-8
                except AttributeError:
                    decoded_line = line
                # pre-scrollable does not really work, as we process the output line by line
                yield f'<pre class="pre-scrollable">{decoded_line}</pre>\n'
                yield " " * 1024  # Encourage the browser to render incrementally

        if p.returncode != 0:
            # ! this one needs to be changed. We need to return an html footer showing the error
            raise CalledProcessError(p.returncode, p.args)

        yield """</div>
          <hr style="width: 100%;" />
          <div class="alert alert-success text-center" role="alert" id="warning-banner">
          <svg class="bi flex-shrink-0 me-2" width="24" height="24" role="img" aria-label="Danger:"><use xlink:href="#info-fill"/></svg>
            Job completed!
          </div>

          <div class="mx-auto text-center">
            <a type="button" class="btn btn-outline-primary btn-sm" href="/encompass">Home</a>
          </div>
        </div>
        <br /><br />
        <script>
          // Auto-scroll to bottom as new content arrives
          var scrollInterval = setInterval(function() {
            window.scrollTo(0, document.body.scrollHeight);
          }, 100);

          // Stop auto-scrolling when job completes
          document.addEventListener('DOMContentLoaded', function() {
            setTimeout(function() {
              clearInterval(scrollInterval);
            }, 500);
          });
        </script>
        </body></html>\n"""


@login_required(login_url="login/")
@group_required_ldap(
    [settings.ENC_ADMIN_GROUP, settings.ENC_USER_GROUP, settings.ENC_VIEWER_GROUP]
)
def home_page(request):
    """list available groups"""
    encompass_email = request.user.ldap_user.attrs.get("mail", [None])[0]
    groups = request.user.ldap_user.attrs.get("memberOf", [])
    disp_name = request.user.ldap_user.attrs.get("displayName", [settings.UNLOGGED])[0]
    group_name = tools.get_groups_info(groups)
    context = {
        "groups": groups,
        "encompass_email": encompass_email,
        "disp_name": disp_name,
        "group_name": group_name,
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
    }

    return render(request, "home.html", context)


@login_required(login_url="/encompass/login/")
def host_list(request):
    """list hosts for health check"""
    encompass_email = request.user.ldap_user.attrs.get("mail", [None])[0]
    groups = request.user.ldap_user.attrs.get("memberOf", [])
    disp_name = request.user.ldap_user.attrs.get("displayName", [settings.UNLOGGED])[0]
    group_name = tools.get_groups_info(groups)
    session = requests_unixsocket.Session()
    r = session.get("http+unix://%2Frun%2Fenc.sock/hosts")
    hosts_list = yaml.safe_load(r.text)
    if isinstance(hosts_list, dict):
        host_names = sorted(hosts_list.keys())
    elif isinstance(hosts_list, list):
        host_names = sorted(hosts_list)
    else:
        host_names = []

    context = {
        "groups": groups,
        "encompass_email": encompass_email,
        "disp_name": disp_name,
        "group_name": group_name,
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
        "hosts": host_names,
    }
    return render(request, "hosts.html", context)


@login_required(login_url="/encompass/login/")
def group_list(request):
    """list groups for health check"""
    encompass_email = request.user.ldap_user.attrs.get("mail", [None])[0]
    groups = request.user.ldap_user.attrs.get("memberOf", [])
    disp_name = request.user.ldap_user.attrs.get("displayName", [settings.UNLOGGED])[0]
    group_name = tools.get_groups_info(groups)
    session = requests_unixsocket.Session()
    r = session.get("http+unix://%2Frun%2Fenc.sock/groups")
    groups_list = yaml.safe_load(r.text)

    context = {
        "groups": groups,
        "encompass_email": encompass_email,
        "disp_name": disp_name,
        "group_name": group_name,
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
        "groups_list": groups_list,
    }
    return render(request, "groups.html", context)


@login_required(login_url="/encompass/login/")
def query_host(request):
    """
    Query a specific host to see its ENC classification.
    GET: Show the query form
    POST: Query the host and display results
    """
    encompass_email = request.user.ldap_user.attrs.get("mail", [None])[0]
    groups = request.user.ldap_user.attrs.get("memberOf", [])
    disp_name = request.user.ldap_user.attrs.get("displayName", [settings.UNLOGGED])[0]
    group_name = tools.get_groups_info(groups)
    
    context = {
        "encompass_email": encompass_email,
        "group_name": group_name,
        "disp_name": disp_name,
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
    }
    
    if request.method == "POST":
        hostname = request.POST.get("hostname", "").strip()
        
        if not hostname:
            context["error"] = "Please enter a hostname"
            return render(request, "query_host.html", context)
        
        try:
            # Query the ENC API
            session = requests_unixsocket.Session()
            response = session.get(f"http+unix://%2Frun%2Fenc.sock/hosts/{hostname}")
            
            if response.status_code == 404:
                context["error"] = f"Host '{hostname}' not found in ENC"
                context["hostname"] = hostname
                return render(request, "query_host.html", context)
            
            if response.status_code != 200:
                context["error"] = f"Error querying host: HTTP {response.status_code}"
                context["hostname"] = hostname
                return render(request, "query_host.html", context)
            
            # Parse the YAML response
            host_data = yaml.safe_load(response.text)
            
            # Convert back to YAML for display (pretty printed)
            yaml_output = yaml.dump(host_data, default_flow_style=False, sort_keys=False)
            
            context["hostname"] = hostname
            context["yaml_output"] = yaml_output
            context["host_data"] = host_data
            
        except Exception as e:  # pylint: disable=broad-except
            logger.exception("Error querying host '%s'", hostname)
            context["error"] = f"Failed to query host: {str(e)}"
            context["hostname"] = hostname
    
    return render(request, "query_host.html", context)


@login_required(login_url="/encompass/login/")
def query(request):
    """
    query VMs from vCenter
    """
    groups = request.user.ldap_user.attrs.get("memberOf", [])
    group_name = tools.get_groups_info(groups)
    encompass_email = request.user.ldap_user.attrs.get("mail", [None])[0]
    groups = request.user.ldap_user.attrs.get("memberOf", [])
    groups_info = tools.get_groups_info(groups)
    disp_name = request.user.ldap_user.attrs.get("displayName", [settings.UNLOGGED])[0]
    try:
        encompass_folder = groups_info[group_name]["encompass_folder"]
    except KeyError:
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": [
                    "You must select a group and click 'Confirm Group'",
                    settings.TRY_AGAIN,
                ],
                "current_version": settings.CURRENT_VERSION,
            },
        )
    context = {
        "encompass_folder": encompass_folder,
        "encompass_email": encompass_email,
        "group_name": group_name,
        "disp_name": disp_name,
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
    }

    return render(request, "query.html", context)


@login_required(login_url="/encompass/login/")
def query_terminal(request):
    """update Terraformware terminal"""
    encompass_email = request.user.ldap_user.attrs.get("mail", [None])[0]
    disp_name = request.user.ldap_user.attrs.get("displayName", [settings.UNLOGGED])[0]
    groups = request.user.ldap_user.attrs.get("memberOf", [])
    group_name = tools.get_groups_info(groups)
    vm_pattern = request.POST.get("vm_pattern", "")
    vm_location = request.POST.get("vm_location", "")
    context = {
        "encompass_email": encompass_email,
        "group_name": group_name,
        "disp_name": disp_name,
        "action_name": "Query",
        "vm_pattern": vm_pattern,
        "vm_location": vm_location,
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
    }

    stream = run_selfupdate(
        "terminal/terminal.html",
        f"/usr/local/bin/vm_find.py --vm {vm_pattern} --location {vm_location}",
        context,
    )
    response = StreamingHttpResponse(stream, content_type=settings.TEXT_HTML)
    response["Cache-Control"] = "no-cache"
    return response


@login_required(login_url="/encompass/login/")
@group_required_ldap(
    [settings.ENC_ADMIN_GROUP, settings.ENC_USER_GROUP, settings.ENC_VIEWER_GROUP]
)
def hosts(request):
    """
    grab all VMs from Consul and list them in a grid
    add status for each VM and allow deletion
    """
    groups = request.user.ldap_user.attrs.get("memberOf", [])
    group_name = tools.get_groups_info(groups)
    encompass_email = request.user.ldap_user.attrs.get("mail", [None])[0]
    groups = request.user.ldap_user.attrs.get("memberOf", [])
    disp_name = request.user.ldap_user.attrs.get("displayName", [settings.UNLOGGED])[0]
    groups_info = tools.get_groups_info(groups)
    try:
        encompass_folder = groups_info[group_name]["encompass_folder"]
    except KeyError:
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": [
                    "You must select a group and click 'Confirm Group'",
                    settings.TRY_AGAIN,
                ],
                "current_version": settings.CURRENT_VERSION,
            },
        )

    folders_list = "aaa"
    _tf_ison_list, _ = "bbb"

    if settings.IS_MULTIPROCESS:
        vm_list = "ccc"
    else:
        vm_list = "ddd"

    context = {
        "folders": sorted(folders_list),
        "encompass_folder": encompass_folder,
        "encompass_email": encompass_email,
        "group_name": group_name,
        "disp_name": disp_name,
        "vm_list": vm_list,
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
    }
    return render(request, "dashboard.html", context)


@login_required(login_url="/encompass/login/")
def vm_purge_confirmation(request):
    """show purge confirmation"""
    groups = request.user.ldap_user.attrs.get("memberOf", [])
    group_name = tools.get_groups_info(groups)
    encompass_email = request.user.ldap_user.attrs.get("mail", [None])[0]
    groups = request.user.ldap_user.attrs.get("memberOf", [])
    disp_name = request.user.ldap_user.attrs.get("displayName", [settings.UNLOGGED])[0]
    groups_info = tools.get_groups_info(groups)
    encompass_folder = groups_info[group_name]["encompass_folder"]

    selected_elements = request.POST.getlist("selected_vms[]", "")
    if not selected_elements:
        return render(
            request,
            settings.ERROR_HTML,
            {"results": ["No VMs selected", settings.TRY_AGAIN]},
        )

    # this is an array of arrays: [[vm1, folder1, status], [vm2, folder2, status]]
    selected_list = [ast.literal_eval(x) for x in selected_elements]
    context = {
        "encompass_folder": encompass_folder,
        "encompass_email": encompass_email,
        "group_name": group_name,
        "disp_name": disp_name,
        "vm_list": selected_list,
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
    }

    return render(request, "vm_purge_confirmation.html", context)


@login_required(login_url="login/")
def vm_common(request):
    """
    Create new vm or edit existing vm.
    If the folder does not exist, call vm_warning.html to ask if the user wants to create it
    if the user wants to create it, create the folder and call vm_common again.
    This time the folder will exist.
    If the folder exists, call vm_common.html
    """
    group_name = request.POST.get("group_name", "")
    encompass_folder = request.POST.get("encompass_folder", "")
    encompass_email = request.POST.get("encompass_email", "")
    disp_name = request.POST.get("disp_name", "")
    newfoldername = request.POST.get("newfoldername", "")
    existingfoldername = request.POST.get("existingfoldername", "")
    subfoldername = request.POST.get("subfoldername", "")
    _create = request.POST.get("create", "")
    _dc_name = "dd"
    datacenter, datacenter_long = "cc", "cc"

    # check if all data have been provided
    data = tools.check(newfoldername, existingfoldername)

    if data == "missing_foldername":
        context = {
            "results": ["You did not choose any Folder name", settings.TRY_AGAIN],
            "watermark": settings.WATERMARK,
            "current_version": settings.CURRENT_VERSION,
        }
        response = render(request, settings.ERROR_HTML, context)
        return response

    if newfoldername:
        foldername = newfoldername
    else:
        foldername = existingfoldername

    folder_status = True
    # if folder_status is set to "folder" we have only the Application folder
    # if folder_status is None we have neither the Application folder nor the Environment folder
    # else we have both the Application folder and the Environment folder
    if folder_status == "folder" or not folder_status:
        if not folder_status:
            warn_msg = f"An application folder {foldername} does not exist"
            card_header = "New application notice"
        else:
            warn_msg = (
                f"An environment {subfoldername}, for the application "
                + f"folder {foldername} does not exist"
            )
            card_header = "New environment notice"
        context = {
            "results": [warn_msg, "Do you want to create it?"],
            "card_header": card_header,
            "encompass_folder": encompass_folder,
            "group_name": group_name,
            "encompass_email": encompass_email,
            "disp_name": disp_name,
            "newfoldername": newfoldername,
            "existingfoldername": existingfoldername,
            "subfoldername": subfoldername,
            "foldername": foldername,
            "datacenter_long": datacenter_long,
            "create": "create",
            "watermark": settings.WATERMARK,
            "current_version": settings.CURRENT_VERSION,
        }
        response = render(request, "vm_warning.html", context)
        return response

    vm_editor_context = {}
    common_context = {}
    nsx_generic_tags_list = "eee"
    _folders = os.path.join(encompass_folder, foldername, datacenter, subfoldername)
    nsx_user_tags_list = "fff"

    vms_startval_data = "ggg"
    common_startval_data = "hhh"
    vms_startval_json = json.dumps(vms_startval_data)
    common_startval_json = json.dumps(common_startval_data)
    vm_editor_context["vms"] = vms_startval_json
    common_context["common"] = common_startval_json
    common_schema_url = f"{settings.CDS_URL}/common-schema-{subfoldername}.json"
    context = {
        "foldername": foldername,
        "newfoldername": newfoldername,
        "existingfoldername": existingfoldername,
        "subfoldername": subfoldername,
        "datacenter": datacenter,
        "datacenter_long": datacenter_long,
        "editor_dict": vm_editor_context,
        "common_dict": common_context,
        "encompass_folder": encompass_folder,
        "encompass_email": encompass_email,
        "disp_name": disp_name,
        "group_name": group_name,
        "nsx_generic_tags_list": nsx_generic_tags_list,
        "nsx_user_tags_list": nsx_user_tags_list,
        "common_schema_url": common_schema_url,
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
    }

    response = render(request, "vm_common.html", context)
    return response


@login_required(login_url="login/")
def vm_editor(request):
    """VM editor"""
    group_name = request.POST.get("group_name", "")
    encompass_folder = request.POST.get("encompass_folder", "")
    encompass_email = request.POST.get("encompass_email", "")
    disp_name = request.POST.get("disp_name", "")
    foldername = request.POST.get("foldername", "")
    subfoldername = request.POST.get("subfoldername", "")
    datacenter = request.POST.get("datacenter", "")
    datacenter_long = request.POST.get("datacenter_long", "")
    json_vms_str = request.POST.get("json_common", "")
    selected_tags = request.POST.getlist("selected_tags[]", "")
    groups = request.user.ldap_user.attrs.get("memberOf", [])
    _groups_info = tools.get_groups_info(groups)

    common_dict = json.loads(json_vms_str)

    if foldername == "":
        context = {
            "results": ["You did not choose any Folder name", settings.TRY_AGAIN],
            "watermark": settings.WATERMARK,
            "current_version": settings.CURRENT_VERSION,
        }
        html_file = settings.ERROR_HTML
    else:
        html_file = "vm_editor.html"

        vm_editor_context = {}

        vms_schema_url = f"{settings.CDS_URL}/vms-schema-{subfoldername}.json"
        context = {
            "editor_dict": vm_editor_context["vms"],
            "common_dict": common_dict["common"],
            "encompass_folder": encompass_folder,
            "encompass_email": encompass_email,
            "disp_name": disp_name,
            "group_name": group_name,
            "foldername": foldername,
            "subfoldername": subfoldername,
            "datacenter": datacenter,
            "datacenter_long": datacenter_long,
            "vms_schema_url": vms_schema_url,
            "selected_tags": selected_tags,
            "watermark": settings.WATERMARK,
            "current_version": settings.CURRENT_VERSION,
        }

    response = render(request, html_file, context)
    return response


@login_required(login_url="/encompass/login/")
def logout_confirmation(request):
    """show update confirmation"""
    encompass_email = request.user.ldap_user.attrs.get("mail", [None])[0]
    disp_name = request.user.ldap_user.attrs.get("displayName", [settings.UNLOGGED])[0]
    group_name = request.POST.get("group_name", "")
    context = {
        "encompass_email": encompass_email,
        "group_name": group_name,
        "disp_name": disp_name,
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
    }

    return render(request, "logout_confirmation.html", context)
