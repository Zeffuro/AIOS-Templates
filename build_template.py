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

# Change this when using a different repository name or path.
OUTPUT_RAW_URL = (
    "https://raw.githubusercontent.com/"
    "Zeffuro/AIOS-Templates/"
    "refs/heads/main/fakegaming-torbox.json"
)

CUSTOM_REVISION = 1


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


def main() -> None:
    templates = download_upstream()

    upstream = next(
        (
            template
            for template in templates
            if template.get("metadata", {}).get("id") == "tamtaro.complete"
        ),
        None,
    )

    if upstream is None:
        raise RuntimeError(
            "Could not find the upstream template with id 'tamtaro.complete'."
        )

    template = copy.deepcopy(upstream)
    metadata = template["metadata"]
    config = template["config"]

    upstream_version = str(metadata.get("version", "1.0.0"))

    metadata.update(
        {
            "id": "zeffuro.fakegaming-torbox",
            "name": "Fakegaming TorBox Setup",
            "description": (
                "Friends-and-family TorBox configuration based on Tam-Taro's "
                "Complete SEL Setup. TMDB and TVDB are supplied by this "
                "AIOStreams instance; each user provides only their own "
                "TorBox account."
            ),
            "author": "TamTaro",
            "version": f"{upstream_version}+fg.{CUSTOM_REVISION}",
            "source": "external",
            "sourceUrl": OUTPUT_RAW_URL,
            "category": "TorBox",
            # Only show TorBox in the service step.
            "services": ["torbox"],
            # With one required service, AIOStreams proceeds directly to
            # that service's credentials.
            "serviceRequired": True,
            "setToSaveInstallMenu": True,
        }
    )

    # The upstream changelog describes the unmodified template and has a
    # different version history, so do not show it for this fork.
    metadata.pop("changelogUrl", None)
    metadata.pop("changelog", None)

    # Do not insert the real keys here.
    #
    # Empty values explicitly clear any old per-profile metadata credentials.
    # AIOStreams then uses TMDB_API_KEY and TVDB_API_KEY from the instance.
    config["tmdbApiKey"] = ""
    config["tvdbApiKey"] = ""

    # A one-item array is accepted in the same way as Tam-Taro's multi-template
    # file, but keeps the friend-facing template chooser simple.
    output = [template]

    OUTPUT_PATH.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(
        f"Generated {OUTPUT_PATH} from Tam-Taro {upstream_version} "
        f"as {metadata['version']}."
    )


if __name__ == "__main__":
    main()
