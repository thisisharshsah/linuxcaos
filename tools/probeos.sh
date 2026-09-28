#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-or-later
#
# probeos.sh - guided command-line setup and complete removal of "ProbeOS", the
# separate macOS installation that boots the screen probe on this Mac.
#
# Everything that changes the Mac shows the exact command and asks you to type
# "yes". --dry-run shows the commands without running them. The everyday macOS
# is never modified: every step refuses to act on the volume group you booted.
# See docs/FIRST_HARDWARE_RUN.md. None of this has been run on hardware yet.

set -u

NAME="${PROBEOS_NAME:-ProbeOS}"
VOLUMES="${PROBEOS_VOLUMES_ROOT:-/Volumes}"
PREBOOT="${PROBEOS_PREBOOT_ROOT:-/System/Volumes/Preboot}"
RECOVERY_VOL="${PROBEOS_RECOVERY_ROOT:-/Volumes/Recovery}"
RECORD="${PROBEOS_RECORD:-$HOME/ProbeOS-removal.txt}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KIT="${PROBEOS_KIT:-$ROOT/build/hw-kit}"
APPS="${PROBEOS_APPS_ROOT:-/Applications}"
MIN_FREE_GB_FOR_INSTALL=45   # installer (~18 GB) plus a new macOS (~25 GB)
DRY_RUN=0

