"""Discover orphaned YAML files in /data"""
import logging
import re

from enc_core.enc_data import load_map
from .tools import EncSyncError
from .tools import get_puppetdb_nodes


logger = logging.getLogger(__name__)


def _get_keys(what: str) -> list[str]:
    return list(load_map(what).keys())


def discover_orphan_hosts(puppetdb_nodes: list[str]) -> list[str]:
    """
    Discover hosts elements in YAML not matching any certname from PuppetDB.
    """
    hosts = _get_keys("hosts")
    orphans = sorted(set(hosts) - set(puppetdb_nodes))
    return orphans


def _selector_matches_fqdn(selector: str, fqdn: str) -> bool:
    selector = selector.strip()
    if not selector:
        return False

    is_regex_selector = (
        len(selector) >= 2 and selector.startswith("/") and selector.endswith("/")
    )
    if is_regex_selector:
        pattern = selector[1:-1]
        try:
            return re.fullmatch(pattern, fqdn) is not None
        except re.error as err:
            logger.warning("Skipping invalid regex selector '%s': %s", selector, err)
            return False

    return fqdn.startswith(selector)


def _first_matching_group_name(groups: dict, fqdn: str) -> str | None:
    for group_name, group_data in groups.items():
        if group_name == "default":
            continue

        selectors = group_data.get("hosts", []) if isinstance(group_data, dict) else []
        for host_selector in selectors:
            if _selector_matches_fqdn(str(host_selector), fqdn):
                return group_name

    if "default" in groups:
        return "default"
    return None


def discover_orphan_groups(puppetdb_nodes: list[str]) -> dict[str, list[str]]:
    """
    Discover groups that are never selected for current PuppetDB nodes.

    Resolution model mirrors ENC behavior:
    - host entries in hosts.yaml always win and bypass groups
    - among groups, first matching group in YAML order wins
    - selector syntax: prefix or /regex/

    Returns a dict with:
    - orphan_groups: all groups never selected
    - never_matching_groups: groups whose selectors match no node
    - shadowed_groups: selectors match nodes but group is never selected due precedence
    """
    hosts = load_map("hosts")
    groups = load_map("groups")

    ordered_groups = list(groups.keys())
    non_default_groups = [name for name in ordered_groups if name != "default"]

    candidate_hits = {name: 0 for name in non_default_groups}
    selected_hits = {name: 0 for name in ordered_groups}

    for fqdn in sorted(set(puppetdb_nodes)):
        if fqdn in hosts:
            continue

        for group_name in non_default_groups:
            group_data = groups.get(group_name, {})
            selectors = (
                group_data.get("hosts", []) if isinstance(group_data, dict) else []
            )
            if any(_selector_matches_fqdn(str(item), fqdn) for item in selectors):
                candidate_hits[group_name] += 1

        winner = _first_matching_group_name(groups, fqdn)
        if winner is not None:
            selected_hits[winner] = selected_hits.get(winner, 0) + 1

    orphan_groups = sorted(
        [group_name for group_name, count in selected_hits.items() if count == 0]
    )

    never_matching_groups = sorted(
        [
            group_name
            for group_name in non_default_groups
            if selected_hits.get(group_name, 0) == 0
            and candidate_hits.get(group_name, 0) == 0
        ]
    )

    shadowed_groups = sorted(
        [
            group_name
            for group_name in non_default_groups
            if selected_hits.get(group_name, 0) == 0
            and candidate_hits.get(group_name, 0) > 0
        ]
    )

    return {
        "orphan_groups": orphan_groups,
        "never_matching_groups": never_matching_groups,
        "shadowed_groups": shadowed_groups,
    }


def main() -> int:
    """Main entry point for the spring cleaning script."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    try:
        puppetdb_nodes = get_puppetdb_nodes()
    except EncSyncError as err:
        logger.error("%s", err)
        return 1

    orphan_hosts = discover_orphan_hosts(puppetdb_nodes)
    orphan_groups_data = discover_orphan_groups(puppetdb_nodes)

    print(f"PuppetDB nodes: {len(puppetdb_nodes)}")
    print(f"Orphan hosts: {len(orphan_hosts)}")
    for host in orphan_hosts:
        print(f"  - {host}")

    print(f"Orphan groups: {len(orphan_groups_data['orphan_groups'])}")
    for group_name in orphan_groups_data["orphan_groups"]:
        print(f"  - {group_name}")

    print(
        "Never-matching groups: " f"{len(orphan_groups_data['never_matching_groups'])}"
    )
    for group_name in orphan_groups_data["never_matching_groups"]:
        print(f"  - {group_name}")

    print(f"Shadowed groups: {len(orphan_groups_data['shadowed_groups'])}")
    for group_name in orphan_groups_data["shadowed_groups"]:
        print(f"  - {group_name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
