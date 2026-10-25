from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from university.core.registry import registry


class Command(BaseCommand):
    help = "List installed University modules and what they contribute."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--permissions", action="store_true", help="Also list declared permissions.")

    def handle(self, *args: Any, **options: Any) -> None:
        for info in sorted(registry.all(), key=lambda m: m.name):
            requires = ", ".join(info.requires) or "-"
            self.stdout.write(f"{info.name:<16} {info.version:<10} {info.app_name:<32} requires: {requires}")
        if registry.plugins:
            self.stdout.write("\nEntry-point plugins: " + ", ".join(registry.plugins))
        missing = registry.missing_dependencies()
        for module, deps in missing.items():
            self.stderr.write(self.style.ERROR(f"{module} is missing: {', '.join(deps)}"))
        if options["permissions"]:
            self.stdout.write("\nPermissions:")
            for code, perm in sorted(registry.permissions.items()):
                flag = " [sensitive]" if perm.sensitive else ""
                self.stdout.write(f"  {code:<45} {', '.join(perm.scopes)}{flag}")
