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

# Keep the existing output path/URL so Coolify does not need to change.
OUTPUT_PATH = Path("fakegaming-torbox.json")
OUTPUT_RAW_URL = (
    "https://raw.githubusercontent.com/"
    "Zeffuro/AIOS-Templates/"
    "refs/heads/main/fakegaming-torbox.json"
)

# Increment whenever this local transformation changes.
CUSTOM_REVISION = 3

# These are shown in AIOStreams' mandatory service selector. AIOStreams filters
# out any service disabled or unavailable on the instance.
DEBRID_SERVICES = [
    "torbox",
    "premiumize",
    "realdebrid",
    "alldebrid",
    "debridlink",
    "easydebrid",
    "debrider",
    "offcloud",
    "putio",
    "pikpak",
]

# Measured fast sources generally finish in ~0.4-1.2 seconds. Obscure titles
# still get a longer fallback window.
BALANCED_ADDON_TIMEOUT_MS = 3500
OPTIONAL_HTTP_TIMEOUT_MS = 1800
DYNAMIC_EXIT_CONDITION = (
    "(count(cached(totalStreams)) > 9 and totalTimeTaken > 1100) "
    "or totalTimeTaken > 3200"
)

# Torrentio rejects this VPS, Peerflix belongs to the direct-P2P path, and
# HdHub was timing out/failing almost every request on this server.
BANNED_ADDON_TYPES = ("torrentio", "peerflix", "hdhub")
FAST_PRESETS_TO_COPY = ("comet", "torrents-db")

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


def make_template_version(upstream_version: str, revision: int) -> str:
    """Convert an upstream x.y.z version to AIOStreams' numeric x.y.z format."""
    try:
        major, minor, patch = (
            int(part) for part in upstream_version.split(".")
        )
    except (TypeError, ValueError) as error:
        raise RuntimeError(
            f"Unsupported upstream template version: {upstream_version!r}"
        ) from error

    if not 1 <= revision <= 99:
        raise ValueError("CUSTOM_REVISION must be between 1 and 99.")

    # 3.0.4 + revision 3 -> 3.0.403
    return f"{major}.{minor}.{patch * 100 + revision}"


def remove_addon_type(value: Any, addon_type: str) -> tuple[Any, int]:
    """Recursively remove preset/addon objects of one AIOStreams type."""
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

            cleaned: dict[str, Any] = {}
            for key, item in node.items():
                cleaned_item = clean(item)
                if cleaned_item is not _DROP:
                    cleaned[key] = cleaned_item
            return cleaned

        if isinstance(node, list):
            cleaned_list: list[Any] = []
            for item in node:
                cleaned_item = clean(item)
                if cleaned_item is not _DROP:
                    cleaned_list.append(cleaned_item)
            return cleaned_list

        return node

    result = clean(value)
    return ({} if result is _DROP else result), removed_count


def contains_addon_type(value: Any, addon_type: str) -> bool:
    if isinstance(value, dict):
        preset = value.get("preset")
        if value.get("type") == addon_type:
            return True
        if isinstance(preset, dict) and preset.get("type") == addon_type:
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


def get_service_preset_switch(
    config: dict[str, Any],
) -> tuple[dict[str, Any], list[Any], list[Any]]:
    """Return the services switch, no-service branch, and service branch."""
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

    cases = service_switch.get("cases")
    no_service_branch = cases.get("") if isinstance(cases, dict) else None
    service_branch = service_switch.get("default")

    if not isinstance(no_service_branch, list):
        raise RuntimeError(
            "Upstream preset structure changed: missing no-service/P2P branch."
        )
    if not isinstance(service_branch, list):
        raise RuntimeError(
            "Upstream preset structure changed: missing service branch."
        )

    return service_switch, no_service_branch, service_branch


def copy_fast_presets_to_service_branch(
    no_service_branch: list[Any],
    service_branch: list[Any],
) -> list[str]:
    """Keep fast coverage sources, but force their direct-P2P output off."""
    existing_types = {
        item.get("type")
        for item in service_branch
        if isinstance(item, dict)
    }
    copied: list[str] = []

    for addon_type in FAST_PRESETS_TO_COPY:
        if addon_type in existing_types:
            continue

        source = next(
            (
                item
                for item in no_service_branch
                if isinstance(item, dict)
                and item.get("type") == addon_type
            ),
            None,
        )
        if source is None:
            raise RuntimeError(
                f"Upstream no longer contains the {addon_type!r} preset."
            )

        clone = copy.deepcopy(source)
        clone["category"] = "Debrid"

        options = clone.get("options")
        if isinstance(options, dict):
            if "includeP2P" in options:
                options["includeP2P"] = False
            if "showTorrentLinks" in options:
                options["showTorrentLinks"] = False

        service_branch.append(clone)
        existing_types.add(addon_type)
        copied.append(addon_type)

    return copied


