"""
views definition
"""

# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import os
import re
import ast
import json
import socket
import datetime
import configparser
from multiprocessing import Pool
from functools import partial
from django.conf import settings
import consul
from . import tools


def consul_connector():
    """connect to Consul"""
    config = configparser.ConfigParser(allow_no_value=True)
    config.read(os.path.join(os.path.expanduser("~"), ".terraformware.conf"))
    cluster = config.get("terraformware", "consul_cluster")
    token = config.get("terraformware", "consul_token")
    c_connector = consul.Consul(host=cluster, port="443", token=token, scheme="https")

    return c_connector


def acquire_lock(top_folder, folder, datacenter, subfolder, disp_name, session):
    """
    acquire lock on Consul
    """
    culprit = None
    unix_timestamp = None
    c_client = consul_connector()
    lock_path = f"{top_folder}/{folder}/{datacenter}/{subfolder}/tformator.lock"
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    sess_id = c_client.session.create(ttl=3600, behavior="delete")
    lock_json = json.dumps(
        {
            "created": timestamp,
            "unix_timestamp": datetime.datetime.now().timestamp(),
            "key": lock_path,
            "metadata": disp_name,
            "consul_session": sess_id,
            "www_session": session,
        },
        indent=4,
    )
    if not c_client.kv.put(lock_path, lock_json, acquire=sess_id):
        json_culprit = json.loads(c_client.kv.get(lock_path, keys=False)[1]["Value"])
        if json_culprit["www_session"] != session:  # that's not me!
            culprit = json_culprit["metadata"]
            unix_timestamp = json_culprit["unix_timestamp"]

    return culprit, unix_timestamp


def store_group_information(session_id, group_name):
    """
    store group name on Consul
    """
    c_client = consul_connector()
    group_folder_path = f"terraform_config/group_session/{session_id}"
    try:
        c_client.kv.put(group_folder_path, group_name)
    except Exception:  # pylint: disable=broad-exception-caught
        return False

    return True


def retrieve_group_information(session_id):
    """
    retrieve group name on Consul
    """
    c_client = consul_connector()
    folder_path = f"terraform_config/group_session/{session_id}"
    try:
        group_info = c_client.kv.get(folder_path, keys=False)[1]["Value"].decode()
    except Exception:  # pylint: disable=broad-exception-caught
        return False

    return group_info.rstrip()


def release_lock(top_folder, folder, datacenter, subfolder):
    """release lock on Consul"""
    lock_path = f"{top_folder}/{folder}/{datacenter}/{subfolder}/tformator.lock"
    c_client = consul_connector()

    try:
        sess_id = c_client.kv.get(lock_path)[1]["Session"]
    except (TypeError, KeyError) as err:
        print(f"[ERROR] {lock_path}: {err}")
        try:
            _ = c_client.kv.delete(lock_path)
        except KeyError as error:
            print(f"[ERROR] the lock is gone: {error}")
            return None

    _ = c_client.kv.put(lock_path, None, acquire=sess_id)
    try:
        c_client.kv.delete(lock_path)
    except KeyError:
        pass

    return None


def check_folder(top_folder, folder, datacenter, subfolder):
    """check whether the folder exists in Consul"""
    c_client = consul_connector()
    subfolder_path = f"{top_folder}/{folder}/{datacenter}/{subfolder}/"
    folder_path = f"{top_folder}/{folder}/"
    subfolder_check = c_client.kv.get(subfolder_path, keys=True)[1]
    if subfolder_check:
        return "subfolder"

    folder_check = c_client.kv.get(folder_path, keys=True)[1]
    if folder_check:
        return "folder"

    return None


def get_user_nsx_tags(folders):
    """get user defined NSX-T Tags from Consul"""
    c_client = consul_connector()
    full_path = f"{folders}/nsx_tags.json"
    try:
        vms_json = c_client.kv.get(full_path, keys=False)[1]["Value"].decode()
        vms_dict = json.loads(vms_json)
    except Exception:  # pylint: disable=broad-exception-caught
        return []

    return vms_dict


def match_hostname(exclusion, hostnames=None):
    """
    match hostname inside json object
    how it works: it runs a recursive search on Consul. The query returns even the name of the
    top folder. For instance, `terraform_swd` is included in the search, if we search under
    `terraform`.   While this works, it safer to add a trailing slash to the top folder, and
    iterate over the list of top folders.
    We are also transforming the json to a dictionary, than json again, to have a consistent
    output.
    exclusion, is our path to the json file, and we are excluding it from the search.
    """
    c_client = consul_connector()
    top_elements = tools.get_groups_info(None, True)
    hostnames_list = hostnames if hostnames else []
    top_folders = [f"{x}/" for x in top_elements]
    duplicates = []
    for top in top_folders:
        json_list = [
            [x["Key"], json.dumps(json.loads(x["Value"].decode()))]
            for x in c_client.kv.get(top, recurse=True)[1]
            if x["Key"].endswith("variables.tf.json")
            and f"{settings.CONSUL_CONFIG_BASE}/" not in x["Key"]
            and x["Key"].startswith(exclusion) is False
        ]
        for hostname in hostnames_list:
            duplicates += [
                [x[0], hostname]
                for x in json_list
                if f'"hostname": "{hostname}"' in x[1]
            ]

    return duplicates


