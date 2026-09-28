#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-or-later
#
# recovery.sh - the Recovery (1TR) stage of tools/probeos.sh. Copied into the
# probe kit on ProbeOS; run it from the Recovery Terminal:
#
#   sh "/Volumes/ProbeOS - Data/Users/Shared/probeos/recovery.sh" [install|undo|remove-policy UUID]
#
#   install (default)  set ONLY ProbeOS to Permissive Security and install the
#                      screen probe as its custom kernel
#   undo               restore Full Security for ProbeOS
#   remove-policy UUID remove the boot policy of a deleted ProbeOS
#
# Settings (payload, SHA-256, virtual address) come from probeos.env next to
# this script, written by `make hw-kit`. Every change asks for "yes" first, and
# everything is logged to recovery.log next to this script. Untested on hardware.

NAME="${PROBEOS_NAME:-ProbeOS}"
VOLUMES="${PROBEOS_VOLUMES_ROOT:-/Volumes}"
KIT="$(cd "$(dirname "$0")" && pwd)"
LOG="$KIT/recovery.log"

say()  { printf '%s\n' "$*" | tee -a "$LOG"; }
die()  { printf 'ERROR: %s\n' "$*" | tee -a "$LOG" >&2; exit 1; }

# Run and report the real exit status (tee would hide it in plain sh).
confirm_run_status() {
    say ""
    say "  \$ $*"
    printf 'Type "yes" to run this command: '
    read -r answer || answer=""
    [ "$answer" = "yes" ] || { say "Skipped."; return 2; }
    { "$@"; echo $? > "$KIT/.status"; } 2>&1 | tee -a "$LOG"
    code=$(cat "$KIT/.status" 2>/dev/null || echo 1)
    rm -f "$KIT/.status"
    return "$code"
}

sha256_of() {
    if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
    elif command -v openssl >/dev/null 2>&1; then openssl dgst -sha256 "$1" | awk '{print $NF}'
    else echo ""; fi
}

probe_volume() {
    vol="$VOLUMES/$NAME"
    [ -d "$vol" ] || die "$vol not found. Is $NAME's volume mounted? Try: diskutil mount \"$NAME\""
    name=$(diskutil info "$vol" 2>/dev/null | awk -F': *' '/^ *Volume Name:/ {print $2; exit}')
    [ "$name" = "$NAME" ] || die "$vol is named '$name', expected '$NAME'; refusing"
    group=$(diskutil info "$vol" 2>/dev/null | awk -F': *' '/^ *APFS Volume Group:/ {print $2; exit}')
    [ -n "$group" ] || die "could not read the volume group of $vol"
}

do_install() {
    [ -f "$KIT/probeos.env" ] || die "probeos.env missing next to this script"
    . "$KIT/probeos.env"
    payload="$KIT/$PROBE_PAYLOAD"
    [ -f "$payload" ] || die "$payload missing"
    probe_volume
    say "$NAME volume: $vol, volume group $group"

    actual=$(sha256_of "$payload")
    if [ -z "$actual" ]; then
        say "WARNING: no SHA-256 tool in this Recovery; checksum not verified."
    elif [ "$actual" != "$PROBE_SHA256" ]; then
        die "checksum mismatch: expected $PROBE_SHA256, got $actual"
    else
        say "Checksum OK: $actual"
    fi

    say ""
    say "Step 1 of 2: set ONLY $NAME to Permissive Security."
    say "Enter the $NAME administrator's name and password when asked."
    confirm_run_status bputil -n -v "$group" || die "bputil did not complete; nothing else was changed"

    say ""
    say "Step 2 of 2: install the screen probe as $NAME's custom kernel."
    if ! confirm_run_status kmutil configure-boot -c "$payload" --raw \
            --lowest-virtual-address "$PROBE_VA" --entry-point "$PROBE_VA" -v "$vol"; then
        say ""
        say "kmutil failed. Asahi's guide also enabled these options for its own tools:"
        say "kernel extensions, no kernel CTRR, custom boot arguments (still only $NAME)."
        say "Photograph the message above. You may retry with them, or stop here."
        confirm_run_status bputil -nkcas -v "$group" || die "stopped; photograph the output and report it"
        confirm_run_status kmutil configure-boot -c "$payload" --raw \
            --lowest-virtual-address "$PROBE_VA" --entry-point "$PROBE_VA" -v "$vol" ||
            die "kmutil failed again; photograph the output and report it"
    fi

    cat <<EOF | tee -a "$LOG"

Done. Next:
  1. Apple menu > Shut Down.
  2. Hold the power button until "Loading startup options...".
  3. Select $NAME, click Continue, and wait up to one minute.
  4. Photograph the screen (colour bars and text), then hold the power
     button about 10 seconds to turn off.
  5. Start again the same way and select Macintosh HD.
To undo later:  sh "$KIT/recovery.sh" undo
EOF
}

do_undo() {
    probe_volume
    say "Restore Full Security for $NAME (volume group $group) only."
    confirm_run_status bputil -f -v "$group" || die "not changed"
    say "Done. $NAME is back to Full Security and will no longer start the probe."
}

do_remove_policy() {
    [ -n "${1:-}" ] || die "usage: recovery.sh remove-policy <volume-group-UUID>"
    if [ -d "$VOLUMES/$NAME" ]; then die "$NAME still exists; delete it from macOS first (tools/probeos.sh remove)"; fi
    say "Remove the boot policy of the deleted $NAME (volume group $1)."
    confirm_run_status bputil -r "$1" || die "not removed"
    say "Done."
}

case "${1:-install}" in
    install) do_install ;;
    undo) do_undo ;;
    remove-policy) do_remove_policy "${2:-}" ;;
    *) say "usage: recovery.sh [install|undo|remove-policy UUID]"; exit 2 ;;
esac
