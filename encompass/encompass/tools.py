"""
analyzes data received
"""

import json
import yaml
import requests_unixsocket
from django.core.mail import EmailMessage
from django.conf import settings


def get_host_details(hostname: str) -> dict:
    """get host details from ENC"""
    url = f"http+unix://%2Frun%2Fenc.sock/hosts/{hostname}"
    session = requests_unixsocket.Session()
    response = session.get(url)

    if response.status_code != 200:
        # pylint: disable=broad-exception-raised
        raise Exception(
            f"ENC error for {hostname}: {response.status_code}"
        )
        # pylint: enable=broad-exception-raised

    return yaml.safe_load(response.text)


def host_exists(hostname: str) -> bool:
    """check if a host exists in ENC"""
    url = "http+unix://%2Frun%2Fenc.sock/hosts"
    session = requests_unixsocket.Session()
    response = session.get(url)

    if response.status_code != 200:
        return False

    hosts_list = yaml.safe_load(response.text)
    if isinstance(hosts_list, list):
        return hostname in hosts_list
    elif isinstance(hosts_list, dict):
        return hostname in hosts_list
    return False


def delete_host(hostname: str) -> dict:
    """delete host from ENC"""
    url = f"http+unix://%2Frun%2Fenc.sock/hosts/{hostname}"
    session = requests_unixsocket.Session()
    response = session.delete(url)

    if response.status_code != 200:
        # pylint: disable=broad-exception-raised
        raise Exception(
            f"ENC error for {hostname}: {response.status_code}"
        )
        # pylint: enable=broad-exception-raised

    return yaml.safe_load(response.text)


def update_host(hostname: str, payload: dict) -> dict:
    """update host in ENC using PUT data with delta tracking"""
    url = f"http+unix://%2Frun%2Fenc.sock/hosts/{hostname}"
    session = requests_unixsocket.Session()

    # First, get the current state
    try:
        original = get_host_details(hostname)
    except Exception:  # pylint: disable=broad-except
        original = {"environment": "", "classes": [], "parameters": {}}

    data = []

    # Environment: always set if provided
    environment = payload.get("environment", "")
    if environment != "":
        data.append(("environment", environment))

    # Classes: calculate delta
    original_classes = set(original.get("classes", []) or [])
    new_classes = set(payload.get("classes", []) or [])

    # Remove old classes not in new set
    for cls in original_classes - new_classes:
        if cls != "":
            data.append(("classes", f"-{cls}"))

    # Add new classes
    for cls in new_classes:
        if cls != "":
            data.append(("classes", cls))

    # Parameters: calculate delta
    original_params = original.get("parameters", {}) or {}
    new_params = payload.get("parameters", {}) or {}

    # Remove old parameters not in new set
    for key in set(original_params.keys()) - set(new_params.keys()):
        if key != "":
            data.append((key, f"-{original_params[key]}"))

    # Set new/updated parameters
    for key, value in new_params.items():
        if key == "":
            continue
        data.append((key, "" if value is None else str(value)))

    response = session.put(url, data=data)

    if response.status_code != 200:
        # pylint: disable=broad-exception-raised
        raise Exception(
            f"ENC error for {hostname}: {response.status_code}"
        )
        # pylint: enable=broad-exception-raised

    return yaml.safe_load(response.text)


def create_host(hostname: str, payload: dict) -> dict:
    """create new host in ENC"""
    url = "http+unix://%2Frun%2Fenc.sock/hosts"
    session = requests_unixsocket.Session()

    # Build host data
    host_data = {}
    
    environment = payload.get("environment", "").strip()
    if environment:
        host_data["environment"] = environment
    
    classes = [cls.strip() for cls in payload.get("classes", []) if cls.strip()]
    if classes:
        host_data["classes"] = classes
    
    parameters = {}
    for key, value in payload.get("parameters", {}).items():
        key = key.strip()
        if key:
            parameters[key] = value
    if parameters:
        host_data["parameters"] = parameters

    # Convert to YAML
    yaml_data = yaml.dump(host_data)

    # Send POST request
    data = {
        "fqdn": hostname,
        "data": yaml_data
    }
    
    response = session.post(url, data=data)

    if response.status_code != 200:
        # pylint: disable=broad-exception-raised
        raise Exception(
            f"ENC error creating {hostname}: {response.status_code}"
        )
        # pylint: enable=broad-exception-raised

    return yaml.safe_load(response.text)