def upload_user_nsx_tags(nsx_tags, folders):
    """upload NSX-T Tags to Consul"""
    full_path = f"{folders}/nsx_tags.json"
    c_client = consul_connector()
    json_content = json.dumps(nsx_tags, indent=2)
    try:
        c_client.kv.put(full_path, json_content)
    except Exception:  # pylint: disable=broad-exception-caught
        return False

    return True


def get_ssh_pub_key(folders):
    """delete SSH public key from Consul"""
    c_client = consul_connector()
    full_path = f"{folders}/ssh_pub_key"
    try:
        sshkey = c_client.kv.get(full_path, keys=False)[1]["Value"].decode()
    except Exception:  # pylint: disable=broad-exception-caught
        return ""

    return sshkey


def upload_ssh_pub_key(ssh_pub_key, folders):
    """upload SSH public key to Consul"""
    full_path = f"{folders}/ssh_pub_key"
    c_client = consul_connector()
    try:
        c_client.kv.put(full_path, ssh_pub_key)
    except Exception:  # pylint: disable=broad-exception-caught
        return False

    return True


def delete_ssh_pub_key(folders):
    """delete SSH public key from Consul"""
    full_path = f"{folders}/ssh_pub_key"
    c_client = consul_connector()
    try:
        c_client.kv.delete(full_path)
    except Exception:  # pylint: disable=broad-exception-caught
        return False

    return True


def list_folder(top_folder):
    """list folders in Consul"""
    c_client = consul_connector()
    folders = c_client.kv.get(f"{top_folder}/", keys=True)[1]
    cut_folders = sorted([re.sub(rf"^{top_folder}/", "", x) for x in folders])
    unique_root_folders = set([re.sub(r"\/.*$", "", x) for x in cut_folders])
    try:
        unique_root_folders.remove("config")
    except KeyError:
        pass

    return unique_root_folders


def list_variables_tf_json(top_folder=None, all_folders=None):
    """list subfolders in Consul"""
    c_client = consul_connector()
    if not top_folder and not all_folders:
        return False, False
    if all_folders:
        folders = []
        top_folders = tools.get_groups_info(None, True)
        for folder in top_folders:
            folders += c_client.kv.get(f"{folder}/", keys=True)[1]
    else:
        folders = c_client.kv.get(f"{top_folder}/", keys=True)[1]

    vars_js_list = [x for x in folders if x.endswith("variables.tf.json")]
    vars_tf_list = [x for x in folders if x.endswith("variables.tf")]

    unique_vars_json_list = set(vars_js_list)
    unique_vars_tf_list = set(vars_tf_list)

    return list(unique_vars_json_list), list(unique_vars_tf_list)


def check_ping(fqdn):
    """check ping status"""
    try:
        socket.gethostbyname(fqdn)
    except socket.gaierror:
        return '<td class="bg-danger">dns not found</td>'
    response = os.system(f"fping -t 120 {fqdn} > /dev/null 2>&1")
    if response == 0:
        pingstatus = '<td class="bg-success">up</td>'
    else:
        pingstatus = '<td class="bg-danger">ping down</td>'
    return pingstatus


def process_vm(c_client, top_folder, full_path):
    """Process each VM"""
    json_obj = c_client.kv.get(full_path, keys=False)[1]["Value"].decode()
    vms_dict = json.loads(json_obj)
    instances = vms_dict["variable"]["instances"]["default"]
    vm_entries = []
    for vm in range(1, int(instances) + 1):
        host_name = vms_dict["variable"][str(vm)]["default"]["hostname"]
        domain_name = vms_dict["variable"][str(vm)]["default"]["domain"]
        vm_name = f"{host_name}.{domain_name}"
        dir_name = os.path.dirname(full_path)
        folder = re.sub(rf"^{top_folder}/", "", dir_name)
        ping_status = check_ping(vm_name)
        vm_entries.append([vm_name, folder, ping_status])
    return vm_entries


def scavenge_vms_mp(top_folder, variables_objects=None):
    """
    scavenge VMs from Consul using multiprocessing
    muyltiprocessing added by GPT
    """
    c_client = consul_connector()
    vms_list = []
    variables_list = variables_objects if variables_objects else []

    with Pool() as pool:
        partial_process_vm = partial(process_vm, c_client, top_folder)
        results = pool.map(partial_process_vm, variables_list)
        for result in results:
            vms_list.extend(result)

    return sorted(vms_list, key=lambda x: x[0])


