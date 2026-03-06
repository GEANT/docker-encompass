"""Rotate encrypted CSR challengePassword entries."""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from csr_store import csr_attributes


class Command(BaseCommand):
    help = "Rotate CSR challengePassword values for host/group entries"

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
            help="Rotate all existing entries from the encrypted store",
        )
        parser.add_argument(
            "--show-values",
            action="store_true",
            help="Print rotated plaintext challengePassword values (use carefully)",
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

        rotated = csr_attributes.rotate_many(entities)
        if not rotated:
            self.stdout.write("No entries rotated")
            return

        self.stdout.write(f"Rotated {len(rotated)} CSR challengePassword value(s)")

        if options["show_values"]:
            for entity, challenge_password in sorted(rotated.items()):
                self.stdout.write(f"{entity} {challenge_password}")
        else:
            for entity in sorted(rotated.keys()):
                self.stdout.write(entity)
