"""M55.1 machine-local source binding for approved take sequences."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Protocol

from agent.contracts import validate_contract
from agent.paths import take_sequence_bindings_directory
from agent.take_selection import media_file_identity
from transports.filesystem import atomic_write_json, read_json_object

BINDING_VERSION = "1.0"
MAX_SOURCES = 100


class TakeSequenceBindingError(ValueError):
    """Raised when local files cannot safely bind to an approved sequence."""


class TakeSequenceReader(Protocol):
    """Read-only approved sequence boundary consumed by M55.1."""

    def get(self, sequence_id: str) -> dict[str, Any]: ...


class LocalMediaPolicy(Protocol):
    """Existing allowlisted source validation boundary."""

    def validate_files(self, paths: list[str]) -> list[str]: ...


class TakeSequenceBindingWorkflow:
    """Bind approved entries to exact machine-local files without Resolve."""

    def __init__(
        self,
        sequences: TakeSequenceReader,
        media_policy: LocalMediaPolicy,
        bindings_root: Path | None = None,
    ) -> None:
        self._sequences = sequences
        self._media_policy = media_policy
        self._bindings_root = (
            bindings_root or take_sequence_bindings_directory()
        )

    def bind(
        self,
        *,
        sequence_id: str,
        sources: list[dict[str, str | int]],
    ) -> dict[str, Any]:
        """Validate and persist one private path binding plus redacted receipt."""
        sequence = self._sequences.get(sequence_id)
        entries = sequence.get("entries")
        if not isinstance(entries, list) or not entries:
            raise TakeSequenceBindingError("Approved take sequence is incomplete.")
        normalized = _source_inputs(sources, len(entries))
        paths = self._media_policy.validate_files(
            [source["path"] for source in normalized]
        )
        private_sources: list[dict[str, Any]] = []
        public_sources: list[dict[str, Any]] = []
        entries_by_order = {
            entry.get("order"): entry
            for entry in entries
            if isinstance(entry, dict)
        }
        if len(entries_by_order) != len(entries):
            raise TakeSequenceBindingError("Approved sequence entry order is invalid.")
        for source, path_value in zip(normalized, paths, strict=True):
            order = source["order"]
            entry = entries_by_order.get(order)
            if not isinstance(entry, dict):
                raise TakeSequenceBindingError(
                    f"Source order is not present in the sequence: {order}"
                )
            path = Path(path_value).resolve()
            identity = media_file_identity(path)
            if any(
                identity[field] != entry.get(field)
                for field in ("display_name", "fingerprint", "size_bytes")
            ):
                raise TakeSequenceBindingError(
                    f"Source file does not match approved entry {order}."
                )
            public_source = {
                "order": order,
                "selected_candidate_id": entry["selected_candidate_id"],
                **identity,
            }
            if "source_range" in entry:
                public_source["source_range"] = entry["source_range"]
            public_sources.append(public_source)
            private_sources.append({**public_source, "path": str(path)})
        private_payload = {
            "binding_version": BINDING_VERSION,
            "sequence_id": sequence["sequence_id"],
            "sequence_sha256": _canonical_sha256(sequence),
            "sources": private_sources,
        }
        binding_id = _canonical_sha256(private_payload)
        public_payload = {
            "binding_version": BINDING_VERSION,
            "binding_id": binding_id,
            "status": "bound",
            "sequence_id": sequence["sequence_id"],
            "sequence_sha256": private_payload["sequence_sha256"],
            "sources": public_sources,
            "source_count": len(public_sources),
            "paths_redacted": True,
            "timeline_modified": False,
            "apply_supported": False,
        }
        validate_contract("take-sequence-binding", public_payload)
        self._bindings_root.mkdir(parents=True, exist_ok=True)
        public_path = self._bindings_root / f"{binding_id}.json"
        private_path = self._bindings_root / f"{binding_id}.private.json"
        private_artifact = {
            **private_payload,
            "binding_id": binding_id,
            "private_sha256": _canonical_sha256(private_payload),
        }
        if public_path.is_file() or private_path.is_file():
            existing = self.get(binding_id)
            existing_private = self._private(binding_id)
            if existing != public_payload or existing_private != private_artifact:
                raise TakeSequenceBindingError(
                    "Stored source binding does not match exact replay."
                )
            return existing
        atomic_write_json(private_path, private_artifact)
        atomic_write_json(public_path, public_payload)
        return public_payload

    def get(self, binding_id: str) -> dict[str, Any]:
        """Return only the redacted canonical binding receipt."""
        identifier = _sha256(binding_id, "binding_id")
        path = self._bindings_root / f"{identifier}.json"
        if not path.is_file():
            raise TakeSequenceBindingError("The take-sequence binding was not found.")
        result = read_json_object(path)
        validate_contract("take-sequence-binding", result)
        if result.get("binding_id") != identifier:
            raise TakeSequenceBindingError("Stored binding identity is invalid.")
        private = self._private(identifier)
        expected = {
            "binding_version": private["binding_version"],
            "binding_id": identifier,
            "status": "bound",
            "sequence_id": private["sequence_id"],
            "sequence_sha256": private["sequence_sha256"],
            "sources": [
                {key: value for key, value in source.items() if key != "path"}
                for source in private["sources"]
            ],
            "source_count": len(private["sources"]),
            "paths_redacted": True,
            "timeline_modified": False,
            "apply_supported": False,
        }
        if result != expected:
            raise TakeSequenceBindingError("Stored public binding is invalid.")
        return result

    def resolve_sources(self, binding_id: str) -> list[dict[str, Any]]:
        """Return private sources only to in-process future M55 orchestration."""
        sources = list(self._private(binding_id)["sources"])
        paths = self._media_policy.validate_files(
            [source["path"] for source in sources]
        )
        verified: list[dict[str, Any]] = []
        for source, path_value in zip(sources, paths, strict=True):
            identity = media_file_identity(Path(path_value))
            if any(
                identity[field] != source.get(field)
                for field in ("display_name", "fingerprint", "size_bytes")
            ):
                raise TakeSequenceBindingError(
                    f"Bound source file changed for order {source['order']}."
                )
            verified.append({**source, "path": str(Path(path_value).resolve())})
        return verified

    def _private(self, binding_id: str) -> dict[str, Any]:
        identifier = _sha256(binding_id, "binding_id")
        path = self._bindings_root / f"{identifier}.private.json"
        if not path.is_file():
            raise TakeSequenceBindingError("Private source binding is missing.")
        artifact = read_json_object(path)
        payload = {
            key: artifact.get(key)
            for key in (
                "binding_version",
                "sequence_id",
                "sequence_sha256",
                "sources",
            )
        }
        if (
            artifact.get("binding_id") != identifier
            or artifact.get("private_sha256") != _canonical_sha256(payload)
            or _canonical_sha256(payload) != identifier
            or not isinstance(artifact.get("sources"), list)
        ):
            raise TakeSequenceBindingError("Private source binding is invalid.")
        for source in artifact["sources"]:
            path_value = source.get("path") if isinstance(source, dict) else None
            if not isinstance(path_value, str) or not Path(path_value).is_absolute():
                raise TakeSequenceBindingError("Private source path is invalid.")
        return artifact


def _source_inputs(
    sources: list[dict[str, str | int]],
    expected_count: int,
) -> list[dict[str, Any]]:
    if (
        not isinstance(sources, list)
        or not 1 <= len(sources) <= MAX_SOURCES
        or len(sources) != expected_count
    ):
        raise TakeSequenceBindingError(
            "sources must contain exactly one entry per approved sequence item."
        )
    normalized: list[dict[str, Any]] = []
    orders: set[int] = set()
    for source in sources:
        if not isinstance(source, dict) or set(source) != {"order", "path"}:
            raise TakeSequenceBindingError("Each source requires only order and path.")
        order = source["order"]
        path = source["path"]
        if (
            not isinstance(order, int)
            or isinstance(order, bool)
            or not 1 <= order <= MAX_SOURCES
            or order in orders
            or not isinstance(path, str)
            or not path
        ):
            raise TakeSequenceBindingError("Source order or path is invalid.")
        orders.add(order)
        normalized.append({"order": order, "path": path})
    return normalized


def _sha256(value: str, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise TakeSequenceBindingError(f"{name} must be a lowercase SHA-256 ID.")
    return value


def _canonical_sha256(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
