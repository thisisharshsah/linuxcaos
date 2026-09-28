# First hardware run: the screen probe

A step-by-step checklist for running the [screen probe](SCREEN_PROBE.md) on this
MacBookPro17,1 and reporting back. It is written for the owner to follow by hand;
the steps need a person at the keyboard, the power button, and a phone camera.
**This procedure has not been tried yet.** Where it relies on an untested
assumption, it says so and gives a fallback.

## What stays safe

- Your everyday macOS ("Macintosh HD") keeps **Full Security**. Only a second,
  separate macOS installation ("ProbeOS") gets a lowered security policy.
- The probe writes only RAM and the screen. It never writes flash storage, NVRAM,
  or firmware, so turning the Mac off erases everything it did.
- Asahi Linux's documentation describes M1 Macs as effectively unbrickable as long
  as flash is not written, provided Recovery (1TR) on the internal disk still works.
- Everything below can be undone (see [Undo](#undo)).

## Before you start

| Check | Why | This Mac on 2026-09-27 |
| --- | --- | --- |
| A current backup (Time Machine or copies of important files) | Disk changes always carry some risk | Unknown |
| **At least 70 GB free** on Macintosh HD | A second macOS needs roughly 25–35 GB, and your everyday macOS needs room left over | **About 46 GB free: free up about 25 GB more first** |
| Charger connected, about 2 hours, internet access | The macOS download is large | — |
| Your login password | FileVault is on, so Recovery asks for it | FileVault on |
| A phone camera | The photo is the evidence | — |

Write down each password you create. You will need the ProbeOS administrator
password in Recovery.

## Step 1: Create the ProbeOS volume (in your everyday macOS)

Open **Disk Utility**, select the **Macintosh HD** container (View → Show All
Devices helps), click **+** (Add APFS Volume), name it `ProbeOS`, format APFS,
and click Add. This adds a volume that shares the existing free space; nothing
is resized or erased.

> Untested assumption: Asahi's guide used a separate partition instead of a
> volume in the same container. Apple supports installing macOS on another APFS
> volume, and each installation has its own boot policy, so a volume should work.
> If `kmutil` in step 4 refuses it, tell me and we will switch to a partition.

## Step 2: Install macOS onto ProbeOS

1. Shut down. Press and **hold** the power button until "Loading startup
   options…" appears. Choose **Options**, then Continue, and enter your password.
2. Choose **Reinstall macOS**. When asked for a disk, pick **ProbeOS**. **Do not
   pick Macintosh HD.**
3. When it restarts into the new macOS setup: create a local administrator
   account (for example `probe`), skip the Apple Account, and **leave FileVault
   off** for this installation.

## Step 3: Copy the probe onto ProbeOS (back in your everyday macOS)

Restart holding the power button, pick **Macintosh HD**. Then in Terminal:

```sh
cd ~/Desktop/linux
make hw-kit
cp build/hw-kit/screen-probe.bin "/Volumes/ProbeOS - Data/Users/Shared/"
shasum -a 256 "/Volumes/ProbeOS - Data/Users/Shared/screen-probe.bin"
cat build/hw-kit/SHA256SUMS
```

The two checksums must match. If `/Volumes/ProbeOS - Data` does not exist, open
Disk Utility and mount "ProbeOS - Data" first. Keep `build/hw-kit` open: it holds
the exact `kmutil` command (BUILD-INFO.txt) and the report template.

## Step 4: Allow ProbeOS to boot the probe (in Recovery)

1. Shut down. Hold the power button until "Loading startup options…", choose
   **Options**, and unlock with your password.
2. Open **Utilities → Terminal**.
3. Find ProbeOS's volume group UUID:

   ```sh
   diskutil apfs listVolumeGroups
   ```

   Note the UUID of the group that contains ProbeOS (not Macintosh HD).
4. Check the file is there and unchanged:

   ```sh
   ls "/Volumes/ProbeOS - Data/Users/Shared/"
   shasum -a 256 "/Volumes/ProbeOS - Data/Users/Shared/screen-probe.bin"
   ```

   If the folder is missing, run `diskutil mount "ProbeOS - Data"`.
5. Lower **only ProbeOS** to Permissive Security (it asks for the ProbeOS
   administrator's name and password):

   ```sh
   bputil -n -v <ProbeOS-UUID>
   ```

6. Install the probe as ProbeOS's custom kernel. This is the command from
   BUILD-INFO.txt with the volume name filled in:

   ```sh
   kmutil configure-boot -c "/Volumes/ProbeOS - Data/Users/Shared/screen-probe.bin" --raw --lowest-virtual-address 0xfffffe0007004000 --entry-point 0xfffffe0007004000 -v "/Volumes/ProbeOS"
   ```

   **Photograph the output.** If it reports a security-policy problem, Asahi's
   guide used more options; run `bputil -nkcas -v <ProbeOS-UUID>` and try again.
   The address is XNU's own kernel link address, a reasoned guess: if `kmutil`
   rejects it, photograph the message and stop there.
7. Shut down (Apple menu → Shut Down).

## Step 5: Run the probe

1. Hold the power button until "Loading startup options…". Select **ProbeOS**
   and click Continue.
2. Wait up to one minute. Expected: four colour bars across the top (red, green,
   blue, white from left to right) and a white text report on black.
3. **Photograph the whole screen**, then close-ups of the text. Note the colour
   of each bar as you see it.
4. Hold the power button about 10 seconds until the Mac turns off.

A black screen, a frozen Apple logo, or a restart are also results. Photograph
them and note how long you waited. Any of them teaches us something.

## Step 6: Return to your everyday macOS

Hold the power button until "Loading startup options…", select **Macintosh HD**,
and click Continue. If the Mac tries to start ProbeOS by default afterwards, open
System Settings → General → Startup Disk and choose Macintosh HD.

## Step 7: Report back

Fill in `build/hw-kit/REPORT-TEMPLATE.md` (or just tell me the answers), and
share the photos. I will record the result in [RESEARCH.md](RESEARCH.md) and the
[blueprint](BLUEPRINT.md), including what it proves and what it does not.

## Undo

- **Restore ProbeOS to Full Security:** in Recovery Terminal,
  `bputil -f -v <ProbeOS-UUID>`.
- **Remove everything:** in your everyday macOS, open Disk Utility and delete the
  ProbeOS volumes (ProbeOS and ProbeOS - Data). Then in Recovery Terminal,
  `bputil -r <ProbeOS-UUID>` removes its leftover boot policy.
- Your everyday macOS's policy is never changed by this procedure, so it needs no
  undo.

## Sources

`kmutil` and `bputil` options are from their local help on this Mac (macOS 27.0,
26A428). The installation route and fallback options follow Asahi Linux's public
developer quickstart; the virtual address is XNU's `ARM64_LINK_ADDR`. Details
and pinned versions are in [RESEARCH.md](RESEARCH.md) and
[APPLE_BOOT.md](APPLE_BOOT.md).
