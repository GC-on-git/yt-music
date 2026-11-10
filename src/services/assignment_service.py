"""Local destination playlist assignment logic."""

from __future__ import annotations

from typing import Any, Sequence

from src.db.repository import Repository

PREDESIGNED_DESCRIPTION = (
    "Pre-designed from an imported playlist excluded from Smart Assign."
)


def track_label(title: str, artists: str | None = None, album: str | None = None) -> str:
    parts = [title.strip() or "Untitled"]
    if artists and str(artists).strip():
        parts.append(str(artists).strip())
    if album and str(album).strip():
        parts.append(str(album).strip())
    return " — ".join(parts)


def labeled_track_map(rows: Sequence[Any]) -> dict[str, int]:
    """Unique title-first labels mapped to track ids."""
    counts: dict[str, int] = {}
    labels: list[tuple[str, int]] = []
    for row in rows:
        base = track_label(row["title"], row["artists"])
        counts[base] = counts.get(base, 0) + 1
        labels.append((base, int(row["id"])))
    used: dict[str, int] = {}
    out: dict[str, int] = {}
    for base, track_id in labels:
        if counts[base] == 1:
            label = base
        else:
            used[base] = used.get(base, 0) + 1
            label = f"{base} ({used[base]})"
        out[label] = track_id
    return out


class AssignmentService:
    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    def create_destination(self, name: str, description: str | None = None) -> int:
        name = name.strip()
        if not name:
            raise ValueError("Destination playlist name is required.")
        dest_id = self.repo.create_destination(name, description)
        self.repo.conn.commit()
        return dest_id

    def sync_predesigned_from_excluded_sources(self) -> dict[str, int]:
        """Turn excluded source playlists into destination playlists with their tracks."""
        sources = self.repo.list_source_playlists()
        excluded = [row for row in sources if not row["include_in_smart_assign"]]
        included_names = {
            str(row["title"]).strip().lower()
            for row in sources
            if row["include_in_smart_assign"] and str(row["title"]).strip()
        }

        created = 0
        updated = 0
        assigned = 0
        removed = 0

        for dest in self.repo.list_destinations():
            if not is_predesigned_playlist(dest.description):
                continue
            if dest.name.strip().lower() in included_names:
                self.repo.delete_destination(dest.id)
                removed += 1

        for source in excluded:
            name = str(source["title"] or "").strip()
            if not name:
                continue
            existing = self.repo.get_destination_by_name(name)
            if existing is None:
                dest_id = self.repo.create_destination(name, PREDESIGNED_DESCRIPTION)
                created += 1
            else:
                dest_id = existing.id
                if is_predesigned_playlist(existing.description):
                    updated += 1
                elif not (existing.description or "").strip():
                    self.repo.update_destination(
                        dest_id,
                        description=PREDESIGNED_DESCRIPTION,
                        set_description=True,
                    )
                    updated += 1
            assigned += self.repo.assign_source_playlist_to_destination(
                int(source["id"]), dest_id
            )

        self.repo.conn.commit()
        return {
            "created": created,
            "updated": updated,
            "assigned": assigned,
            "removed": removed,
            "excluded": len(excluded),
        }

    def rename_destination(self, dest_id: int, name: str) -> None:
        self.update_destination(dest_id, name=name)

    def update_destination(
        self,
        dest_id: int,
        *,
        name: str | None = None,
        description: str | None = None,
        set_description: bool = False,
    ) -> None:
        if name is not None and not name.strip():
            raise ValueError("Destination playlist name is required.")
        if name is None and not set_description:
            raise ValueError("Nothing to update.")
        cleaned_description = None
        if set_description:
            cleaned_description = description.strip() if description and description.strip() else None
        self.repo.update_destination(
            dest_id,
            name=name,
            description=cleaned_description,
            set_description=set_description,
        )
        self.repo.conn.commit()

    def merge_destinations(
        self,
        source_ids: Sequence[int],
        target_id: int,
        *,
        name: str | None = None,
        description: str | None = None,
        set_description: bool = False,
    ) -> int:
        unique_sources = {int(item) for item in source_ids}
        if int(target_id) not in unique_sources:
            unique_sources.add(int(target_id))
        if len(unique_sources) < 2:
            raise ValueError("Pick at least two playlists to merge.")
        moved = self.repo.merge_destinations(source_ids, target_id)
        if name is not None or set_description:
            self.update_destination(
                target_id,
                name=name,
                description=description,
                set_description=set_description,
            )
        else:
            self.repo.conn.commit()
        return moved

    def delete_destination(self, dest_id: int) -> None:
        self.repo.delete_destination(dest_id)
        self.repo.conn.commit()

    def assign(self, track_id: int, destination_id: int) -> None:
        self.repo.assign_track(track_id, destination_id)
        self.repo.conn.commit()

    def toggle(self, track_id: int, destination_id: int) -> bool:
        """Add or remove one playlist. Other assignments stay. Returns True if now assigned."""
        current = self.repo.get_assignment_destination_ids(track_id)
        if destination_id in current:
            self.unassign(track_id, destination_id)
            return False
        self.assign(track_id, destination_id)
        return True

    def unassign(self, track_id: int, destination_id: int | None = None) -> None:
        self.repo.unassign_track(track_id, destination_id)
        self.repo.conn.commit()

    def set_assignments(self, track_id: int, destination_ids: Sequence[int]) -> None:
        self.repo.set_track_assignments(track_id, destination_ids)
        self.repo.conn.commit()

    def bulk_assign(self, track_ids: Sequence[int], destination_id: int) -> int:
        count = self.repo.bulk_assign(track_ids, destination_id)
        self.repo.conn.commit()
        return count

    def assign_labels(self, labels: Sequence[str], mapping: dict[str, int], destination_id: int) -> int:
        ids = [mapping[label] for label in labels if label in mapping]
        return self.bulk_assign(ids, destination_id)

    def undo(self) -> bool:
        ok = self.repo.undo_last_assignment()
        self.repo.conn.commit()
        return ok


def is_predesigned_playlist(description: str | None = None) -> bool:
    from src.models.state_machines import DestinationOrigin

    return DestinationOrigin.from_playlist("", description) == DestinationOrigin.PREDESIGNED
