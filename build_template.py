#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import urllib.request
from pathlib import Path
from typing import Any


UPSTREAM_URL = (
    "https://raw.githubusercontent.com/"
    "Tam-Taro/SEL-Filtering-and-Sorting/"
    "refs/heads/main/Tamtaro-All-Templates-for-AIOStreams.json"
)

OUTPUT_PATH = Path("fakegaming-torbox.json")

OUTPUT_RAW_URL = (
    "https://raw.githubusercontent.com/"
    "Zeffuro/AIOS-Templates/"
    "refs/heads/main/fakegaming-torbox.json"
)

# Increment this whenever you change your local transformation.
CUSTOM_REVISION = 2

# The fast sources on this server normally finish in about 0.4-1.2 seconds.
# Sparse titles are still allowed to wait longer for fallback sources.
BALANCED_ADDON_TIMEOUT_MS = 3500
OPTIONAL_HTTP_TIMEOUT_MS = 1800
DYNAMIC_EXIT_CONDITION = (
    "(count(cached(totalStreams)) > 9 and totalTimeTaken > 1100) "
    "or totalTimeTaken > 3200"
)

_DROP = object()


def download_upstream() -> list[dict[str, Any]]:
    request = urllib.request.Request(
        UPSTREAM_URL,
        headers={"User-Agent": "fakegaming-aiostreams-template-builder/1.0"},
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)

    if not isinstance(data, list):
        data = [data]

    return data


def make_template_version(
    upstream_version: str,
    revision: int,
) -> str:
    """
    AIOStreams currently requires a purely numeric x.y.z version.

    Examples:
        3.0.4 + revision 1 -> 3.0.401
        3.0.4 + revision 2 -> 3.0.402
        3.0.5 + revision 1 -> 3.0.501
    """
    try:
        major, minor, patch = (
            int(part) for part in upstream_version.split(".")
        )
    except (TypeError, ValueError) as error:
        raise RuntimeError(
            f"Unsupported upstream version: {upstream_version!r}"
        ) from error

    if not 1 <= revision <= 99:
        raise ValueError("CUSTOM_REVISION must be between 1 and 99.")

    return f"{major}.{minor}.{patch * 100 + revision}"


def remove_addon_type(
    value: Any,
    addon_type: str,
) -> tuple[Any, int]:
    """
    Remove an addon preset from every nested template branch.

    Handles both template preset objects:

        {"type": "torrentio", ...}

    and expanded addon objects:

        {"preset": {"type": "torrentio"}, ...}
    """
    removed_count = 0

    def clean(node: Any) -> Any:
        nonlocal removed_count

        if isinstance(node, dict):
            preset = node.get("preset")
            direct_match = node.get("type") == addon_type
            preset_match = (
                isinstance(preset, dict)
                and preset.get("type") == addon_type
            )

            if direct_match or preset_match:
                removed_count += 1
                return _DROP

            cleaned_dict: dict[str, Any] = {}

            for key, item in node.items():
                cleaned_item = clean(item)

                if cleaned_item is not _DROP:
                    cleaned_dict[key] = cleaned_item

            return cleaned_dict

        if isinstance(node, list):
            cleaned_list: list[Any] = []

            for item in node:
                cleaned_item = clean(item)

                if cleaned_item is not _DROP:
                    cleaned_list.append(cleaned_item)

            return cleaned_list

        return node

    result = clean(value)

    if result is _DROP:
        result = {}

    return result, removed_count


def contains_addon_type(
    value: Any,
    addon_type: str,
) -> bool:
    if isinstance(value, dict):
        preset = value.get("preset")

        if value.get("type") == addon_type:
            return True

        if (
            isinstance(preset, dict)
            and preset.get("type") == addon_type
        ):
            return True

        return any(
            contains_addon_type(item, addon_type)
            for item in value.values()
        )

    if isinstance(value, list):
        return any(
            contains_addon_type(item, addon_type)
            for item in value
        )

    return False


