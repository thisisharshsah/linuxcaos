# First hardware run: the screen probe

A step-by-step guide for running the [screen probe](SCREEN_PROBE.md) on this
MacBookPro17,1, reporting back, and removing everything afterwards. A guided
command-line tool, `tools/probeos.sh`, does most steps; a few need a person at
the power button and a phone camera. **This procedure has not been tried yet.**
Where it relies on an untested assumption, it says so and gives a fallback.

## What stays safe

- Your everyday macOS ("Macintosh HD") keeps **Full Security** and is never
  modified. Only a second, separate macOS installation ("ProbeOS") gets a lowered
  security policy. The tools refuse to act on the system you booted.
- The probe writes only RAM and the screen. It never writes flash, NVRAM, or
  firmware, so turning the Mac off erases everything it did.
- Every step that changes something shows the exact command and waits for you to
  type `yes`. Add `--dry-run` to see the commands without running them.
- Asahi Linux's documentation describes M1 Macs as effectively unbrickable as long
  as flash is not written, provided Recovery (1TR) on the internal disk still works.
- [Complete removal](#complete-removal) returns the Mac to how it was.

## Before you start

| Check | Why | This Mac on 2026-09-27 |
| --- | --- | --- |
| A backup of your files, passwords, and FileVault recovery key | Some risk comes with any disk change | Done (owner) |
| At least 70 GB free | Installer (about 18 GB) plus a second macOS | 75.5 GB free |
| Charger, about 2 hours, internet | The macOS download is large | — |
| A phone camera | The photo is the evidence | — |

Write down the ProbeOS administrator password you create in step 4; Recovery asks
for it.

## Where things are

- **Startup options** (choose which system starts): Apple menu › Shut Down, wait
  until the screen is dark, then press and **hold** the power button until
  "Loading startup options…" appears. Select a system and click Continue.
- **Recovery (1TR)**: open the startup options as above, click **Options**, then
  Continue, choose your user, and enter your password. Recovery Terminal is in the
  menu bar under **Utilities › Terminal**.
- **Default startup disk**: System Settings › General › Startup Disk.
- **The tool**: in Terminal on your everyday macOS, `cd ~/Desktop/linux`.
  `tools/probeos.sh help` lists every step; `tools/probeos.sh recovery-help`
  prints the Recovery instructions again.

## Quick path

Run these on your everyday macOS unless a step says otherwise.

1. **Check.** `tools/probeos.sh status` (read-only).
2. **Create ProbeOS.** `tools/probeos.sh create-volume` adds an empty APFS volume
   next to Macintosh HD. Nothing is resized or erased.
   > Untested assumption: Asahi's guide used a separate partition. Apple supports
   > macOS on another APFS volume with its own boot policy, so a volume should
   > work. If `kmutil` refuses it in step 6, report it and we switch to a partition.
3. **Download macOS.** `tools/probeos.sh download` fetches the full installer for
   your current macOS version from Apple (about 18 GB).
4. **Install macOS onto ProbeOS.** `tools/probeos.sh install-macos`. It asks for
   your password, then the Mac restarts and installs. In ProbeOS's setup: create
   an administrator (for example `probe`), skip the Apple Account, and **leave
   FileVault off** for ProbeOS. If the installer cannot target a volume, the tool
   prints the Recovery route instead: Recovery › Reinstall macOS › choose
   **ProbeOS** (never Macintosh HD).
5. **Copy the probe.** Restart into Macintosh HD using the startup options, then
   `tools/probeos.sh copy-kit`. It builds the kit, copies it to ProbeOS, checks the
   SHA-256, and prints the Recovery instructions.
6. **Install the probe (Recovery).** Enter Recovery, open Terminal, and run:

   ```sh
   sh "/Volumes/ProbeOS - Data/Users/Shared/probeos/recovery.sh"
   ```

   It finds ProbeOS, verifies the checksum, then asks before each change:
   `bputil -n -v <ProbeOS UUID>` (Permissive Security for ProbeOS only; enter the
   ProbeOS administrator's name and password) and the `kmutil configure-boot
   --raw` command. **Photograph its output.** If `kmutil` fails, it explains and
   offers Asahi's wider `bputil -nkcas` settings, still only for ProbeOS.
   Everything is logged to `recovery.log` in the same folder.
7. **Run the probe.** Shut down, open the startup options, select **ProbeOS**,
   and wait up to one minute. Expected: four bars across the top (red, green,
   blue, white from left to right) and a white text report on black.
   **Photograph the whole screen**, then close-ups. Hold the power button about 10
   seconds to turn off.
8. **Return.** Open the startup options and select **Macintosh HD**. If the Mac
   later starts ProbeOS by default, choose Macintosh HD under Startup Disk.

A black screen, a frozen Apple logo, or a restart are also results: photograph
them and note how long you waited. After step 4 you may delete the installer app
to recover about 18 GB; `remove` also deletes it.

## Report back

Fill in `build/hw-kit/REPORT-TEMPLATE.md` (or just tell me the answers) and share
the photos, including the Recovery output from step 6. The result goes into
[RESEARCH.md](RESEARCH.md) and the [blueprint](BLUEPRINT.md) with exactly what it
does and does not prove.

## Complete removal

This deletes ProbeOS and everything the procedure added, leaving the Mac as it
was. Your files on Macintosh HD are not touched.

1. Start **Macintosh HD** and run `tools/probeos.sh remove`. It asks before each
   part and:
   - deletes the ProbeOS volume group (ProbeOS and ProbeOS - Data) with
     `diskutil apfs deleteVolumeGroup`, which also removes their XART, Preboot, and
     Recovery entries (diskutil's own help);
   - removes any ProbeOS folder still left in Preboot or Recovery;
   - deletes the downloaded macOS installer and the local kit (`build/hw-kit`);
   - saves the final Recovery command to `~/ProbeOS-removal.txt`.
2. **Remove the boot policy (Recovery).** Only Recovery can do this. Enter
   Recovery, open Terminal, and run the command from `~/ProbeOS-removal.txt`:

   ```sh
   bputil -r <ProbeOS UUID>
   ```

   Check with `bputil -e`: only Macintosh HD should be listed.
3. Start Macintosh HD, confirm **Startup Disk** shows Macintosh HD, and run
   `tools/probeos.sh verify-removed`. It should print "Clean on the macOS side."
   Then delete `~/ProbeOS-removal.txt`.

To keep ProbeOS but stop it starting the probe, run `recovery.sh undo` in Recovery
instead: it restores Full Security for ProbeOS (`bputil -f -v <UUID>`).

## Sources

`kmutil`, `bputil`, and `diskutil` behaviour is from their local help on this Mac
(macOS 27.0, 26A428). The installation route and fallback options follow Asahi
Linux's public developer quickstart; the virtual address is XNU's
`ARM64_LINK_ADDR`. Details and pinned versions are in [RESEARCH.md](RESEARCH.md)
and [APPLE_BOOT.md](APPLE_BOOT.md). The tools are tested with fake system
commands (`tests/test_probeos.py`); they have not yet run against the real ones.