def force_p2p_options_off(value: Any) -> tuple[int, int]:
    """Force every includeP2P/showTorrentLinks option to false."""
    include_p2p_changed = 0
    torrent_links_changed = 0

    def visit(node: Any) -> None:
        nonlocal include_p2p_changed, torrent_links_changed

        if isinstance(node, dict):
            if node.get("includeP2P") is True:
                node["includeP2P"] = False
                include_p2p_changed += 1
            if node.get("showTorrentLinks") is True:
                node["showTorrentLinks"] = False
                torrent_links_changed += 1
            for item in node.values():
                visit(item)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(value)
    return include_p2p_changed, torrent_links_changed


def has_true_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        if value.get(key) is True:
            return True
        return any(has_true_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(has_true_key(item, key) for item in value)
    return False


def remove_exact_list_value(value: Any, unwanted: str) -> Any:
    """Remove an exact string from nested lists without editing SEL text."""
    if isinstance(value, list):
        return [
            remove_exact_list_value(item, unwanted)
            for item in value
            if item != unwanted
        ]
    if isinstance(value, dict):
        return {
            key: remove_exact_list_value(item, unwanted)
            for key, item in value.items()
        }
    return value


def get_metadata_input(
    metadata: dict[str, Any],
    input_id: str,
) -> dict[str, Any]:
    inputs = metadata.get("inputs")
    if not isinstance(inputs, list):
        raise RuntimeError("Template metadata has no input list.")

    item = next(
        (
            entry
            for entry in inputs
            if isinstance(entry, dict) and entry.get("id") == input_id
        ),
        None,
    )
    if item is None:
        raise RuntimeError(f"Could not find template input {input_id!r}.")
    return item


def set_suboption_default(
    metadata: dict[str, Any],
    section_id: str,
    option_id: str,
    value: Any,
    *,
    description: str | None = None,
) -> None:
    section = get_metadata_input(metadata, section_id)
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
            f"Could not find template input {section_id}.{option_id}."
        )

    option["default"] = value
    if description is not None:
        option["description"] = description


def set_addon_timeouts(
    value: Any,
    addon_types: set[str],
    timeout_ms: int,
) -> int:
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


def harden_debrid_only_template(
    metadata: dict[str, Any],
    config: dict[str, Any],
) -> tuple[int, int, list[str]]:
    """
    Keep the multi-service selector, but make the empty-service path harmless.

    The server should also keep DISABLED_STREAM_TYPES=p2p as the final safety
    boundary. This template adds its own defence-in-depth controls as well.
    """
    service_switch, no_service_branch, service_branch = (
        get_service_preset_switch(config)
    )

    copied_fast_presets = copy_fast_presets_to_service_branch(
        no_service_branch,
        service_branch,
    )

    # A mandatory selector should make this unreachable. Emptying it means even
    # a UI bug or future regression cannot create the direct-P2P preset set.
    cases = service_switch.get("cases")
    assert isinstance(cases, dict)
    cases[""] = []

    inputs = metadata.get("inputs")
    if not isinstance(inputs, list):
        raise RuntimeError("Template metadata has no input list.")

    # Remove controls that only make sense for the now-disabled no-service mode.
    removed_input_ids = {"header.p2p", "sortingP2P"}
    before = len(inputs)
    metadata["inputs"] = [
        item
        for item in inputs
        if not (
            isinstance(item, dict)
            and item.get("id") in removed_input_ids
        )
    ]
    removed_inputs = before - len(metadata["inputs"])

    # Replace the upstream banner with an explicit safety statement.
    intro = get_metadata_input(metadata, "header.intro")
    intro.pop("__if", None)
    intro["name"] = "Debrid/Cloud Mode — Direct P2P Disabled"
    intro["description"] = (
        "Choose at least one supported service. Torrent indexes may be searched, "
        "but playable torrent results are resolved through the selected service; "
        "raw P2P streams are blocked by this template and by the server."
    )
    intro["intent"] = "success"

    core_filter = get_metadata_input(metadata, "coreFilterNonUsenet")
    core_filter["name"] = "SELect Engine: Debrid · HTTP"
    core_filter["description"] = (
        "Sets a range of streams kept per Quality/Resolution. Applies to cached "
        "debrid and HTTP streams; direct P2P streams are disabled. Enter 0 to "
        "disable this selection stage."
    )

    include_addon = get_metadata_input(metadata, "includeAddon")
    sub_options = include_addon.get("subOptions")
    if isinstance(sub_options, list):
        http_option = next(
            (
                item
                for item in sub_options
                if isinstance(item, dict)
                and item.get("id") == "httpAddons"
            ),
            None,
        )
        if isinstance(http_option, dict):
            http_option["description"] = (
                "Include direct HTTP fallback sources for niche or older titles. "
                "These are not BitTorrent/P2P streams, but they may be slower or "
                "less reliable than debrid sources."
            )

    # Defence in depth inside each saved profile.
    excluded = config.get("excludedStreamTypes")
    if not isinstance(excluded, list):
        raise RuntimeError(
            "Upstream excludedStreamTypes is no longer a list; review required."
        )
    if "p2p" not in excluded:
        excluded.append("p2p")

    if "preferredStreamTypes" in config:
        config["preferredStreamTypes"] = remove_exact_list_value(
            config["preferredStreamTypes"],
            "p2p",
        )

    colors = config.get("addonCategoryColors")
    if isinstance(colors, dict):
        color_values = colors.get("__value")
        if isinstance(color_values, dict):
            color_values.pop("P2P", None)

    include_p2p_changed, torrent_links_changed = force_p2p_options_off(
        config
    )

    return (
        removed_inputs,
        include_p2p_changed + torrent_links_changed,
        copied_fast_presets,
    )


