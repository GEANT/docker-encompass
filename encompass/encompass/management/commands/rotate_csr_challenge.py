"""Re-encrypt stored CSR challengePassword entries."""

from __future__ import annotations

import os

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from csr_store import csr_attributes


class Command(BaseCommand):
    """Re-encrypt CSR challengePassword values for host/group entries."""
    help = "Re-encrypt CSR challengePassword values for host/group entries"

    def add_arguments(self, parser):
        parser.add_argument(
            "--entity",
            action="append",
            default=[],
            help="Explicit entity name, e.g. host/node1.example.org",
        )
        parser.add_argument(
            "--host",
            action="append",
            default=[],
            help="Host name (mapped to host/<hostname>)",
        )
        parser.add_argument(
            "--group",
            action="append",
            default=[],
            help="Group name (mapped to group/<groupname>)",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Re-encrypt all existing entries from the encrypted store",
        )
        parser.add_argument(
            "--old-token",
            default="",
            help="Old CSR challenge token (defaults to CSR_CHALLENGE_OLD_KEY)",
        )
        parser.add_argument(
            "--new-token",
            default="",
            help="New CSR challenge token (defaults to CSR_CHALLENGE_KEY)",
        )
        parser.add_argument(
            "--show-values",
            action="store_true",
            help="Print plaintext challengePassword values after re-encryption (use carefully)",
        )

    def handle(self, *args, **options):
        entities = set(options["entity"] or [])
        for host in options["host"] or []:
            entities.add(csr_attributes.host_entity_name(host))
        for group in options["group"] or []:
            entities.add(csr_attributes.group_entity_name(group))

        if options["all"]:
            entities.update(csr_attributes.all_entity_names())

        entities = sorted(str(item).strip() for item in entities if str(item).strip())
        if not entities:
            raise CommandError(
                "No target selected. Use --entity/--host/--group or pass --all."
            )

        old_token = str(options.get("old_token") or "").strip() or str(
            os.environ.get("CSR_CHALLENGE_OLD_KEY", "")
        ).strip()
        new_token = str(options.get("new_token") or "").strip() or str(
            os.environ.get("CSR_CHALLENGE_KEY", "")
        ).strip()
        if not old_token:
            raise CommandError(
                "Old CSR token is required (use --old-token or CSR_CHALLENGE_OLD_KEY)."
            )
        if not new_token:
            raise CommandError(
                "New CSR token is required (use --new-token or CSR_CHALLENGE_KEY)."
            )
        if old_token == new_token:
            raise CommandError("Old and new CSR tokens must differ for re-encryption.")

        reencrypted = csr_attributes.reencrypt_many(entities, old_token, new_token)
        if not reencrypted:
            self.stdout.write("No entries re-encrypted")
            return

        self.stdout.write(
            f"Re-encrypted {len(reencrypted)} CSR challengePassword value(s)"
        )

        if options["show_values"]:
            for entity, challenge_password in sorted(reencrypted.items()):
                self.stdout.write(f"{entity} {challenge_password}")
        else:
            for entity in sorted(reencrypted.keys()):
                self.stdout.write(entity)