def convert_to_mb(vms_dict=None):
    """convert to MB"""
    vm_range = range(1, int(vms_dict["variable"]["instances"]["default"]) + 1)
    for vm in vm_range:
        mem_mb = int(int(vms_dict["variable"][str(vm)]["default"]["memory"]) * 1024)
        vms_dict["variable"][str(vm)]["default"].update({"memory": int(mem_mb)})

    return vms_dict


def get_file_content(filename):
    """Navbar watermark"""
    try:
        with open(filename, "r", encoding="utf-8") as wm_file:
            filename_data = wm_file.read().replace("\n", "")
    except FileNotFoundError:
        filename_data = ""

    return filename_data


def get_groups_info(groups: list, return_all: bool = False) -> str | list:
    """
    get groups information.
    Returns the highest privilege group name.
    Possible return values: admin, user, viewer, not yet known
    """
    if return_all:
        group_names = []
        if settings.ENC_ADMIN_GROUP in groups:
            group_names.append("admin")
        if settings.ENC_USER_GROUP in groups:
            group_names.append("user")
        if settings.ENC_VIEWER_GROUP in groups:
            group_names.append("viewer")

        return group_names

    if settings.ENC_ADMIN_GROUP in groups:
        return "admin"
    if settings.ENC_USER_GROUP in groups:
        return "user"
    if settings.ENC_VIEWER_GROUP in groups:
        return "viewer"

    return "not yet known"


def check(newfolder, existingfolder):
    """check data consitency"""
    if newfolder and existingfolder:
        return "folders_mismatch"

    if not newfolder and not existingfolder:
        return "missing_foldername"

    return "all_good"


def send_purge_mail(encompass_group, encompass_email, vms=None):
    """send purge notification via email"""
    vms_list = ", ".join(vms) if vms else "none"
    email_subject = "Terraformware purge request"
    email_from = f"Terraformware <{settings.DEFAULT_FROM_EMAIL}>"
    body = (
        f"\n\nYour team: {encompass_group}\n"
        + f"These VMs are being deleted: {vms_list}\n\n"
        + "Please do not reply to this email.\n\nRegards"
    )
    email = EmailMessage(
        email_subject,
        body,
        email_from,
        [encompass_email],
        reply_to=["no-reply@geant.org"],
        headers={"Message-ID": "encompass"},
    )

    email.send()


def copy_logs(user, email, group, folder, subfolder, action, sess_id, vms=None):
    """copy logs"""
    user_data_file = f"/root/userinfo-{sess_id}.json"
    user_data = {
        "user": user,
        "email": email,
        "group": group,
        "folder": folder,
        "subfolder": subfolder,
        "action": action,
        "vms": vms,
    }
    with open(user_data_file, "w", encoding="utf-8") as f:
        json.dump(user_data, f)


def get_group_details(groupname: str) -> dict:
    """get group details from ENC"""
    url = f"http+unix://%2Frun%2Fenc.sock/groups/{groupname}"
    session = requests_unixsocket.Session()
    response = session.get(url)

    if response.status_code != 200:
        # pylint: disable=broad-exception-raised
        raise Exception(
            f"ENC error for {groupname}: {response.status_code}"
        )
        # pylint: enable=broad-exception-raised

    return yaml.safe_load(response.text)


def delete_group(groupname: str) -> dict:
    """delete group from ENC"""
    url = f"http+unix://%2Frun%2Fenc.sock/groups/{groupname}"
    session = requests_unixsocket.Session()
    response = session.delete(url)

    if response.status_code != 200:
        # pylint: disable=broad-exception-raised
        raise Exception(
            f"ENC error for {groupname}: {response.status_code}"
        )
        # pylint: enable=broad-exception-raised

    return yaml.safe_load(response.text)


