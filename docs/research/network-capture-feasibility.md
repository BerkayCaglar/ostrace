# Capturing over the network instead of USB

**Date:** 2026-08-08
**Feeds:** [ADR 0006](../adr/0006-defer-wifi-capture.md)
**Status of the evidence:** macOS behaviour is from documentation and from
`pymobiledevice3`'s own API surface, not from a machine. No Mac was available.
Windows behaviour was checked against a live Apple Mobile Device Service
installation.

---

## The mechanism

There is nothing log-specific about network capture. `os_trace_relay` is a
lockdown service, and lockdown sessions can be established over TCP to a paired
device as readily as over USB. The question is entirely about **discovery and
pairing**, not about the log stream.

The path a network device takes:

1. The device and host are paired over USB once.
2. The host's usbmux implementation is told to also look for the device over the
   network.
3. The device advertises itself over mDNS (`_apple-mobdev2._tcp`).
4. usbmux resolves it and presents it as a device with
   `connection_type == "Network"`.

`pymobiledevice3` already exposes step 4. `list_devices()` returns objects with
`is_usb` and `is_network` flags, and `create_using_usbmux()` accepts network
devices. From the library's point of view, the transport is already abstracted.

## macOS: essentially free

On macOS, step 2 is a checkbox. Xcode's Devices and Simulators window has
**"Connect via network"**; ticking it, with the device attached over USB once,
makes it visible to `usbmuxd` over the local network afterwards. `usbmuxd` on
macOS is Apple's own, part of the OS, and handles the mDNS side itself.

There is a caveat worth recording: network-attached devices are noticeably
slower and less reliable than USB for sustained streaming, and the connection
drops when the device sleeps or moves between access points. For a log stream
running for an hour that is a real reliability concern, not a theoretical one —
which is an argument for building reconnect handling well before building
network support.

## Windows: not comparably available

On Windows the usbmux implementation is **Apple Mobile Device Service**, part of
the Apple Mobile Device Support package, listening on TCP `127.0.0.1:27015`.
Confirmed present and listening on the test machine.

What could not be found is any supported way to enable network discovery through
it. Specifically:

- There is no Windows equivalent of Xcode's "Connect via network" checkbox.
  iTunes' Wi-Fi sync is a separate mechanism operating at the iTunes application
  layer, not something that makes the device appear in the usbmux device list.
- AMDS exposes no documented interface for adding a network device to its list.
- The plausible workarounds all involve bypassing AMDS rather than using it:
  implementing mDNS discovery directly, reading the pair record and opening a
  lockdown TCP session to the device without going through usbmux at all.

That last option is technically feasible — `pymobiledevice3` has the pieces —
but it means depending on undocumented behaviour and on pair record locations
that Apple can change. It also means the Windows path would work differently
from the macOS path, which doubles the surface that has to be maintained and
tested, on the platform where network capture is least likely to be wanted.

One hard constraint found along the way: **pair records must never be read from
disk directly.** On macOS `/var/db/lockdown` is root-only and TCC-protected;
reading it would require elevation for something that does not otherwise need
it. `pymobiledevice3` asks `usbmuxd` for the pair record over its socket
instead, which requires no privileges at all. Any future network implementation
has to go through that path.

## Conclusion

Network capture is close to free on macOS and expensive-and-fragile on Windows.
Shipping it on macOS only would mean a feature that exists on one platform and
cannot be tested by the maintainer on that platform — the worst of both.

Deferred for v1. The abstraction cost of leaving room is zero: `connection_type`
is already surfaced by discovery, and `LogSource` is a protocol over `Record`
objects that says nothing about transport. When this is picked up, the work is
in `devices/discovery.py` and nowhere else.

## What a future implementation would need to establish

- Whether AMDS on current Windows builds can be induced to enumerate network
  devices at all, or whether mDNS discovery has to be implemented directly.
- How reliably a network lockdown session survives an hour of streaming, on both
  platforms, including device sleep.
- Whether reconnect-after-gap (already required for USB) is sufficient, or
  whether network capture needs a different strategy for a longer interruption.
