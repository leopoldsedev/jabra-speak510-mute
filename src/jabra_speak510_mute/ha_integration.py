"""Drive Home Assistant lights from a mute state callback.

On mute: snapshot each light, set red.
On unmute: restore each light's previous color/brightness (or off state).
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from typing import Iterable

log = logging.getLogger(__name__)


class HAMuteLight:
    def __init__(
        self,
        url: str,
        token: str,
        lights: Iterable[str],
        mute_rgb: tuple[int, int, int] = (255, 0, 0),
        timeout: float = 5.0,
        fallback_automation: str | None = None,
    ):
        self.url = url.rstrip("/")
        self.token = token
        self.lights = list(lights)
        self.mute_rgb = mute_rgb
        self.timeout = timeout
        self.fallback_automation = fallback_automation
        self._saved: dict[str, dict] = {}

    def _request(self, method: str, path: str, body: dict | None = None) -> dict | None:
        req = urllib.request.Request(
            self.url + path,
            method=method,
            headers={
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json",
            },
            data=json.dumps(body).encode() if body is not None else None,
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            raw = resp.read()
        return json.loads(raw) if raw else None

    def _snapshot(self, entity_id: str) -> dict:
        # Force HA to re-poll the bulb first; otherwise rgb/xy can be stale.
        try:
            self._request("POST", "/api/services/homeassistant/update_entity", {"entity_id": entity_id})
        except Exception as exc:
            log.debug("update_entity failed for %s: %s", entity_id, exc)
        return self._request("GET", "/api/states/" + entity_id) or {}

    def _apply_red(self, entity_id: str) -> None:
        self._request("POST", "/api/services/light/turn_on", {
            "entity_id": entity_id,
            "rgb_color": list(self.mute_rgb),
        })

    def _restore(self, entity_id: str, snap: dict) -> None:
        if snap.get("state") != "on":
            self._request("POST", "/api/services/light/turn_off", {"entity_id": entity_id})
            return
        attrs = snap.get("attributes", {}) or {}
        body: dict = {"entity_id": entity_id}
        if attrs.get("brightness") is not None:
            body["brightness"] = attrs["brightness"]
        mode = attrs.get("color_mode")
        if mode == "color_temp" and attrs.get("color_temp_kelvin") is not None:
            body["color_temp_kelvin"] = attrs["color_temp_kelvin"]
        elif mode == "xy" and attrs.get("xy_color"):
            body["xy_color"] = attrs["xy_color"]
        elif mode == "hs" and attrs.get("hs_color"):
            body["hs_color"] = attrs["hs_color"]
        elif attrs.get("rgb_color"):
            body["rgb_color"] = attrs["rgb_color"]
        self._request("POST", "/api/services/light/turn_on", body)

    @staticmethod
    def _looks_invalid(snap: dict) -> bool:
        """Detect HA's 'I don't really know what color this is' sentinel.

        Hue lights via HA occasionally end up with color_mode=xy and an
        xy_color of [0.0, 0.0], which is not a real chromaticity coordinate.
        Restoring from such a snapshot pushes the wrong color back to the
        bulb (typically a deep blue).
        """
        if snap.get("state") != "on":
            return False
        attrs = snap.get("attributes", {}) or {}
        if attrs.get("color_mode") != "xy":
            return False
        xy = attrs.get("xy_color") or []
        return len(xy) == 2 and abs(xy[0]) < 1e-3 and abs(xy[1]) < 1e-3

    def on_mute_change(self, muted: bool) -> None:
        if muted:
            for light in self.lights:
                t0 = time.monotonic()
                try:
                    self._saved[light] = self._snapshot(light)
                    self._apply_red(light)
                    log.info("  %s -> red (%.0f ms)", light, (time.monotonic() - t0) * 1000)
                except Exception as exc:
                    log.warning("  %s: HA error on mute: %s", light, exc)
            return

        # Unmute: if any saved snapshot looks invalid AND a fallback automation
        # is configured, trigger it instead of per-light restore. The fallback
        # is responsible for putting the affected lights into a known-good
        # state.
        if self.fallback_automation and any(
            self._looks_invalid(self._saved.get(l, {})) for l in self.lights
        ):
            log.warning(
                "snapshot looks invalid (HA cache stale); triggering %s instead of restore",
                self.fallback_automation,
            )
            try:
                self._request("POST", "/api/services/automation/trigger", {"entity_id": self.fallback_automation})
            except Exception as exc:
                log.warning("HA error triggering fallback %s: %s", self.fallback_automation, exc)
            self._saved.clear()
            return

        for light in self.lights:
            snap = self._saved.pop(light, None)
            if snap is None:
                continue
            t0 = time.monotonic()
            try:
                self._restore(light, snap)
                log.info("  %s -> restored (%.0f ms)", light, (time.monotonic() - t0) * 1000)
            except Exception as exc:
                log.warning("  %s: HA error on unmute: %s", light, exc)
