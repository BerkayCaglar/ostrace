# Research

The evidence the [architecture decisions](../adr/) rest on. These are records of
what was measured and found, kept separate from the decisions so the ADRs can
stay short and so the findings can be re-examined on their own terms.

| Document | Feeds | Evidence quality |
| --- | --- | --- |
| [log-sources-comparison.md](log-sources-comparison.md) | [ADR 0002](../adr/0002-use-pymobiledevice3-over-libimobiledevice-cli.md) | Measured on a physical device |
| [network-capture-feasibility.md](network-capture-feasibility.md) | [ADR 0006](../adr/0006-defer-wifi-capture.md) | Windows verified; macOS from documentation only |
| [gui-toolkit-evaluation.md](gui-toolkit-evaluation.md) | [ADR 0004](../adr/0004-pyside6-with-custom-filtered-model.md) | Upstream issues and published benchmarks |
| [claude-code-log-investigation.md](claude-code-log-investigation.md) | [ADR 0005](../adr/0005-agent-bundle-export-format.md) | Observed behaviour plus documented tool limits |

Each document states its own evidence quality at the top. Where something was
not verified on hardware, it says so — several conclusions here rest on
documentation because no Mac was available, and treating those as equal to a
measurement would be the mistake this whole directory exists to prevent.
