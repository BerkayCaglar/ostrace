---
status: accepted
date: 2026-08-08
decision-makers: Berkay ÇAĞLAR
---

# Defer network (Wi-Fi) capture to a later release

## Context and Problem Statement

Apple devices can be reached over the network as well as over USB. On macOS,
"Connect via network" in Xcode's Devices window makes a paired device visible to
`usbmuxd` over the local network, and `pymobiledevice3` exposes those devices
with `connection_type == "Network"` exactly as it does USB ones.

On Windows the situation is different. The usbmux implementation is Apple Mobile
Device Service, listening on TCP `127.0.0.1:27015`, and enabling network
discovery is not exposed the way it is on macOS. Making it work would mean
either driving the pairing and mDNS discovery directly or depending on
behaviour that Apple does not document and can change.

Meanwhile the device under test is attached over USB, and USB capture is the
case that has actually been measured.

## Decision Drivers

- v1 must ship. Every feature that is not required for a first useful release is
  competing with the ones that are.
- The Windows path is the one that would need real research, and it is the
  platform with the fewest network-capture users.
- Whatever is decided must not have to be undone later.

## Considered Options

1. **Defer network capture entirely.**
2. **Support it on macOS only**, where it is nearly free.
3. **Implement it on both**, researching the Windows path now.

## Decision Outcome

Chosen option: **defer network capture entirely for v1**, with the abstraction
built so that adding it later is additive.

Concretely, the deferral is a scope decision and not an architectural one:

- Device discovery already surfaces `connection_type`, so a network device is
  representable today; it is simply not selected.
- `LogSource` is a protocol over `Record` objects. A network-attached device
  produces the same records over the same lockdown service — the transport
  differs, nothing downstream does.
- Nothing in the record model, the storage format or the exporters encodes an
  assumption that the device is attached over USB.

### Consequences

- Good: v1 stays scoped to what has been measured on a real device.
- Good: the Windows research — mDNS discovery, pairing records, whatever AMDS
  does and does not expose — is not on the critical path.
- Bad: users who want to capture logs while the device is untethered cannot,
  which for a log viewer is a genuine limitation (capturing during a walk, or
  while the device is in a case, or under load that USB power affects).
- Neutral: because the constraint is scope rather than architecture, this ADR is
  expected to be superseded rather than to stand indefinitely.

### Confirmation

The discovery layer lists network devices and reports them as unsupported with
a clear message, rather than pretending they do not exist. If that message ever
has to become "not supported on this platform" instead of "not supported yet",
that is the signal that this decision needs revisiting rather than extending.

## More Information

- [docs/research/network-capture-feasibility.md](../research/network-capture-feasibility.md)
- Requested explicitly during planning: "windows wifi bağlantısına gerek yok
  şimdilik" — Windows Wi-Fi is not needed for now.
