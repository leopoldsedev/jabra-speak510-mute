"""Watch the Jabra Speak 510 hardware mute button.

The Speak 510 only forwards HID button events while it believes a call is
active, so this watcher writes an OffHook output report to gate the event
stream open, then reads PhoneMute toggle pulses and mirrors the resulting
state back to the MicMute LED so the LED always matches reality. The device
drops off-hook whenever it loses power (system suspend, USB autosuspend), so
the report is re-asserted every OFFHOOK_REFRESH_SECONDS. See the README's
"How it works" section for the report layout and discovery story.
"""

from __future__ import annotations

import glob
import logging
import os
import select
import signal
from typing import Callable

JABRA_VID = 0x0B0E
JABRA_PID = 0x0422

REPORT_ID = 0x03
INPUT_PHONE_MUTE_BIT = 1 << 4
OUT_OFFHOOK_BIT = 1 << 0
OUT_MIC_MUTE_LED_BIT = 1 << 5

OFFHOOK_REFRESH_SECONDS = 30.0

log = logging.getLogger(__name__)


def find_jabra_hidraw() -> str | None:
    for sys_path in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            with open(os.path.join(sys_path, "device/uevent")) as f:
                uevent = f.read()
        except FileNotFoundError:
            continue
        for line in uevent.splitlines():
            if not line.startswith("HID_ID="):
                continue
            parts = line.split("=", 1)[1].split(":")
            if len(parts) == 3 and int(parts[1], 16) == JABRA_VID and int(parts[2], 16) == JABRA_PID:
                return "/dev/" + os.path.basename(sys_path)
    return None


class MuteWatcher:
    """Hold the Speak 510 off-hook, read mute toggles, drive the LED, and
    invoke a callback on every state change."""

    def __init__(self, on_change: Callable[[bool], None] | None = None):
        self.on_change = on_change or (lambda _muted: None)
        self._muted = False
        self._last_mute_bit = False
        self._fd: int | None = None

    @property
    def muted(self) -> bool:
        return self._muted

    def _write_output(self, off_hook: bool, mic_mute_led: bool) -> None:
        b = (OUT_OFFHOOK_BIT if off_hook else 0) | (OUT_MIC_MUTE_LED_BIT if mic_mute_led else 0)
        log.debug("HID -> report %02x byte %02x", REPORT_ID, b)
        os.write(self._fd, bytes([REPORT_ID, b, 0x00]))

    def run(self) -> None:
        dev = find_jabra_hidraw()
        if not dev:
            raise RuntimeError(f"Jabra Speak 510 ({JABRA_VID:04x}:{JABRA_PID:04x}) not found")
        log.info("found device: %s", dev)

        try:
            self._fd = os.open(dev, os.O_RDWR)
        except PermissionError as exc:
            raise RuntimeError(f"permission denied opening {dev}; run as root or install the udev rule") from exc

        def shutdown(*_):
            log.info("shutting down: clearing off-hook, releasing device")
            try:
                self._write_output(off_hook=False, mic_mute_led=False)
            finally:
                if self._fd is not None:
                    os.close(self._fd)
                    self._fd = None
            raise SystemExit(0)

        signal.signal(signal.SIGINT, shutdown)
        signal.signal(signal.SIGTERM, shutdown)

        self._write_output(off_hook=True, mic_mute_led=False)
        log.info("ready — listening for mute toggles")

        try:
            while True:
                ready, _, _ = select.select([self._fd], [], [], OFFHOOK_REFRESH_SECONDS)
                if not ready:
                    self._write_output(off_hook=True, mic_mute_led=self._muted)
                    continue
                data = os.read(self._fd, 64)
                if len(data) < 2 or data[0] != REPORT_ID:
                    log.debug("HID <- ignoring report %s", data.hex())
                    continue
                log.debug("HID <- report 03 byte %02x", data[1])
                mute_bit = bool(data[1] & INPUT_PHONE_MUTE_BIT)
                # PhoneMute is declared relative in the descriptor, so a rising
                # edge (0 -> 1) is one button press.
                if mute_bit and not self._last_mute_bit:
                    self._muted = not self._muted
                    self._write_output(off_hook=True, mic_mute_led=self._muted)
                    log.info("MUTED" if self._muted else "unmuted")
                    try:
                        self.on_change(self._muted)
                    except Exception:
                        log.exception("on_change callback raised")
                self._last_mute_bit = mute_bit
        finally:
            if self._fd is not None:
                try:
                    self._write_output(off_hook=False, mic_mute_led=False)
                except Exception:
                    pass
                os.close(self._fd)
                self._fd = None
