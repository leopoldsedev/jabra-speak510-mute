# jabra-speak510-mute

A small Linux daemon that tracks the hardware mute button on a Jabra
Speak 510 USB speakerphone and, optionally, drives Home Assistant lights
based on its state.

> Disclaimer: this is a vibe-coded project. I had a problem, I worked it
> out in conversation with an LLM, and the result happens to work for
> me. The code is small and readable; treat it as a worked example, not
> as a polished product.

## What it does

- Watches the physical mute button on the Speak 510 and maintains an
  authoritative software mute state.
- Mirrors that state back to the device's MicMute LED so the LED matches
  reality even when the host application of the moment doesn't.
- Optionally, on every state change: sets a configured list of Home
  Assistant lights to red on mute, restores them to their previous
  colour and brightness on unmute.

## Status & scope

This is a single-user, single-setup project. It is hard-coded for the
Jabra Speak 510 (USB ID `0b0e:0422`); it reads HID reports directly using
the report layout decoded from that specific device. The Home Assistant
side is opinionated about what "mute means red" looks like.

There is no PyPI release and there are no plans for one. I am publishing
this because the discovery process behind it might be useful to others
who have a similar device and want to read state out of it without using
the official Jabra SDK.

## Requirements

- Linux with `hidraw` (i.e. anything with a recent kernel)
- Python 3.10+
- [`uv`](https://github.com/astral-sh/uv) for the venv
- A Jabra Speak 510
- (optional) A reachable Home Assistant instance + long-lived access token

## Install

```sh
git clone https://github.com/leopoldsedev/jabra-speak510-mute.git
cd jabra-speak510-mute
make install
```

`make install` will:

1. Run `uv sync` to create `./.venv` with the project installed in
   editable mode (the project has no runtime dependencies, but `uv`
   gives us a stable Python interpreter path for systemd).
2. Install `packaging/70-jabra-speak510.rules` into `/etc/udev/rules.d/`
   (one `sudo` prompt) so your user can open the device's hidraw node
   without root.
3. Write a `systemd --user` unit pointing at the venv's Python and
   `~/.config/jabra-speak510-mute/config.env`.
4. Create `~/.config/jabra-speak510-mute/config.env` from the example
   (mode `0600`) if it doesn't exist.
5. `daemon-reload`, then enable and start the unit.

After install, edit the config file (see below), then `make restart`.

`make uninstall` reverses everything, but keeps your config and `.venv`
in place. Run `make help` to see all targets, including service control
(`start` / `stop` / `restart` / `status` / `logs`).

### When does this need sudo?

Only for one thing: writing the udev rule into `/etc/udev/rules.d/` and
reloading the udev daemon. That happens inside `make install` (and
`make uninstall`); you'll see exactly two `sudo` invocations:

```
sudo install -m 0644 packaging/70-jabra-speak510.rules /etc/udev/rules.d/70-jabra-speak510.rules
sudo udevadm control --reload && sudo udevadm trigger
```

Everything else runs as your user:

- `uv sync` and `.venv` creation — your home directory.
- The systemd unit — installed under `~/.config/systemd/user/` and run
  via `systemctl --user`, i.e. as you, not as root.
- The daemon itself at runtime — reads and writes `/dev/hidraw*` for the
  Speak 510, but the udev rule's `TAG+="uaccess"` grants your seat user
  access to that node, so the daemon does not need to be root.

If you'd rather not install the udev rule, you can skip `make install`
and just run the daemon ad-hoc with `sudo`:

```sh
sudo HA_URL=... HA_TOKEN=... HA_LIGHTS=... uv run python -m jabra_speak510_mute
```

That's only useful for one-off testing — the systemd unit assumes the
udev rule is in place.

## Configuration

The unit reads `~/.config/jabra-speak510-mute/config.env`. Variables:

| Variable                 | Meaning                                                    |
|--------------------------|------------------------------------------------------------|
| `HA_URL`                 | Base URL of your Home Assistant instance. Empty = disable. |
| `HA_TOKEN`               | Long-lived access token.                                   |
| `HA_LIGHTS`              | Comma-separated list of light entity IDs.                  |
| `HA_FALLBACK_AUTOMATION` | Optional. Automation entity ID to trigger on unmute when HA's snapshot looks bogus (see below). |
| `LOG_LEVEL`              | `DEBUG`, `INFO` (default), `WARNING`, `ERROR`.             |

The config file is `chmod 600` and listed in `.gitignore`. It never
enters the repository.

If `HA_URL` / `HA_TOKEN` / `HA_LIGHTS` are all empty, the daemon still
runs and tracks mute state — it simply skips the Home Assistant calls.

### The stale-snapshot fallback

Home Assistant's Hue integration sometimes reports a light's state as
`color_mode=xy, xy_color=[0.0, 0.0]`, which is not a real chromaticity
coordinate — it's the integration's "I don't actually know" sentinel.
If the daemon's pre-mute snapshot ends up in that state, the eventual
restore would push the bogus color back to the bulb (typically a deep
blue at low brightness, very visible in a dark office).

To work around this, set `HA_FALLBACK_AUTOMATION` to an automation that
puts your lights into a known-good state — e.g. one that activates a
work scene. When the daemon detects an invalid snapshot at unmute time,
it triggers that automation instead of running its per-light restore.
The automation is responsible for handling all the lights listed in
`HA_LIGHTS`; the daemon does not call per-light restore as well.

## How it works

The interesting part of this project is how you read the hardware mute
state at all. None of the obvious approaches work:

- `pactl get-source-mute alsa_input.usb-0b0e_Jabra_SPEAK_510_...` does
  not change when you press the button. The Speak 510 does not
  propagate its hardware mute to the host as a source-mute event.
- The HID input node `/dev/hidraw4` (the Speak 510's HID interface) is
  silent when you press the button. No `evdev` event either. The button
  is, in its default state, purely a device-local DSP toggle.

The trick — figured out by decompiling Jabra's official .NET SDK and
matching what it does against the Speak 510's HID report descriptor —
is that the device is, at the HID layer, a telephony endpoint. It
treats its buttons as call-control inputs, and it only forwards those
inputs to the host once the host has told it there is a call in
progress. The convention for "a call is in progress" is the HID OffHook
usage: when the host sets it, the device lights its in-call LEDs and
starts emitting Input reports for HookSwitch, Flash, PhoneMute, Redial,
etc.

So the daemon, on startup, writes:

```
03 01 00     # Report ID 3, byte 1 = 0b00000001 (OffHook), byte 2 = 0
```

to `/dev/hidraw4`. The device's call-state LEDs light up. The button
events now stream as Input reports of the form:

```
03 XX 00
```

where the bits of byte 1 are (from the report descriptor; usage page
`0x0b` Telephony):

| bit | usage         | type     |
|-----|---------------|----------|
| 0   | HookSwitch    | absolute |
| 1   | (vendor 0x97) | absolute |
| 2   | SpeakerPhone  | absolute |
| 3   | Line          | absolute |
| 4   | PhoneMute     | relative |
| 5   | Flash         | relative |
| 6   | Redial        | relative |
| 7   | SpeedDial     | relative |

"Relative" in the HID descriptor means the device emits a 1 only on the
edge — i.e. each press of the mute button gives us one `03 1X 00`
report followed by `03 0X 00`. We toggle our software state on the
rising edge of bit 4.

The same Report ID 3 has an Output side (HID usage page `0x08` LEDs):

| bit | usage      |
|-----|------------|
| 0   | OffHook    |
| 1   | Speaker    |
| 2   | Mute (LED) |
| 3   | Ring       |
| 4   | Hold       |
| 5   | MicMute    |
| 6   | Online     |

The daemon keeps OffHook (bit 0) high for its lifetime and writes the
MicMute bit (bit 5) to mirror its software state, so the device's red
mute indicator always tracks reality. On shutdown it writes `03 00 00`
to clear OffHook so the call-state LEDs go back to idle.

A few notes that surprised me along the way:

- "OffHook" is purely telephony jargon. Lifting an old phone handset
  off its cradle meant "I'm starting a call". On a fixed speakerphone
  like the Speak 510 it has no physical or audio meaning. Crucially, it
  does not gate the microphone: USB Audio Class endpoints are exposed
  by a separate USB interface and keep working regardless of HID state.
  Verified by recording before / during / after.
- The PhoneMute input the device emits is a notification of user
  intent, not the device's current mute state. There is no readable
  "current mute" register on the Speak 510. The host has to remember
  state itself and tell the device's LED what to display.
- This project does not include or redistribute any SDK code. All
  credit for the protocol design belongs to Jabra; all bugs in this
  implementation are mine.

You can verify all of this against your device by dumping its report
descriptor:

```sh
cat /sys/class/hidraw/hidraw<N>/device/report_descriptor | hexdump -C
```