def force_torbox_preset_branch(
    config: dict[str, Any],
) -> tuple[int, list[str]]:
    """
    This fork is TorBox-only, so discard the upstream P2P/no-service branch.

    Preserve Comet and TorrentsDB from that branch because they are fast and
    reliable on this server, but configure them as debrid-only sources.
    """
    presets_wrapper = config.get("presets")

    if not isinstance(presets_wrapper, dict):
        raise RuntimeError("Template config has no presets wrapper.")

    service_switch = presets_wrapper.get("__value")

    if (
        not isinstance(service_switch, dict)
        or service_switch.get("__switch") != "services"
    ):
        raise RuntimeError(
            "Upstream preset structure changed: expected a services switch."
        )

    torbox_branch = service_switch.get("default")
    p2p_branch = service_switch.get("cases", {}).get("")

    if not isinstance(torbox_branch, list):
        raise RuntimeError(
            "Upstream preset structure changed: missing default service branch."
        )

    if not isinstance(p2p_branch, list):
        raise RuntimeError(
            "Upstream preset structure changed: missing P2P source branch."
        )

    selected = copy.deepcopy(torbox_branch)
    existing_types = {
        item.get("type")
        for item in selected
        if isinstance(item, dict)
    }
    added: list[str] = []

    for addon_type in ("comet", "torrents-db"):
        if addon_type in existing_types:
            continue

        source = next(
            (
                item
                for item in p2p_branch
                if isinstance(item, dict)
                and item.get("type") == addon_type
            ),
            None,
        )

        if source is None:
            raise RuntimeError(
                f"Upstream no longer contains the {addon_type!r} preset."
            )

        cloned = copy.deepcopy(source)
        cloned["category"] = "Debrid"

        options = cloned.get("options")
        if isinstance(options, dict) and "includeP2P" in options:
            options["includeP2P"] = False

        selected.append(cloned)
        added.append(addon_type)

    presets_wrapper["__value"] = selected
    return len(selected), added


def set_suboption_default(
    metadata: dict[str, Any],
    section_id: str,
    option_id: str,
    value: Any,
    *,
    description: str | None = None,
) -> None:
    inputs = metadata.get("inputs")

    if not isinstance(inputs, list):
        raise RuntimeError("Template metadata has no input list.")

    section = next(
        (
            item
            for item in inputs
            if isinstance(item, dict) and item.get("id") == section_id
        ),
        None,
    )

    if section is None:
        raise RuntimeError(f"Could not find template input {section_id!r}.")

    sub_options = section.get("subOptions")

    if not isinstance(sub_options, list):
        raise RuntimeError(
            f"Template input {section_id!r} has no sub-options."
        )

    option = next(
        (
            item
            for item in sub_options
            if isinstance(item, dict) and item.get("id") == option_id
        ),
        None,
    )

    if option is None:
        raise RuntimeError(
            f"Could not find template input "
            f"{section_id}.{option_id}."
        )

    option["default"] = value

    if description is not None:
        option["description"] = description


def set_addon_timeouts(
    value: Any,
    addon_types: set[str],
    timeout_ms: int,
) -> int:
    """Override timeout for selected fallback addon preset types."""
    changed = 0

    def visit(node: Any) -> None:
        nonlocal changed

        if isinstance(node, dict):
            if node.get("type") in addon_types:
                options = node.get("options")

                if isinstance(options, dict):
                    options["timeout"] = timeout_ms
                    changed += 1

            for item in node.values():
                visit(item)

        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(value)
    return changed