def scavenge_vms(top_folder, variables_objects=None):
    """
    scavenge VMs from Consul
    we use this function only for debugging
    """
    c_client = consul_connector()
    vms_list = []
    variables_list = variables_objects if variables_objects else []

    for full_path in variables_list:
        json_obj = c_client.kv.get(full_path, keys=False)[1]["Value"].decode()
        vms_dict = json.loads(json_obj)
        instances = vms_dict["variable"]["instances"]["default"]
        for vm in range(1, int(instances) + 1):
            try:
                host_name = vms_dict["variable"][str(vm)]["default"]["hostname"]
            except KeyError:
                print("[DEBUG] Full path:", full_path)
                break
            domain_name = vms_dict["variable"][str(vm)]["default"]["domain"]
            vm_name = f"{host_name}.{domain_name}"
            dir_name = os.path.dirname(full_path)
            folder = re.sub(rf"^{top_folder}/", "", dir_name)
            vms_list.append([vm_name, folder, check_ping(vm_name)])

    return sorted(vms_list, key=lambda x: x[0])


def build_json(folder, datacenter, subfolder, top_folder):
    """
    check subfolder content in Consul
    the folders are ordered as follows:
    terraform/<folder>/<datacenter>/<subfolder>/variables.tf.json
    creates a json file if does not exist
    """
    c_client = consul_connector()
    json_path = f"{top_folder}/{folder}/{datacenter}/{subfolder}/variables.tf.json"

    # if json does not exist, create json from default template, else do nothing
    try:
        _ = c_client.kv.get(json_path, keys=True)[1][0]
    except TypeError:
        try:
            _default_template = c_client.kv.get(
                f"{settings.CONSUL_CONFIG_BASE}/variables.tf.json", keys=False
            )[1]["Value"].decode()
            default_template = json.loads(_default_template)
            # puppet_env is needed only from the CLI but not from the UI
            for element in ["1", "2"]:
                try:
                    del default_template["variable"][element]["default"]["puppet_env"]
                except KeyError:
                    pass
            dumped_template = json.dumps(default_template, indent=2)
            c_client.kv.put(json_path, dumped_template)
        except Exception as err:  # pylint: disable=broad-exception-caught
            print(f"[ERROR] failed uploading default template: {err}")
            return False

    return True


def reconcile_dict(vars_dict):
    """
    reconcile dictionary
    it removes old keys from common and adds new ones in the VM section if missing
    """
    vm_range = range(1, int(vars_dict["variable"]["instances"]["default"]) + 1)
    alowed_common_keys = ["ssh_group", "sudo_group", "template"]
    alowed_vm_keys = [
        "hostname",
        "domain",
        "puppet_env",
        "disk_size_gb",
        "extra_disk_number",
        "extra_disk_size_gb",
        "ipv4_address",
        "ipv6_address",
        "memory",
        "num_cpus",
        "bandwidth",
        "annotation",
    ]
    existing_common_keys = vars_dict["variable"]["common"]["default"].keys()
    forbidden_common_keys = list(set(existing_common_keys) - set(alowed_common_keys))
    dns_dict = {"type": "list", "default": ["83.97.93.200", "62.40.104.250"]}
    ignore_dict = {"type": "list", "default": ["clone", "disk", "network_interface"]}

    vars_dict["variable"]["dns_servers"].update(dns_dict)

    for key in forbidden_common_keys:
        del vars_dict["variable"]["common"]["default"][key]

    try:
        _ = vars_dict["variable"]["ignore_changes"]
    except KeyError:
        vars_dict["variable"]["ignore_changes"] = ignore_dict

    for vm in vm_range:
        existing_vm_keys = vars_dict["variable"][str(vm)]["default"].keys()
        forbidden_vm_keys = list(set(existing_vm_keys) - set(alowed_vm_keys))
        for key in forbidden_vm_keys:
            del vars_dict["variable"][str(vm)]["default"][key]

        try:
            _ = vars_dict["variable"][str(vm)]["default"]["extra_disk_number"]
        except KeyError:
            vars_dict["variable"][str(vm)]["default"]["extra_disk_number"] = 0

        try:
            _ = vars_dict["variable"][str(vm)]["default"]["extra_disk_size_gb"]
        except KeyError:
            vars_dict["variable"][str(vm)]["default"]["extra_disk_size_gb"] = 0

    return vars_dict


