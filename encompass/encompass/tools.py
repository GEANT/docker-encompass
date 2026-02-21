"""
analyzes data received
"""

import json
from django.core.mail import EmailMessage
from django.conf import settings
from . import enc_data


def get_host_details(hostname: str) -> dict:
    """Get host details from local ENC YAML data, with group/default fallback."""
    hosts = enc_data.load_map("hosts")
    groups = enc_data.load_map("groups")
    data = enc_data.resolve_host(hosts, groups, hostname)
    return data


def host_exists(hostname: str) -> bool:
    """Check if a host exists in ENC."""
    return hostname in enc_data.load_map("hosts")


def delete_host(hostname: str) -> dict:
    """Delete host from ENC."""
    with enc_data.data_lock("hosts"):
        hosts = enc_data.load_map("hosts")
        if hostname not in hosts:
            raise Exception(f"ENC error for {hostname}: 404")  # pylint: disable=broad-exception-raised
        deleted = hosts[hostname]
        del hosts[hostname]
        enc_data.save_map("hosts", hosts)
        return deleted


def update_host(hostname: str, payload: dict) -> dict:
    """Update host in ENC from full payload."""
    with enc_data.data_lock("hosts"):
        hosts = enc_data.load_map("hosts")
        if hostname not in hosts:
            raise Exception(f"ENC error for {hostname}: 404")  # pylint: disable=broad-exception-raised
        normalized = enc_data.normalize_host_payload(payload)
        hosts[hostname] = normalized
        enc_data.save_map("hosts", hosts)
        return normalized


def create_host(hostname: str, payload: dict) -> dict:
    """Create new host in ENC."""
    with enc_data.data_lock("hosts"):
        hosts = enc_data.load_map("hosts")
        normalized = enc_data.normalize_host_payload(payload)
        hosts[hostname] = normalized
        enc_data.save_map("hosts", hosts)
        return normalized



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
    Possible return values: admin, viewer, not yet known
    """
    if return_all:
        group_names = []
        if settings.ENC_ADMIN_GROUP in groups:
            group_names.append("admin")
        if settings.ENC_VIEWER_GROUP in groups:
            group_names.append("viewer")

        return group_names

    if settings.ENC_ADMIN_GROUP in groups:
        return "admin"
    if settings.ENC_VIEWER_GROUP in groups:
        return "viewer"

    return "not yet known"


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
    """Get group details from ENC."""
    groups = enc_data.load_map("groups")
    if groupname not in groups:
        raise Exception(f"ENC error for {groupname}: 404")  # pylint: disable=broad-exception-raised
    return groups[groupname]


def delete_group(groupname: str) -> dict:
    """Delete group from ENC."""
    with enc_data.data_lock("groups"):
        groups = enc_data.load_map("groups")
        if groupname not in groups:
            raise Exception(f"ENC error for {groupname}: 404")  # pylint: disable=broad-exception-raised
        if groupname == "default":
            raise Exception(f"ENC error for {groupname}: 403")  # pylint: disable=broad-exception-raised
        deleted = groups[groupname]
        del groups[groupname]
        enc_data.save_map("groups", groups)
        return deleted


def update_group(groupname: str, payload: dict) -> dict:
    """Update group in ENC from full payload."""
    with enc_data.data_lock("groups"):
        groups = enc_data.load_map("groups")
        if groupname not in groups:
            raise Exception(f"ENC error for {groupname}: 404")  # pylint: disable=broad-exception-raised
        normalized = enc_data.normalize_group_payload(payload)
        groups[groupname] = normalized
        enc_data.save_map("groups", groups)
        return normalized


def create_group(groupname: str, payload: dict) -> dict:
    """Create new group in ENC."""
    with enc_data.data_lock("groups"):
        groups = enc_data.load_map("groups")
        normalized = enc_data.normalize_group_payload(payload)
        groups[groupname] = normalized
        enc_data.save_map("groups", groups)
        return normalized


def group_exists(groupname: str) -> bool:
    """Check if a group exists in ENC."""
    return groupname in enc_data.load_map("groups")


def list_hosts() -> list[str]:
    """Return sorted host names."""
    return sorted(enc_data.load_map("hosts").keys())


def list_groups() -> list[str]:
    """Return sorted group names."""
    return sorted(enc_data.load_map("groups").keys())