def update_group(groupname: str, payload: dict) -> dict:
    """update group in ENC using PUT data with delta tracking"""
    url = f"http+unix://%2Frun%2Fenc.sock/groups/{groupname}"
    session = requests_unixsocket.Session()

    # First, get the current state
    try:
        original = get_group_details(groupname)
    except Exception:  # pylint: disable=broad-except
        original = {"environment": "", "classes": [], "hosts": [], "parameters": {}}

    data = []

    # Environment: always set if provided
    environment = payload.get("environment", "")
    if environment != "":
        data.append(("environment", environment))

    # Classes: calculate delta
    original_classes = set(original.get("classes", []) or [])
    new_classes = set(payload.get("classes", []) or [])

    # Remove old classes not in new set
    for cls in original_classes - new_classes:
        if cls != "":
            data.append(("classes", f"-{cls}"))

    # Add new classes
    for cls in new_classes:
        if cls != "":
            data.append(("classes", cls))

    # Hosts: calculate delta
    original_hosts = set(original.get("hosts", []) or [])
    new_hosts = set(payload.get("hosts", []) or [])

    # Remove old hosts not in new set
    for host in original_hosts - new_hosts:
        if host != "":
            data.append(("hosts", f"-{host}"))

    # Add new hosts
    for host in new_hosts:
        if host != "":
            data.append(("hosts", host))

    # Parameters: calculate delta
    original_params = original.get("parameters", {}) or {}
    new_params = payload.get("parameters", {}) or {}

    # Remove old parameters not in new set
    for key in set(original_params.keys()) - set(new_params.keys()):
        if key != "":
            data.append((key, f"-{original_params[key]}"))

    # Set new/updated parameters
    for key, value in new_params.items():
        if key == "":
            continue
        data.append((key, "" if value is None else str(value)))

    response = session.put(url, data=data)

    if response.status_code != 200:
        # pylint: disable=broad-exception-raised
        raise Exception(
            f"ENC error for {groupname}: {response.status_code}"
        )
        # pylint: enable=broad-exception-raised

    return yaml.safe_load(response.text)


def create_group(groupname: str, payload: dict) -> dict:
    """create new group in ENC"""
    url = "http+unix://%2Frun%2Fenc.sock/groups"
    session = requests_unixsocket.Session()

    # Build group data
    group_data = {}

    environment = payload.get("environment", "").strip()
    if environment:
        group_data["environment"] = environment

    classes = [cls.strip() for cls in payload.get("classes", []) if cls.strip()]
    if classes:
        group_data["classes"] = classes

    hosts = [host.strip() for host in payload.get("hosts", []) if host.strip()]
    if hosts:
        group_data["hosts"] = hosts

    parameters = {}
    for key, value in payload.get("parameters", {}).items():
        key = key.strip()
        if key:
            parameters[key] = value
    if parameters:
        group_data["parameters"] = parameters

    # Convert to YAML
    yaml_data = yaml.dump(group_data)

    # Send POST request
    data = {
        "name": groupname,
        "data": yaml_data
    }

    response = session.post(url, data=data)

    if response.status_code != 200:
        # pylint: disable=broad-exception-raised
        raise Exception(
            f"ENC error creating {groupname}: {response.status_code}"
        )
        # pylint: enable=broad-exception-raised

    return yaml.safe_load(response.text)


def group_exists(groupname: str) -> bool:
    """check if a group exists in ENC"""
    url = "http+unix://%2Frun%2Fenc.sock/groups"
    session = requests_unixsocket.Session()
    response = session.get(url)

    if response.status_code != 200:
        return False

    groups_list = yaml.safe_load(response.text)
    if isinstance(groups_list, list):
        return groupname in groups_list
    elif isinstance(groups_list, dict):
        return groupname in groups_list
    return False

