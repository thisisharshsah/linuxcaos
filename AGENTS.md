# Project documentation

The user requested a living, side-by-side blueprint that stays updated as the
project changes. Read `docs/BLUEPRINT.md` before planning implementation work.

For each meaningful implementation change, update the affected blueprint
architecture/status rows, evidence, next steps, revision/date, and append its
history entry in the same change. Update `docs/ROADMAP.md` when milestone scope
changes and `docs/RESEARCH.md` for new hardware observations or sourced findings.

Distinguish source written, build passed, Unicorn instruction tests, QEMU
device-model tests, and physical-M1 validation. Never promote emulator results
to hardware compatibility or describe planned components as implemented.

Keep the project boundary explicit: original boot/platform-support code, with
the existing Linux kernel as the intended OS core. No Apple boot interface has
been validated yet. Documentation maintenance does not require rerunning runtime
tests for documentation-only edits; inspect existing evidence and check links.
