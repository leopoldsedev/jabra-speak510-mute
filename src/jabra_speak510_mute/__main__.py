from __future__ import annotations

import logging
import os
import sys

from . import logging_config
from .ha_integration import HAMuteLight
from .mute_watcher import MuteWatcher

log = logging.getLogger("jabra-mute")


def main() -> None:
    logging_config.configure()

    ha_url = os.environ.get("HA_URL", "").strip()
    ha_token = os.environ.get("HA_TOKEN", "").strip()
    ha_lights = [e.strip() for e in os.environ.get("HA_LIGHTS", "").split(",") if e.strip()]
    ha_fallback = os.environ.get("HA_FALLBACK_AUTOMATION", "").strip() or None

    callbacks = []
    if ha_url and ha_token and ha_lights:
        ha = HAMuteLight(ha_url, ha_token, ha_lights, fallback_automation=ha_fallback)
        callbacks.append(ha.on_mute_change)
        log.info(
            "Home Assistant integration enabled (%s, %d light(s)%s)",
            ha_url,
            len(ha_lights),
            f", fallback {ha_fallback}" if ha_fallback else "",
        )
        if ha_fallback:
            try:
                if not ha.fallback_exists():
                    log.error("fallback automation %s does not exist in Home Assistant", ha_fallback)
            except Exception as exc:
                log.warning("could not verify fallback automation %s: %s", ha_fallback, exc)
    else:
        log.info("Home Assistant integration disabled (HA_URL, HA_TOKEN, HA_LIGHTS not set)")

    def on_change(muted: bool) -> None:
        for cb in callbacks:
            cb(muted)

    try:
        MuteWatcher(on_change=on_change).run()
    except RuntimeError as exc:
        log.error("%s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
