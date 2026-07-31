"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

from agent import __version__
from agent.bridge_state import (
    DEFAULT_HEARTBEAT_MAX_AGE_SECONDS,
    BridgeStateError,
    bridge_is_healthy,
    heartbeat_age_seconds,
    load_bridge_state,
)
from agent.client import AgentClientError, CommandTimeoutError
from agent.paths import PathConfigurationError
from providers.resolve import ResolveProviderClient

EXIT_SUCCESS = 0
EXIT_ERROR = 1
EXIT_TIMEOUT = 3
DEFAULT_COMMAND_TIMEOUT_SECONDS = 30.0


def _add_request_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_COMMAND_TIMEOUT_SECONDS,
        help="Seconds to wait for ResolveBridge to process the command.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print the machine-readable result.",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        prog="davinci-agent",
        description="Local, provider-neutral video editor automation agent.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command")

    status_parser = subparsers.add_parser(
        "status",
        help="Show the latest cached Resolve bridge heartbeat.",
    )
    status_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print the machine-readable bridge state.",
    )
    status_parser.add_argument(
        "--max-age-seconds",
        type=int,
        default=DEFAULT_HEARTBEAT_MAX_AGE_SECONDS,
        help="Maximum healthy heartbeat age.",
    )

    ping_parser = subparsers.add_parser(
        "ping",
        help="Send a validated ping command to ResolveBridge.",
    )
    _add_request_options(ping_parser)

    resolve_parser = subparsers.add_parser(
        "resolve",
        help="Send a validated read-only command to ResolveBridge.",
    )
    resolve_subparsers = resolve_parser.add_subparsers(dest="resolve_command")
    for command, help_text in (
        ("bridge", "Show live bridge and Resolve information."),
        ("capabilities", "Discover live Resolve provider capabilities."),
        ("project", "Show the current Resolve project."),
        ("timelines", "List timelines in the current Resolve project."),
        ("timeline", "Show the current Resolve timeline."),
        ("snapshot", "Collect the current workspace in one bridge run."),
        ("render-options", "Discover render formats, codecs, presets, and jobs."),
    ):
        request_parser = resolve_subparsers.add_parser(command, help=help_text)
        _add_request_options(request_parser)
    return parser


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _run_status(*, json_output: bool, max_age_seconds: int) -> int:
    if max_age_seconds < 1:
        raise BridgeStateError("--max-age-seconds must be greater than zero.")

    state = load_bridge_state()
    healthy = bridge_is_healthy(state, max_age_seconds=max_age_seconds)
    if json_output:
        _print_json(state)
    else:
        age = heartbeat_age_seconds(state)
        product_name = state.get("product_name") or "unknown"
        version = state.get("resolve_version") or "unknown"
        project_name = state.get("project_name") or "(no project open)"
        timeline_name = state.get("current_timeline_name") or "(no timeline open)"
        print(f"Bridge: {state['status']}")
        print(f"Heartbeat age: {age:.1f}s")
        print(f"Resolve: {product_name} {version}")
        print(f"Project: {project_name}")
        print(f"Timeline: {timeline_name}")
    return EXIT_SUCCESS if healthy else EXIT_ERROR


def _create_resolve_client() -> ResolveProviderClient:
    return ResolveProviderClient()


def _run_ping(*, timeout_seconds: float, json_output: bool) -> int:
    result = _create_resolve_client().ping(timeout_seconds)
    if json_output:
        _print_json({"message": result})
    else:
        print(result)
    return EXIT_SUCCESS


def _run_resolve_request(
    command: str,
    *,
    timeout_seconds: float,
    json_output: bool,
) -> int:
    client = _create_resolve_client()
    if command == "bridge":
        result: Any = client.bridge_info(timeout_seconds)
    elif command == "capabilities":
        result = client.capabilities(timeout_seconds)
    elif command == "project":
        result = client.current_project(timeout_seconds)
    elif command == "timelines":
        result = client.timelines(timeout_seconds)
    elif command == "timeline":
        result = client.current_timeline(timeout_seconds)
    elif command == "snapshot":
        result = client.workspace_snapshot(timeout_seconds)
    elif command == "render-options":
        result = client.render_environment(timeout_seconds)
    else:
        raise AgentClientError(f"Unknown Resolve CLI command: {command}")

    if json_output:
        _print_json(result)
        return EXIT_SUCCESS

    if command == "capabilities":
        for name, value in sorted(result.items()):
            print(f"{name}: {str(value).lower()}")
    elif command == "project":
        print("No Resolve project is open." if result is None else result["name"])
    elif command == "timelines":
        if not result:
            print("No timelines are present.")
        else:
            for timeline in result:
                print(f"{timeline['index']}: {timeline['name']}")
    elif command == "timeline":
        print("No Resolve timeline is open." if result is None else result["name"])
    elif command == "render-options":
        current = result["current"]
        print(
            "Current: "
            f"{current.get('format') or 'unknown'} / "
            f"{current.get('codec') or 'unknown'}"
        )
        print(f"Formats: {len(result['formats'])}")
        print(f"Presets: {len(result['presets'])}")
        print(f"Queued jobs: {len(result['jobs'])}")
    elif command == "snapshot":
        project = result["project"]
        current_timeline = result["current_timeline"]
        timeline_items = result["timeline_items"]
        print(f"Project: {project['name']}")
        print(f"Timelines: {len(result['timelines'])}")
        print(
            "Current timeline: "
            + (
                "(none)"
                if current_timeline is None
                else str(current_timeline["name"])
            )
        )
        print(
            "Timeline items: "
            + (
                "0"
                if timeline_items is None
                else str(len(timeline_items["items"]))
            )
        )
        print(f"Media Pool items: {len(result['media_pool']['items'])}")
        print(f"Render formats: {len(result['render']['formats'])}")
    else:
        for name, value in sorted(result.items()):
            print(f"{name}: {value}")
    return EXIT_SUCCESS


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the command-line interface."""
    parser = build_parser()
    parsed = parser.parse_args(arguments)

    try:
        if parsed.command == "status":
            return _run_status(
                json_output=parsed.json_output,
                max_age_seconds=parsed.max_age_seconds,
            )
        if parsed.command == "ping":
            return _run_ping(
                timeout_seconds=parsed.timeout_seconds,
                json_output=parsed.json_output,
            )
        if parsed.command == "resolve" and parsed.resolve_command is not None:
            return _run_resolve_request(
                parsed.resolve_command,
                timeout_seconds=parsed.timeout_seconds,
                json_output=parsed.json_output,
            )
    except CommandTimeoutError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_TIMEOUT
    except (
        AgentClientError,
        BridgeStateError,
        PathConfigurationError,
        ValueError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR

    parser.print_help()
    return EXIT_SUCCESS


if __name__ == "__main__":
    raise SystemExit(main())
