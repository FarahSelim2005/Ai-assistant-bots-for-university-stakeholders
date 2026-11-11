"""Rename document folders named by an old agent key (labs_research/) to the assistant's id,
the folder name used since migration 004. Run it once after applying 004; files are moved,
not changed, and nothing needs indexing again (the chunks already have the agent id).

Run from the backend folder:
    python -m scripts.move_agent_folders               # every tenant
    python -m scripts.move_agent_folders --tenant demo
    python -m scripts.move_agent_folders --dry-run     # only show what would move
"""
import argparse

from app import tenants
from app.agents import agents_of
from app.db import get_admin_connection, use_admin_login


def main() -> None:
    parser = argparse.ArgumentParser(description="Rename agent-key folders to agent-id folders.")
    parser.add_argument("--tenant", help="only this tenant (slug)")
    parser.add_argument("--dry-run", action="store_true", help="show what would move, move nothing")
    args = parser.parse_args()
    use_admin_login()

    with get_admin_connection() as conn:
        slugs = [slug for (slug,) in conn.execute("SELECT slug FROM tenants ORDER BY slug")]
    for slug in [args.tenant] if args.tenant else slugs:
        tenant = tenants.for_script(slug)
        root = tenants.data_dir(tenant)
        if not root.is_dir():
            continue
        agents = agents_of(tenant.id)
        for folder in sorted(p for p in root.iterdir() if p.is_dir()):
            matches = [a for a in agents if a.settings.template_key == folder.name]
            if len(matches) != 1:
                continue  # already an id folder, or not clearly one assistant's
            target = root / matches[0].name
            if target.exists():
                print(f"{slug}: {folder.name}/ not moved: {target.name}/ already exists")
                continue
            print(f"{slug}: {folder.name}/ -> {target.name}/ ({matches[0].display_name})")
            if not args.dry_run:
                folder.rename(target)


if __name__ == "__main__":
    main()