def main() -> None:
    templates = download_upstream()

    upstream = next(
        (
            template
            for template in templates
            if template.get("metadata", {}).get("id")
            == "tamtaro.complete"
        ),
        None,
    )

    if upstream is None:
        raise RuntimeError(
            "Could not find the upstream template "
            "with id 'tamtaro.complete'."
        )

    template = copy.deepcopy(upstream)
    metadata = template["metadata"]

    # Remove providers that cannot or should not be defaults on this server.
    config, torrentio_removed = remove_addon_type(
        template["config"],
        "torrentio",
    )
    template["config"] = config

    torbox_preset_count, copied_fast_presets = force_torbox_preset_branch(config)

    removed_by_type: dict[str, int] = {
        "torrentio": torrentio_removed,
    }

    # Peerflix belongs to the discarded P2P branch, but keep this guard in
    # case upstream adds it to the service branch later. HdHub currently fails
    # almost every request from this server.
    for addon_type in ("peerflix", "hdhub"):
        config, removed = remove_addon_type(config, addon_type)
        removed_by_type[addon_type] = removed

    template["config"] = config

    for addon_type in removed_by_type:
        if contains_addon_type(config, addon_type):
            raise RuntimeError(
                f"{addon_type} is still present after template cleanup."
            )

    # Keep niche HTTP fallbacks opt-in, but do not let them hold the whole
    # stream request open for five seconds when enabled.
    fallback_timeouts_changed = set_addon_timeouts(
        config,
        {"sootio", "webstreamr"},
        OPTIONAL_HTTP_TIMEOUT_MS,
    )

    # Popular titles return as soon as enough cached results arrive. Sparse
    # titles continue waiting for fallback sources up to the balanced ceiling.
    config["dynamicAddonFetching"] = {
        "__if": "inputs.addonPreset == default",
        "__value": {
            "enabled": True,
            "condition": DYNAMIC_EXIT_CONDITION,
        },
    }

    set_suboption_default(
        metadata,
        "includeAddon",
        "timeout",
        BALANCED_ADDON_TIMEOUT_MS,
        description=(
            "Maximum time per add-on request. The balanced default is "
            f"{BALANCED_ADDON_TIMEOUT_MS} ms; dynamic fetching normally "
            "returns popular titles much sooner."
        ),
    )

    upstream_version = str(metadata.get("version", "1.0.0"))
    custom_version = make_template_version(
        upstream_version,
        CUSTOM_REVISION,
    )

    metadata.update(
        {
            "id": "zeffuro.fakegaming-torbox",
            "name": "Fakegaming TorBox (Balanced)",
            "description": (
                "Friends-and-family TorBox setup based on Tam-Taro's "
                "Complete SEL Setup. It uses server-supplied TMDB/TVDB "
                "credentials, each user supplies their own TorBox account, "
                "Torrentio is omitted, and dynamic fetching avoids waiting "
                "for unhealthy fallback providers when enough results are "
                "already available."
            ),
            "author": "TamTaro",
            "version": custom_version,
            "source": "external",
            "sourceUrl": OUTPUT_RAW_URL,
            "category": "TorBox",
            "services": ["torbox"],
            "serviceRequired": True,
            "setToSaveInstallMenu": True,
        }
    )

    # The upstream changelog describes the unmodified template.
    metadata.pop("changelogUrl", None)
    metadata.pop("changelog", None)

    # Use instance-wide AIOStreams metadata credentials.
    config["tmdbApiKey"] = ""
    config["tvdbApiKey"] = ""

    output = [template]

    OUTPUT_PATH.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(
        f"Generated {OUTPUT_PATH} from Tam-Taro "
        f"{upstream_version} as {custom_version}."
    )
    print(
        f"Forced TorBox preset branch with {torbox_preset_count} entries; "
        f"copied fast presets: {copied_fast_presets}."
    )
    print(
        "Removed addon presets: "
        + ", ".join(
            f"{addon_type}={count}"
            for addon_type, count in removed_by_type.items()
        )
    )
    print(
        f"Set {fallback_timeouts_changed} optional HTTP fallback timeout(s) "
        f"to {OPTIONAL_HTTP_TIMEOUT_MS} ms."
    )
    print(f"Dynamic exit condition: {DYNAMIC_EXIT_CONDITION}")


if __name__ == "__main__":
    main()