def vms_dict_startval(folder, datacenter, subfolder, top_folder):
    """
    we need to grab only the VMs from the json file
    the folders are ordered as follows:
    terraform/<folder>/<datacenter>/<subfolder>/variables.tf.json
    """
    c_client = consul_connector()
    json_path = f"{top_folder}/{folder}/{datacenter}/{subfolder}/variables.tf.json"
    try:
        dict_content = json.loads(
            c_client.kv.get(json_path, keys=False)[1]["Value"].decode()
        )
    except TypeError:
        return False

    vms_list = []
    vm_range = range(1, int(dict_content["variable"]["instances"]["default"]) + 1)
    for vm in vm_range:
        vms_list.append(dict_content["variable"][str(vm)]["default"])
        mem_gb = int(int(dict_content["variable"][str(vm)]["default"]["memory"]) / 1024)
        dict_content["variable"][str(vm)]["default"].update({"memory": int(mem_gb)})
    vms_dict = {"VMs": vms_list}

    return vms_dict


def common_dict_startval(folder, datacenter, subfolder, top_folder):
    """
    we need to grab only the VMs from the json file
    the folders are ordered as follows:
    terraform/<folder>/<datacenter>/<subfolder>/variables.tf.json
    """
    c_client = consul_connector()
    json_path = f"{top_folder}/{folder}/{datacenter}/{subfolder}/variables.tf.json"
    try:
        dict_content = json.loads(
            c_client.kv.get(json_path, keys=False)[1]["Value"].decode()
        )
    except TypeError:
        return False
    common_dict = {"common": dict_content["variable"]["common"]["default"]}

    return common_dict


def upload(content, folder, datacenter, subfolder, top_folder, convert=None):
    """upload `content` onto variables.tf.json"""
    c_client = consul_connector()
    json_path = f"{top_folder}/{folder}/{datacenter}/{subfolder}/variables.tf.json"
    if convert:
        converted_content = tools.convert_to_mb(content)
        content_json = json.dumps(converted_content, indent=2)
    else:
        content_json = json.dumps(content, indent=2)

    try:
        c_client.kv.put(json_path, content_json)
    except Exception:  # pylint: disable=broad-exception-caught
        return False

    return True


def remove_vm(host_name, domain_name, top_folder, folder):
    """remove VM from variables.tf.json"""
    c_client = consul_connector()
    json_path = f"{top_folder}/{folder}/variables.tf.json"
    try:
        dict_content = json.loads(
            c_client.kv.get(json_path, keys=False)[1]["Value"].decode()
        )
    except TypeError:
        return False

    instances = dict_content["variable"]["instances"]["default"]
    new_instances = int(instances) - 1
    for vm in range(1, int(instances) + 1):
        json_hostname = dict_content["variable"][str(vm)]["default"]["hostname"]
        json_domain = dict_content["variable"][str(vm)]["default"]["domain"]
        if json_hostname == host_name and json_domain == domain_name:
            del dict_content["variable"][str(vm)]
            dict_content["variable"]["instances"]["default"] = new_instances
            break

    # we need to reorganize the dictionary
    for vm in range(1, int(instances)):
        try:
            _ = dict_content["variable"][str(vm)]
        except KeyError:
            dict_content["variable"][str(vm)] = dict_content["variable"][str(vm + 1)]
            del dict_content["variable"][str(vm + 1)]

    split_path = json_path.split("/")
    upload(dict_content, split_path[1], split_path[2], split_path[3], top_folder)
    purge_empty(top_folder, folder)

    return True


def purge_empty(top_folder, folder):
    """purge empty folders"""
    c_client = consul_connector()
    json_path = f"{top_folder}/{folder}/variables.tf.json"
    try:
        dict_content = json.loads(
            c_client.kv.get(json_path, keys=False)[1]["Value"].decode()
        )
    except TypeError:
        return False

    instances = dict_content["variable"]["instances"]["default"]
    if instances == 0:
        c_client.kv.delete(f"{top_folder}/{folder}", recurse=True)

    return True


def get_generic_nsx_tags():
    """get NSX tags from Consul"""
    c_client = consul_connector()
    _, params_dict = c_client.kv.get(f"{settings.CONSUL_CONFIG_BASE}/params.conf")
    params = params_dict["Value"].decode("utf-8")
    config_nsx = configparser.RawConfigParser(allow_no_value=True)
    config_nsx.read_string(params)
    nsx_tags_list = ast.literal_eval(config_nsx.get("terraformware", "nsx_tags"))

    return nsx_tags_list


def get_datacenter(dc_name):
    """get datacenter name from Consul"""
    c_client = consul_connector()
    _, params_dict = c_client.kv.get(f"{settings.CONSUL_CONFIG_BASE}/params.conf")
    params = params_dict["Value"].decode("utf-8")
    config_dc = configparser.RawConfigParser(allow_no_value=True)
    config_dc.read_string(params)
    dc_dict = ast.literal_eval(config_dc.get("terraformware", "datacenter_mapping"))

    return dc_dict[dc_name][0], dc_dict[dc_name][1]