say()  { printf '%s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# Show a command, ask for "yes", then run it (or only show it with --dry-run).
run() {
    say ""
    say "  \$ $*"
    if [ "$DRY_RUN" = 1 ]; then say "  (dry run: not executed)"; return 0; fi
    printf 'Type "yes" to run this command: '
    read -r answer || answer=""
    [ "$answer" = "yes" ] || { say "Skipped."; return 1; }
    "$@"
}

field() {  # field <diskutil-info-target> <label>: value of "label:" from diskutil info
    diskutil info "$1" 2>/dev/null | awk -F': *' -v k="$2" '$1 ~ "^ *" k "$" {print $2; exit}'
}

boot_group() { field / "APFS Volume Group"; }
boot_device() { field / "Device Identifier"; }
probe_group() { field "$NAME" "APFS Volume Group"; }
probe_exists() { diskutil info "$NAME" >/dev/null 2>&1; }

guard_not_boot() {  # guard_not_boot <group-uuid>
    local boot; boot="$(boot_group)"
    [ -n "$1" ] || die "could not read the volume group of $NAME"
    [ -n "$boot" ] || die "could not read the volume group of the running macOS"
    [ "$1" != "$boot" ] || die "$NAME belongs to the running macOS's volume group; refusing"
}

enter_recovery_help() {
    cat <<EOF

How to get into Recovery (1TR, "One True Recovery"):
  1. Apple menu > Shut Down. Wait until the screen is completely dark.
  2. Press and HOLD the power (Touch ID) button. Keep holding until
     "Loading startup options..." appears, then let go.
  3. Click "Options", then "Continue". Choose your user and enter your password
     (FileVault is on, so this unlocks the disk).
  4. In the menu bar choose Utilities > Terminal.
How to start a chosen system once: repeat steps 1-2, click the system (for
example $NAME or Macintosh HD), then "Continue".
EOF
}

cmd_help() {
    cat <<EOF
Usage: tools/probeos.sh [--dry-run] <step>

Run the steps in order (details: docs/FIRST_HARDWARE_RUN.md):
  status           Read-only checks: Mac, free space, FileVault, ProbeOS, kit
  create-volume    Add an empty APFS volume "$NAME" next to Macintosh HD
  download         Download the full installer for this macOS version
  install-macos    Install macOS onto $NAME (the Mac restarts), or show the
                   Recovery route if the installer cannot target $NAME
  copy-kit         Build the probe kit and copy it, with recovery.sh, to $NAME
  recovery-help    How to enter Recovery and the one command to run there

Removing everything, cleanly:
  remove           Delete $NAME's volumes and its leftover boot files, the
                   downloaded installer, and the local kit; write the final
                   Recovery command to $RECORD
  verify-removed   Check that nothing from $NAME remains

In Recovery, the kit's recovery.sh installs the probe ("install", default),
restores Full Security ("undo"), or removes the boot policy after deletion
("remove-policy <UUID>").
EOF
    enter_recovery_help
}

cmd_status() {
    say "Mac model:        $(sysctl -n hw.model 2>/dev/null) ($(uname -m))"
    say "macOS:            $(sw_vers -productVersion 2>/dev/null) ($(sw_vers -buildVersion 2>/dev/null))"
    local free_gb; free_gb=$(( $(df -k / | awk 'NR==2 {print $4}') / 1048576 ))
    say "Free space:       ${free_gb} GiB on the startup disk"
    say "FileVault:        $(fdesetup status 2>/dev/null | head -1)"
    say "Running system:   volume group $(boot_group)"
    if probe_exists; then
        say "$NAME:          present, volume group $(probe_group)"
    else
        say "$NAME:          not present"
    fi
    local app; app="$(installer_app)"
    say "Installer app:    ${app:-none}"
    if [ -f "$KIT/SHA256SUMS" ]; then say "Kit:              $(cat "$KIT/SHA256SUMS")"; else say "Kit:              not built (make hw-kit)"; fi
    [ -f "$RECORD" ] && say "Removal record:   $RECORD"
    return 0
}

cmd_create_volume() {
    probe_exists && { say "$NAME already exists; nothing to do."; return 0; }
    local container; container="$(field / "APFS Container")"
    [ -n "$container" ] || die "could not find the APFS container of the startup disk"
    say "This adds an empty APFS volume named $NAME to container $container."
    say "It shares free space with Macintosh HD; nothing is resized or erased."
    run diskutil apfs addVolume "$container" APFS "$NAME"
}

installer_app() {
    local app
    for app in "$APPS"/Install\ macOS*.app; do
        [ -d "$app" ] && { printf '%s\n' "$app"; return 0; }
    done
    return 0
}

cmd_download() {
    local version free_gb; version="$(sw_vers -productVersion)"
    free_gb=$(( $(df -k / | awk 'NR==2 {print $4}') / 1048576 ))
    [ "$free_gb" -ge "$MIN_FREE_GB_FOR_INSTALL" ] ||
        die "only ${free_gb} GiB free; need at least ${MIN_FREE_GB_FOR_INSTALL} GiB for the installer and a new macOS"
    [ -n "$(installer_app)" ] && { say "Installer already present: $(installer_app)"; return 0; }
    say "Downloads the full macOS $version installer from Apple (about 18 GB) into $APPS."
    run softwareupdate --fetch-full-installer --full-installer-version "$version"
}

cmd_install_macos() {
    probe_exists || die "$NAME does not exist; run create-volume first"
    guard_not_boot "$(probe_group)"
    local app; app="$(installer_app)"
    [ -n "$app" ] || die "no installer found; run download first"
    local tool="$app/Contents/Resources/startosinstall"
    if [ -x "$tool" ] && "$tool" --usage 2>&1 | grep -q -- "--volume"; then
        say "Installs macOS onto $NAME. The Mac restarts to finish; this takes a while."
        say "Afterwards, in $NAME's setup: create an administrator (for example 'probe'),"
        say "skip the Apple Account, and leave FileVault OFF for $NAME."
        say "You will be asked for YOUR password (an administrator of this Mac)."
        run sudo "$tool" --agreetolicense --volume "$VOLUMES/$NAME" --user "$(id -un)" --passprompt
    else
        warn "this installer cannot target a volume from the command line; use Recovery instead"
        enter_recovery_help
        say "Then choose 'Reinstall macOS', and pick $NAME as the disk (NOT Macintosh HD)."
    fi
}

cmd_copy_kit() {
    probe_exists || die "$NAME does not exist"
    guard_not_boot "$(probe_group)"
    local data="$VOLUMES/$NAME - Data"
    if [ ! -d "$data" ]; then
        run diskutil mount "$NAME - Data" || die "could not mount $NAME - Data"
    fi
    [ "$DRY_RUN" = 1 ] || (cd "$ROOT" && make -s hw-kit) || die "make hw-kit failed"
    local dest="$data/Users/Shared/probeos"
    say "Copies the kit (probe, checksum, settings, recovery.sh) to $dest."
    run mkdir -p "$dest" && run cp -R "$KIT/." "$dest/" || return 1
    [ "$DRY_RUN" = 1 ] && return 0
    (cd "$dest" && shasum -a 256 -c SHA256SUMS) || die "checksum mismatch after copying"
    cmd_recovery_help
}

cmd_recovery_help() {
    enter_recovery_help
    cat <<EOF

Then run this one command in the Recovery Terminal:

  sh "/Volumes/$NAME - Data/Users/Shared/probeos/recovery.sh"

It finds $NAME, checks the probe's checksum, sets ONLY $NAME to Permissive
Security, and installs the probe as $NAME's custom kernel. It asks before each
change. If "/Volumes/$NAME - Data" is missing there, first run:
  diskutil mount "$NAME - Data"
EOF
}

cmd_remove() {
    say "Complete removal of $NAME. Your files on Macintosh HD are not touched."
    local group=""
    if probe_exists && [ -z "$(probe_group)" ]; then
        # A bare volume: created, but macOS was never installed on it.
        local dev name; dev="$(field "$NAME" "Device Identifier")"; name="$(field "$NAME" "Volume Name")"
        [ -n "$dev" ] && [ "$name" = "$NAME" ] || die "could not identify the $NAME volume"
        case "$(boot_device)" in "$dev"|"$dev"s*) die "$dev is the running system; refusing" ;; esac
        say ""
        say "1. Delete the empty $NAME volume ($dev). macOS was never installed on it."
        run diskutil apfs deleteVolume "$dev" || die "not deleted; stopping"
    elif probe_exists; then
        group="$(probe_group)"
        guard_not_boot "$group"
        say ""
        say "1. Delete $NAME and $NAME - Data (volume group $group), and everything in them."
        say "   diskutil also removes their XART, Preboot, and Recovery entries."
        run diskutil apfs deleteVolumeGroup "$group" || die "not deleted; stopping"
    else
        say "1. $NAME volumes are already gone."
        [ -f "$RECORD" ] && group="$(awk -F': ' '/^Volume group:/ {print $2}' "$RECORD")"
    fi
    if [ -n "$group" ]; then
        local boot; boot="$(boot_group)"
        local dir
        for dir in "$PREBOOT/$group" "$RECOVERY_VOL/$group"; do
            # deleteVolumeGroup also removes XART, Preboot, and Recovery entries
            # (diskutil's own help); this only catches anything left behind.
            if [ -e "$dir" ] && [ "$group" != "$boot" ]; then
                say ""
                say "2. Remove $NAME's leftover boot files: $dir"
                run sudo rm -rf "$dir"
            fi
        done
    fi
    local app; app="$(installer_app)"
    if [ -n "$app" ]; then
        say ""
        say "3. Remove the downloaded installer (about 18 GB): $app"
        run sudo rm -rf "$app"
    fi
    if [ -d "$KIT" ]; then
        say ""
        say "4. Remove the local probe kit: $KIT"
        run rm -rf "$KIT"
    fi
    if [ -n "$group" ] && [ "$DRY_RUN" = 0 ]; then
        cat > "$RECORD" <<EOF
ProbeOS removal record ($(date))
Volume group: $group

Last step, in Recovery (only Recovery can remove a boot policy):
  bputil -r $group
Then open System Settings > General > Startup Disk and make sure
Macintosh HD is selected. Delete this file when done.
EOF
    fi
    if [ -n "$group" ]; then
        say ""
        say "5. Last step, in Recovery: remove $NAME's boot policy."
        say "   Command:  bputil -r $group"
        say "   (saved in $RECORD)"
        enter_recovery_help
        say ""
        say "Finally check System Settings > General > Startup Disk shows Macintosh HD,"
        say "and run: tools/probeos.sh verify-removed"
    else
        say ""
        say "No macOS was installed on $NAME, so it has no boot policy and nothing is"
        say "needed in Recovery. Check with: tools/probeos.sh verify-removed"
    fi
}