def validate_generated_template(template: dict[str, Any]) -> None:
    metadata = template.get("metadata")
    config = template.get("config")
    if not isinstance(metadata, dict) or not isinstance(config, dict):
        raise RuntimeError("Generated template is missing metadata/config.")

    services = metadata.get("services")
    if services != DEBRID_SERVICES:
        raise RuntimeError(
            f"Unexpected service selector contents: {services!r}"
        )
    if metadata.get("serviceRequired") is not True:
        raise RuntimeError("The service selector must be mandatory.")

    for addon_type in BANNED_ADDON_TYPES:
        if contains_addon_type(config, addon_type):
            raise RuntimeError(
                f"Generated template still contains {addon_type!r}."
            )

    if has_true_key(config, "includeP2P"):
        raise RuntimeError("Generated template still has includeP2P=true.")
    if has_true_key(config, "showTorrentLinks"):
        raise RuntimeError(
            "Generated template still has showTorrentLinks=true."
        )

    excluded = config.get("excludedStreamTypes")
    if not isinstance(excluded, list) or "p2p" not in excluded:
        raise RuntimeError("Generated config does not exclude P2P streams.")

    service_switch, no_service_branch, _ = get_service_preset_switch(config)
    if no_service_branch:
        raise RuntimeError(
            "Generated no-service branch is not empty."
        )

    cases = service_switch.get("cases")
    if not isinstance(cases, dict) or cases.get("") != []:
        raise RuntimeError("No-service branch hardening was not preserved.")


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
            "Could not find upstream template id 'tamtaro.complete'."
        )

    template = copy.deepcopy(upstream)
    metadata = template.get("metadata")
    config = template.get("config")
    if not isinstance(metadata, dict) or not isinstance(config, dict):
        raise RuntimeError("Upstream template is missing metadata/config.")

    removed_by_type: dict[str, int] = {}
    for addon_type in BANNED_ADDON_TYPES:
        config, removed = remove_addon_type(config, addon_type)
        removed_by_type[addon_type] = removed
    template["config"] = config

    (
        removed_wizard_inputs,
        p2p_options_changed,
        copied_fast_presets,
    ) = harden_debrid_only_template(metadata, config)

    # Keep optional HTTP fallbacks available, but do not let them hold a request
    # open for the old five-second default when a user enables them.
    fallback_timeouts_changed = set_addon_timeouts(
        config,
        {"sootio", "webstreamr"},
        OPTIONAL_HTTP_TIMEOUT_MS,
    )

    # Return popular titles quickly; sparse titles still receive a fallback wait.
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
            "returns popular titles sooner."
        ),
    )

    upstream_version = str(metadata.get("version", "1.0.0"))
    custom_version = make_template_version(
        upstream_version,
        CUSTOM_REVISION,
    )

    metadata.update(
        {
            # Keep the existing ID so installed/cached copies update in place.
            "id": "zeffuro.fakegaming-torbox",
            "name": "Fakegaming Debrid (Safe & Balanced)",
            "description": (
                "Friends-and-family multi-service setup based on Tam-Taro's "
                "Complete SEL Setup. Users must select their own debrid/cloud "
                "service and provide their own credentials. TMDB/TVDB come from "
                "the server, Torrentio and unhealthy defaults are omitted, "
                "direct P2P is blocked, and dynamic fetching improves latency."
            ),
            "author": "TamTaro",
            "version": custom_version,
            "source": "external",
            "sourceUrl": OUTPUT_RAW_URL,
            "category": "Debrid",
            "services": DEBRID_SERVICES,
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

    validate_generated_template(template)

    OUTPUT_PATH.write_text(
        json.dumps([template], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(
        f"Generated {OUTPUT_PATH} from Tam-Taro "
        f"{upstream_version} as {custom_version}."
    )
    print(f"Service selector: {', '.join(DEBRID_SERVICES)}")
    print(
        "Removed addon presets: "
        + ", ".join(
            f"{addon_type}={count}"
            for addon_type, count in removed_by_type.items()
        )
    )
    print(f"Copied debrid-safe fast presets: {copied_fast_presets}")
    print(
        f"Removed {removed_wizard_inputs} P2P-only wizard section(s); "
        f"forced {p2p_options_changed} P2P/link option(s) off."
    )
    print(
        f"Set {fallback_timeouts_changed} optional HTTP fallback timeout(s) "
        f"to {OPTIONAL_HTTP_TIMEOUT_MS} ms."
    )
    print(f"Dynamic exit condition: {DYNAMIC_EXIT_CONDITION}")


if __name__ == "__main__":
    main()
