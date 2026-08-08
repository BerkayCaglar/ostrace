# Test fixtures

Real captures from a physical device, committed so that the whole pipeline is
testable with nothing attached. `ostrace.sources.replay` reads them and the rest
of the code cannot tell them apart from a live device.

Empty until phase 1, when the record model and the sources exist to produce
them.

**Fixtures are captured, never written by hand.** A previous iteration of this
tool matched 0% of real device output for weeks because its tests used invented
log lines containing a syslog hostname field that real output does not have. The
tests passed the entire time.

Redact before committing: a capture contains whatever the device was logging.
