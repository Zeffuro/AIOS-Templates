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

# Increment this whenever you make a local template change.
CUSTOM_REVISION = 1

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

    This handles both pre-template preset objects:

        {"type": "torrentio", ...}

    and already-expanded addon objects:

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

    cleaned_config, torrentio_removed = remove_addon_type(
        template["config"],
        "torrentio",
    )
    template["config"] = cleaned_config

    if contains_addon_type(template["config"], "torrentio"):
        raise RuntimeError(
            "Torrentio is still present after template cleanup."
        )

    metadata = template["metadata"]
    config = template["config"]

    upstream_version = str(metadata.get("version", "1.0.0"))
    custom_version = make_template_version(
        upstream_version,
        CUSTOM_REVISION,
    )

    metadata.update(
        {
            "id": "zeffuro.fakegaming-torbox",
            "name": "Fakegaming TorBox Setup",
            "description": (
                "Friends-and-family TorBox setup based on Tam-Taro's "
                "Complete SEL Setup. TMDB and TVDB are supplied by this "
                "AIOStreams instance. Each user supplies their own TorBox "
                "account. Torrentio is omitted because it blocks this "
                "server's outbound IP range."
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

    # Use the instance-wide AIOStreams metadata credentials.
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
        f"Removed {torrentio_removed} Torrentio "
        f"preset object(s)."
    )


if __name__ == "__main__":
    main()