cmd_verify_removed() {
    local ok=1 group=""
    [ -f "$RECORD" ] && group="$(awk -F': ' '/^Volume group:/ {print $2}' "$RECORD")"
    if probe_exists; then say "NOT CLEAN: volume $NAME still exists"; ok=0; else say "ok: no $NAME volume"; fi
    if [ -n "$group" ]; then
        if diskutil apfs listVolumeGroups 2>/dev/null | grep -q "$group"; then
            say "NOT CLEAN: volume group $group still exists"; ok=0
        else
            say "ok: volume group $group is gone"
        fi
        local dir
        for dir in "$PREBOOT/$group" "$RECOVERY_VOL/$group"; do
            if [ -e "$dir" ]; then say "NOT CLEAN: $dir remains"; ok=0; else say "ok: no $dir"; fi
        done
        say "check in Recovery: 'bputil -e' should no longer list $group"
    fi
    if [ -n "$(installer_app)" ]; then say "NOT CLEAN: $(installer_app) remains"; ok=0; else say "ok: no macOS installer app"; fi
    if [ -d "$KIT" ]; then say "NOT CLEAN: $KIT remains"; ok=0; else say "ok: no local kit"; fi
    [ "$ok" = 1 ] && say "Clean on the macOS side." || say "Some items remain (see above)."
    [ "$ok" = 1 ]
}

main() {
    [ "${1:-}" = "--dry-run" ] && { DRY_RUN=1; shift; }
    case "${1:-help}" in
        help|-h|--help) cmd_help ;;
        status) cmd_status ;;
        create-volume) cmd_create_volume ;;
        download) cmd_download ;;
        install-macos) cmd_install_macos ;;
        copy-kit) cmd_copy_kit ;;
        recovery-help) cmd_recovery_help ;;
        remove) cmd_remove ;;
        verify-removed) cmd_verify_removed ;;
        *) cmd_help; exit 2 ;;
    esac
}

main "$@"
