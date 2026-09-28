# Reuse Fedora's packages, own the image and boot

**Research date:** 2026-09-27. **Evidence level: desk research only.** Everything below comes from other projects' public documentation, release notes, dashboards and issue trackers. **None of it has been built, run or validated on the owner's MacBookPro17,1, in QEMU, or in Unicorn.** The project has not yet booted Linux on the M1 (roadmap M3), so every recommendation here is a design proposal for milestone M5, not a statement of compatibility. Throughout the report, sentences that begin with or sit under **Interpretation** are this report's reasoning. Everything else is a sourced fact, cited inline.

Existing Linux systems split into three layers: a **package base** that builds and signs software (APT, DNF5, pacman, Nix and others), an **OS delivery model** that decides how the installed system changes and rolls back (mutable packages, Btrfs snapshots, ostree/bootc images, or A/B partitions), and an **app layer** for desktop software (Flatpak/Flathub, Snap, AppImage). The products that feel most premium, such as ChromeOS, SteamOS, Endless OS and Fedora Atomic, all ship a read-only OS image that updates atomically and keep apps in a separate sandboxed channel. Users never see package management. For this project, the recommended stack is: **reuse Fedora's aarch64 RPM/DNF5 package ecosystem unmodified**; **own a small overlay** (a 16K-page mainline kernel package, the project's boot stage, firmware-extraction tooling and platform defaults); **ship the OS as one signed, CI-built bootc/OCI image**; **deliver desktop apps through Flathub** in GNOME Software or KDE Discover; and **build a first-boot setup and a macOS-side installer and recovery tool** that extend the project's existing `probeos.sh`. Fedora is the pragmatic base. The Apple Silicon reference distribution already runs Fedora's DNF5/RPM 6.0 stack on M1-class Macs. Fedora packages the x86-emulation stack those Macs need. A small team (Universal Blue) has shown that Fedora-based signed images can be built with free CI. One risk dominates. **Every surveyed rollback scheme protects only the layers above the bootloader.** On a Mac, the Apple-specific boot stage (which this project writes itself) sits below all of them, so the project must design and test its own fallback path for that stage.

## Recommendation at a glance, and what a small team can actually build

The table below states the recommendation per layer, what the project would own and what it would reuse. The *Basis* column separates sourced precedent from interpretation.

| Layer | Recommendation | Project owns | Project reuses | Basis |
|---|---|---|---|---|
| Package base | Fedora aarch64 repositories with RPM 6.0 / DNF5 | An overlay repository: kernel package (mainline + project config, 16K pages), boot-stage package, firmware tooling, defaults/branding | All other Fedora packages, signing (rpm-sequoia), Mesa, FEX/muvm | Fedora Asahi Remix precedent on M1-class Macs ([Fedora Magazine](https://fedoramagazine.org/fedora-asahi-remix-43-is-now-available/)). Choosing Fedora over Debian is interpretation |
| OS delivery | Immutable image built as a bootc Containerfile in CI, signed, deployed as ostree deployments | Containerfile, CI, signing keys, update channels | bootc, ostree, image-builder | Universal Blue pattern ([universal-blue.org](https://universal-blue.org/)). bootc with a non-UEFI custom loader is **unverified** |
| Rollback | Boot counting plus health checks above the kernel, and a separately versioned copy of the project's boot stage below it | Loader-side slot/entry selection, tries counter, "last known good" policy | systemd boot-assessment conventions, greenboot/health-checker ideas | ([systemd.io](https://systemd.io/AUTOMATIC_BOOT_ASSESSMENT/)), ([health-checker](https://github.com/openSUSE/health-checker/blob/master/README.md)). The design is interpretation |
| Apps | Flathub (optionally the verified subset) in GNOME Software or KDE Discover, with automatic updates | Curated defaults and a known-broken-on-16K list | Flatpak, Flathub, AppStream, ODRS | ([Flathub docs](https://docs.flathub.org/docs/for-users/verification)) |
| x86 apps | Fedora's `@x86-emulation` (FEX in a 4K-page muvm microVM) | Integration and testing only | fex-emu, muvm, binfmt-dispatcher | ([Fedora Changes/FEX](https://fedoraproject.org/wiki/Changes/FEX)) |
| Installer | Guided macOS-side installer (the existing `probeos.sh` lineage) that creates the per-OS partitions, extracts firmware and writes a prebuilt image; personalisation happens at first boot | Installer, image format, first-boot setup, uninstaller | Plasma Setup or GNOME Initial Setup for first boot | The Asahi installer pattern is documented ([asahi-installer](https://github.com/AsahiLinux/asahi-installer)), but its code must not be copied |
| Recovery | "Boot macOS → repair the Linux ESP/stub" tool plus documented recoveryOS/DFU steps | The repair tool and its tests | Apple boot picker, macOS `diskutil`, recoveryOS | ([Asahi Boot Process guide](https://asahilinux.org/docs/alt/boot-process-guide/)), ([Partitioning cheatsheet](https://asahilinux.org/docs/sw/partitioning-cheatsheet/)) |

**Interpretation, phased path.** The phases are gated by evidence, not by calendar dates, which matches the roadmap's rule that M5 starts "only after reliable boot and storage".

| Phase | Entry gate | Deliverable | Proof required |
|---|---|---|---|
| 0: Reproducible kernel (during M3/M4) | None | Pinned, reproducible build of a mainline 16K-page kernel and initramfs, packaged as an RPM in a signed overlay repo | Bit-identical rebuild in CI. Kernel boots to an initramfs shell **on the physical M1** (the M3 exit criterion) |
| 1: Developer image | M3 exit and reliable NVMe storage | A bootc image = Fedora aarch64 base + overlay. `probeos.sh` gains "install image" and "remove". Manual rollback by choosing the previous deployment in the project's loader. Recovery from macOS | Install, boot, update, manual rollback and full removal all performed on the owner's Mac and logged |
| 2: Everyday desktop | Phase 1 plus a working keyboard, touchpad and display under mainline | Automatic boot counting with health-check blessing. Two versioned copies of the boot stage. Flathub by default. First-boot setup. x86 emulation. Per-device support matrix | A deliberately broken update rolls back unattended **on hardware**. A deliberately broken boot stage is recovered using the documented macOS path |
| 3: Scale | Phase 2 stable for several update cycles | testing→stable image tags, openQA or QEMU userland tests in CI, cosign-verified images, delta delivery, later sealed images | Emulator results are reported separately from the physical-device lab, which starts with a single Mac |

A small team should not attempt a new package manager, a new app store, payments, crash-telemetry-driven phased rollout, multi-year support promises, or GPU/display features such as ProMotion and HDR. The notes classify these as either requiring a large organisation or being upstream driver work ([universal-blue.org](https://universal-blue.org/); [Ubuntu blog](https://ubuntu.com/blog/people-and-processes-behind-ubuntu-certified-devices); [asahilinux.org/fedora](https://asahilinux.org/fedora/)).

## Fedora and Debian lead a field where only Arch lacks official aarch64

All traditional managers except pacman ship official aarch64 builds. **Debian 13 "trixie" (2025-08-09) carries 69,830 packages** and ships APT 3.0, which verifies signatures with Sequoia's `sqv` and adds a new solver ([Debian news](https://www.debian.org/News/2025/20250809); [LWN](https://lwn.net/Articles/1017315/)). **Fedora made DNF5 the default in Fedora 41.** Fedora reports queries about 2x faster than the old dnf and a single metadata cache shared with the PackageKit daemon ([Fedora Changes/SwitchToDnf5](https://fedoraproject.org/wiki/Changes/SwitchToDnf5)). RPM 6.0 enforces signature checking by default and supports multiple and post-quantum signatures ([Fedora Changes/RPM-6.0](https://fedoraproject.org/wiki/Changes/RPM-6.0)). Fedora's own RPM-level enforcement is scheduled for Fedora 45, although DNF has always enforced signatures itself ([Fedora Changes](https://fedoraproject.org/wiki/Changes/Enforcing_signature_checking_by_default)). By contrast, **Arch marks AArch64 "Unofficial"**, with packages "not built with Arch Linux infrastructure, not signed by Arch Linux Staff" ([Arch Ports](https://ports.archlinux.page/aarch64/)). The Collabora/Valve Holo Core port was only an early experimental preview in July 2026 ([Collabora](https://www.collabora.com/news-and-blog/news-and-events/building-an-arch-linux-aarch64-port-for-holo-core.html)). Arch Linux ARM signs packages but leaves repository databases unsigned ([archlinuxarm.org](https://archlinuxarm.org/about/package-signing)). Alpine 3.23 ships apk-tools v3 ([Alpine](https://alpinelinux.org/posts/Alpine-3.23.0-released.html)). Gentoo has run an official arm64 binhost since December 2023 ([Gentoo news](https://www.gentoo.org/news/2023/12/29/Gentoo-binary.html)). Void's aarch64 images do not support its installer ([voidlinux.org](https://voidlinux.org/download/)).

The ecosystem-wide lesson is about key hygiene. From 2026-02-01, APT's `sqv` policy rejects SHA-1-based key bindings, and third-party repositories such as NodeSource and Gitea broke on trixie as a result ([NodeSource](https://nodesource.com/blog/gpg-signature-warnings-debian-13-ubuntu-nodesource); [gitea#35588](https://github.com/go-gitea/gitea/issues/35588)). **Interpretation:** a new distribution's overlay repository should start with modern keys, a rotation plan, and signed metadata *and* signed packages. Otherwise the project repeats the break that hit those repositories.

The functional systems offer what the traditional ones lack. **NixOS** builds each configuration as a bootable generation and rolls back with `nixos-rebuild switch --rollback` ([NixOS manual](https://nixos.org/manual/nixos/stable/#sec-rollback)). It requires signed binary-cache paths by default ([Nix manual](https://nix.dev/manual/nix/stable/command-ref/conf-file.html)). However, **aarch64-linux is Tier 2**, with fewer developers and less testing than x86_64 ([RFC 0046](https://github.com/NixOS/rfcs/blob/master/rfcs/0046-platform-support-tiers.md)). The community Apple Silicon port has **no binary cache**, stopped tagged releases on 2025-08-10, and says stable releases are "neither tested nor guaranteed" ([nixos-apple-silicon release notes](https://github.com/nix-community/nixos-apple-silicon/blob/main/docs/release-notes.md)). **GNU Guix** supports aarch64 but defaults to the Linux-libre kernel ([Guix manual](https://guix.gnu.org/manual/en/html_node/GNU-Distribution.html)). **Interpretation:** Linux-libre conflicts with a platform that needs Apple firmware blobs, and the Nix learning curve is a real adoption cost, although no quantitative source measured it.

### Why Fedora rather than Debian (interpretation, with the steelman)

Debian has the stronger *public reproducibility evidence* on arm64 and the larger counted archive, and its stable cadence suits a small team. Fedora wins on precedent for this exact hardware class. **Fedora Asahi Remix is the Asahi project's "flagship" and "a reference for other distributions"** ([Asahi About](https://asahilinux.org/about/)). It uses stock DNF with core packages "straight from the Fedora repositories" plus a few enablement forks ([Asahi blog 2023-08-02](https://asahilinux.org/2023/08/fedora-asahi-remix/)). Fedora 44 retired the vendored Mesa in favour of upstream Fedora Mesa ([Fedora Magazine](https://fedoramagazine.org/?p=43273)). Fedora also packages the complete x86 compatibility stack for 16K-page hosts ([Fedora Changes/FEX](https://fedoraproject.org/wiki/Changes/FEX)), and bootc image tooling ships with Fedora Atomic ([Fedora Change](https://fedoraproject.org/wiki/Changes/DNFAndBootcInImageModeFedora)). Ubuntu Asahi exists as an unaffiliated community project, but no maturity statement was found ([ubuntuasahi.org](https://ubuntuasahi.org/)). **Debian remains a credible fallback.** If Fedora's six-month cadence proves too fast for a one-person project, a Debian/APT base with mkosi images (below) is the alternative this report would choose.

## Image-based delivery with health-checked rollback is what "premium" means

The traditional managers have **no built-in whole-system rollback**. DNF's `history undo` depends on old package versions still being available. That limitation is general background knowledge and was not re-verified in the notes. The image and transactional systems close the gap in four different ways.

**rpm-ostree and bootc.** rpm-ostree is a "hybrid image/package system": the vendor ships a prebuilt `/usr`, and rollback reverts `/usr` while preserving `/etc` and `/var` ([rpm-ostree docs](https://coreos.github.io/rpm-ostree/)). Its successor, **bootc**, ships the entire OS, kernel included, as an OCI container image. It stages updates A/B-style, and `bootc rollback` "will swap the bootloader ordering to the previous boot entry" ([bootc upgrades](https://bootc.dev/bootc/upgrades.html)). Crucially, **bootc itself has no automatic health-based rollback**. That role falls to greenboot, which runs required checks and reverts after repeated failed boots using a GRUB `boot_counter` ([greenboot](https://github.com/fedora-iot/greenboot/blob/main/README.md)).

**openSUSE MicroOS.** MicroOS writes each update into a new Btrfs snapshot. Its health-checker uses a three-tier policy: roll back automatically, retry once, then stop in a minimal state where "an admin can login, but no service should run". This avoids reboot loops ([health-checker](https://github.com/openSUSE/health-checker/blob/master/README.md)).

**A/B partition systems.** ChromeOS, Android and SteamOS keep a full untouched slot and fall back when the tries counter runs out ([ChromiumOS disk format](https://www.chromium.org/chromium-os/developer-library/reference/device/disk-format/); [AOSP A/B](https://source.android.com/docs/core/ota/ab)). SteamOS 3.6 moved to desync chunk delivery, reporting "30%-50% faster" updates and resumable downloads ([Collabora](https://www.collabora.com/news-and-blog/news-and-events/steamos-3-6-how-the-steam-deck-atomic-updates-are-improving.html)). systemd now offers a distro-neutral version of the same parts: **systemd-sysupdate** for A/B versioned partitions or files ([man7](https://man7.org/linux/man-pages/man8/systemd-sysupdate.8.html)), **boot counting** through `+tries-left` filenames blessed by `boot-complete.target` ([systemd.io](https://systemd.io/AUTOMATIC_BOOT_ASSESSMENT/)), UKIs whose `.dtbauto`/`.hwids` sections choose a device tree per board ([UAPI.5](https://uapi-group.org/specifications/specs/unified_kernel_image/)), and **mkosi** to build the images ([mkosi](https://github.com/systemd/mkosi)).

**Sealed images.** A 2026 track chains Secure Boot, a signed UKI carrying a composefs digest, and per-file fs-verity ([bootc blog 2026-05-07](https://bootc.dev/blog/2026-may-07-sealed-images-deploying/)). An open 2026 issue still reports composefs fs-verity errors ([bootc#2471](https://github.com/bootc-dev/bootc/issues/2471)).

**Interpretation, why bootc first.** Three facts favour bootc over sysupdate A/B for this project. First, ostree deployments deduplicate, whereas A/B doubles the root. The Linux share of a Mac disk is carved from APFS, and the reference installer already needs about 40 GB for Linux and reserves 38 GB for macOS updates ([Asahi FAQ](https://asahilinux.org/docs/project/faq/)). Second, there is a working precedent: unofficial "Fedora Asahi Remix Atomic" bootc images already exist. They are cosign-signed and rebuilt daily, but described as "a work in progress… not endorsed by the Asahi developers" ([fedora-asahi-remix-atomic-desktops](https://github.com/fedora-asahi-remix-atomic-desktops/images)). Third, the Universal Blue projects show the build pipeline is maintainable by a small team using GitHub Actions ([ublue-os/image-template](https://github.com/ublue-os/image-template)).

The main risk is that **every surveyed rollback system assumes GRUB or systemd-boot on UEFI**. This project's own loader replaces that layer. The loader would therefore have to discover deployment entries, apply a tries counter, and fall back itself. The project must build and test that. **Nothing in the notes shows bootc working with a non-UEFI custom loader**, and the sealed-image chain presumes UEFI Secure Boot, which Apple Silicon does not provide in this form. If the bootc integration proves awkward, mkosi plus sysupdate with plain versioned kernel/initramfs files and a verity-protected root is the cleaner fallback, because the loader then only has to choose between a few files.

## Flathub is the only realistic app store, with an aarch64 gap

**Flathub listed 3,668 desktop apps, 2,174 of them verified**, at fetch time on 2026-09-27 ([Flathub statistics](https://flathub.org/en/statistics)). It "builds on both `x86_64` and `aarch64` by default" ([Flathub requirements](https://docs.flathub.org/docs/for-app-authors/requirements)). Flatpak apps start with no network or home access and ask for more through portals ([Flatpak docs](https://docs.flatpak.org/en/latest/sandbox-permissions.html)). Users can restrict the remote to verified publishers with `--subset=verified` ([Flathub verification](https://docs.flathub.org/docs/for-users/verification)). Two weaknesses matter here. First, **aarch64 was 1.3% of Flathub's 438.2 million downloads in 2025** ([Flathub 2025 review](https://flathub.org/en/year-in-review/2025)). That is a weak demand signal to vendors. Proprietary apps such as Spotify ship no aarch64 Linux build ([Spotify community](https://community.spotify.com/t5/Desktop-Linux/spotify-desktop-for-aarch64-linux/m-p/6638997/highlight/true)). Second, **paid apps are still not live**. As of late 2025 payments were "not ready yet" ([KDE Planet](https://planet.kde.org/siosms-blog-2025-11-23-how-do-we-keep-apps-maintained-on-flathub-or-building-a-more-respectful-app-store/)), and the GNOME Foundation's September 2026 update announced no launch ([GNOME Foundation](https://blogs.gnome.org/aday/2026/09/17/gnome-foundation-update-september-2026/)). The share of Flathub apps that have an aarch64 build was **not found** in any source.

The alternatives are weaker for an independent distribution. **Snap** has strong strict confinement but depends on AppArmor, runs from a single Canonical-controlled store ([Snap docs](https://snapcraft.io/docs/explanation/security/classic-confinement/)), and had repeated malware incidents through January 2026, including hijacked publisher domains ([Alan Pope](https://blog.popey.com/2026/01/malware-purveyors-taking-over-published-snap-email-domains/)). **AppImage** has no central catalog and updates only if each app embeds update information ([AppImageUpdate](https://github.com/AppImageCommunity/AppImageUpdate/releases)). **GNOME Software and KDE Discover** combine distro packages (through PackageKit), Flatpak and firmware updates in one UI using AppStream metadata ([GNOME Software README](https://github.com/GNOME/gnome-software/blob/main/README.md)). They draw ratings from the shared ODRS service ([ODRS](https://odrs.gnome.org/)). elementary OS 8 shows the premium pattern: OS updates live in Settings and need a restart, app updates apply without one, and the store shows sandbox warnings ([elementary blog](https://blog.elementary.io/os-8-available-now/)).

One caveat applies to Apple Silicon. Fedora Asahi Remix 44 states that **GNOME Software upgrades are not supported** and directs users to Plasma Discover or DNF System Upgrade ([Fedora Magazine](https://fedoramagazine.org/?p=43273)). **Interpretation:** the project should choose the front end whose OS-update path it has actually tested with its own image and boot stage, and should not assume a generic store UI handles Mac-specific boot pieces.

## Apple Silicon adds five constraints no general Linux distribution faces

**16K pages.** Apple Silicon IOMMUs "only support 16K-aligned pages". Binaries whose ELF LOAD segments align below `0x4000` segfault before they start ([Asahi Broken software](https://asahilinux.org/docs/sw/broken-software/)). Chromium/Electron 102+, Firefox 123+, Wine 10.5+ and more than 40 other packages are fixed. hardened_malloc, notion-app and Waydroid remain broken (same source). jemalloc built for 4K pages aborts with "Unsupported system page size" in static binaries such as ripgrep, fd and Telegram Desktop ([jemalloc#2639](https://github.com/jemalloc/jemalloc/issues/2639); [fd#1085](https://github.com/sharkdp/fd/issues/1085)). No source documents a Flatpak-specific 16K failure. **Interpretation:** the risk sits in third-party prebuilt binaries, including extra-data Flatpaks that wrap vendor binaries, rather than in distro-built packages. The project needs a 4K escape hatch and a published known-broken list.

**x86 compatibility.** Since Fedora 42, `dnf install @x86-emulation` installs FEX, a Fedora-built x86 rootfs, muvm and binfmt-dispatcher, with "muvm to take precedence over bare FEX on non-4k page-size systems" ([Fedora Changes/FEX](https://fedoraproject.org/wiki/Changes/FEX); [Fedora Magazine](https://fedoramagazine.org/new-in-fedora-running-x86-programs-on-arm-systems/)). The Steam stack was labelled an alpha in October 2024, and most games need 16 GB of RAM ([Asahi blog](https://asahilinux.org/2024/10/aaa-gaming-on-asahi-linux/)). **Interpretation:** that matters on the owner's 8 GB machine. box64 v0.4.6 (preview 2026-08-07) runs Steam and Proton on 16K without a microVM, but some games still crash ([box86.org](https://box86.org/2026/08/preview-of-next-box64-improved-non-4k-pagesize-handling/)).

**Firmware.** Apple firmware is not redistributed. The Asahi installer extracts it from Apple's IPSW images into `vendorfw/firmware.cpio` on the per-OS ESP, with a SHA256 manifest. It is loaded as an early initrd or located through a device-tree property ([Asahi Open OS interop](https://asahilinux.org/docs/platform/open-os-interop/)). The kernel targets specific macOS firmware ABIs, and Linux 7.2-era fixes covered SMC changes introduced by macOS 27 ([Progress Report 7.2](https://asahilinux.org/2026/08/progress-report-7-2/)). **Interpretation:** firmware is fixed at install time, not delivered through LVFS or package updates. The project needs its own independently written extraction tool. Adopting the documented `vendorfw` layout for interoperability is a format choice, not code reuse.

**Dual-boot with macOS.** Each installed OS gets its own ~2.5 GB APFS stub container, its own ~512 MB ESP and its own recoveryOS. Apple's boot picker "knows nothing about EFI" ([Asahi Open OS interop](https://asahilinux.org/docs/platform/open-os-interop/)). An internal macOS install must remain to "install… update/repair m1n1 and resize" installations. There is **no automated uninstaller**, and deleting `Apple_APFS_ISC` or `Apple_APFS_Recovery` can force a factory restore ([Asahi FAQ](https://asahilinux.org/docs/project/faq/); [Partitioning cheatsheet](https://asahilinux.org/docs/sw/partitioning-cheatsheet/)). The last-resort path is an Apple Configurator or `idevicerestore` DFU restore (same source). There is no EFI variable store, so `efibootmgr`-style entries do not work ([Asahi Open OS interop](https://asahilinux.org/docs/platform/open-os-interop/)). There is also no TPM-style sealing, so Ubuntu's TPM-backed disk encryption ([Ubuntu docs](https://ubuntu.com/desktop/docs/en/latest/how-to/encrypt-your-disk-with-tpm/)) does not apply. The notes found no source for Apple Silicon LUKS sealing, so passphrase-based encryption is the known option.

**The unprotected boot stage.** In Asahi's chain, stage 1 is installed from recoveryOS and "can be considered immutable". Stage 2, device trees and U-Boot sit together on the ESP. If they fail, the documented fix is to boot macOS and "put the old one back" ([Asahi Boot Process guide](https://asahilinux.org/docs/alt/boot-process-guide/)). **No public source describes A/B or boot counting for that stage**, and distributions are told never to downgrade it automatically ([Asahi Open OS interop](https://asahilinux.org/docs/platform/open-os-interop/)). **Interpretation:** this project replaces m1n1 and U-Boot with its own code, so the problem is entirely the project's. Keep the recoveryOS-installed stage minimal and rarely changed. Keep two versioned copies of anything updatable on the ESP and swap them atomically. Record which copy last booted successfully. Ship a scripted "repair from macOS" command. That command is the natural next mode of the existing `probeos.sh` and `probeos-recovery.sh`, whose tests so far run only against fake system tools.

**A hardware gap the package layer cannot fix.** On MacBookPro17,1, the GPU, keyboard, touchpad, speakers, headphone jack, webcam and sleep are listed as downstream-only ("linux-asahi"), not upstream ([Asahi M1 feature support](https://asahilinux.org/docs/platform/feature-support/m1/)). This project reuses mainline Linux and may not copy Asahi code. **Interpretation:** a "premium" desktop therefore depends on M4 hardware enablement for at least input devices, and until that exists no distribution choice can deliver one. It also means the Asahi distribution guidelines, which require packaging the Asahi kernel fork, m1n1 and the U-Boot fork within two weeks of upstream releases ([Asahi policy](https://asahilinux.org/docs/alt/policy/)), do not describe this project. The project would not be an Asahi-recognised distribution.

## Comparison of approaches, with what each number measures

Reproducibility figures are **not comparable across rows**, because each project counts different things. Debian's rebuilder counts binary-package artifact rows, possibly across several versions and suites. Its **97.5% = 216,341 good ÷ (216,341 good + 5,539 bad)** for arm64 "main"; 36.4% of rows are untested, and good rows are 62.0% of all rows ([reproduce.debian.net arm64](https://reproduce.debian.net/arm64/api/v0/dashboard), snapshot 2026-09-28 03:11 UTC). Arch's figures cover **x86_64 only**: 98.1% of tested "core" and 88.1% of tested "extra" packages ([Arch rebuilderd](https://reproducible.archlinux.org/api/v0/dashboard)). Fedora's **"about 90%"** is a self-reported figure from a Change proposal that deferred its 99% goal to Fedora 44, and the notes did not verify whether Fedora 44 adopted it ([Fedora wiki](https://fedoraproject.org/wiki/Changes/Package_builds_are_expected_to_be_reproducible); [LWN](https://lwn.net/Articles/1014979/)). NixOS publishes attestations but no headline percentage: 162,928 derivations and 266,819 attestations across 6 jobsets ([Lila tracker](https://reproducibility.nixos.social/)). The "Premium-UX potential" and "Fit" columns are **interpretation**.

| Approach | Install model | Update / rollback | Reproducibility evidence | aarch64 and 16K readiness | Premium-UX potential | Fit for this project |
|---|---|---|---|---|---|---|
| Debian / APT (mutable) | Package install onto a writable root | No native rollback; needs snapshots | arm64 main: 97.5% of tested artifact rows reproduce, 36.4% untested | arm64 is a release architecture. No Apple Silicon precedent verified | Medium unless wrapped in an image | Strong fallback base |
| Fedora / DNF5 (mutable, like Fedora Asahi Remix) | Package install | `dnf history` only; no atomic rollback | ~90%, self-reported | Official aarch64. The reference distribution on M1-class Macs uses it with a 16K kernel | Medium | **Recommended package base** |
| Fedora Atomic / bootc (image) | Prebuilt OCI image, ostree deployments | Staged A/B-style; manual `rollback`; automatic only with greenboot | Inherits Fedora's packages. Image-level reproducibility not sourced | Unofficial Asahi bootc images exist. Untested with a non-UEFI loader | High | **Recommended delivery model** |
| openSUSE MicroOS (transactional-update) | Btrfs snapshot built on the device | Automatic via health-checker and boot counting | Not researched | No Apple Silicon source found | High | Good policy model; weaker fleet sameness |
| A/B + systemd-sysupdate + mkosi (ChromeOS/SteamOS pattern) | Whole partition or versioned files | Automatic via tries counter | mkosi reproducibility not stated | Distro-neutral. Doubles root space on a shared Mac disk | Very high | Fallback if bootc integration fails |
| NixOS | Declarative generations | Boot-menu rollback; no automatic health check | Attestations, no percentage | Tier 2 aarch64. Apple Silicon port has no binary cache | Medium (steep learning curve) | Not recommended for a small team |
| Arch / pacman | Package install | None built in | x86_64 only: 98.1% core / 88.1% extra of tested | No official aarch64 | Low–medium | Not recommended |
| Flatpak / Flathub (apps) | Per-app sandboxed bundles | Per-app updates; OSTree underneath | Not measured | Builds aarch64 by default, but aarch64 was 1.3% of 2025 downloads | High | **Recommended app layer** |
| Snap (apps) | Store-delivered, auto-refresh 4×/day | Per-snap revisions | Not measured | Strict confinement needs AppArmor | Medium | Not recommended |
| AppImage (apps) | Single file, no install | Opt-in per app | Not measured | Only if the upstream builds for aarch64 | Low | Fallback for vendor binaries only |

The table's gaps are real gaps in the evidence. The notes found no aarch64 package counts except Debian's (Repology was unreachable), no delta-size benchmarks for bootc, ostree or desync, no Flathub per-architecture app share, no primary Fedora Asahi docs (blocked to the fetch tool), and no source on what major macOS updates do to an installed Linux stub.

## Conclusion

The research turns the owner's "premium from installation onwards" goal into a narrower engineering question. Premium Linux products earn their polish by *hiding* the package manager behind an atomic image and a sandboxed app store, and all of those parts can be reused. The part no existing system can hand over is the part this project already owns: the Apple-specific boot stage and the macOS-side installer and recovery flow. That places the project's distinctive M5 work in its loader (entry selection, tries counting, two copies of itself) and in the `probeos.sh` lineage (install, repair and remove from macOS). Package infrastructure is not where the effort should go. Reuse Fedora and Flathub, and spend the scarce engineering time where no one else can help.

The second implication is sequencing. On MacBookPro17,1, mainline Linux does not yet drive the keyboard, touchpad, GPU or speakers, so the "premium" ceiling is set by M4 hardware work, not by distribution choice. The honest next step is Phase 0: a reproducible 16K-page kernel RPM in a signed overlay repository, built alongside M3. That step is useful whichever image model wins, and it creates the first artifact M5 can test on real hardware. Until the project boots Linux on the physical Mac, every recommendation in this report remains a proposal.

## Sources

All sources were accessed 2026-09-27 unless noted. Publication dates are given where the notes recorded them.

**Package managers and reproducibility**
- Debian, "Debian 13 trixie released" (2025-08-09): https://www.debian.org/News/2025/20250809
- LWN, "What's new in APT 3.0" (2025): https://lwn.net/Articles/1017315/
- Debian 13 release notes: https://www.debian.org/releases/stable/release-notes/
- NodeSource blog, GPG signature warnings on Debian 13: https://nodesource.com/blog/gpg-signature-warnings-debian-13-ubuntu-nodesource
- Gitea issue #35588: https://github.com/go-gitea/gitea/issues/35588
- reproduce.debian.net arm64 dashboard (snapshot 2026-09-28 03:11 UTC): https://reproduce.debian.net/arm64/api/v0/dashboard
- reproduce.debian.net amd64 dashboard (same snapshot): https://reproduce.debian.net/amd64/api/v0/dashboard
- Arch rebuilderd dashboard (same snapshot): https://reproducible.archlinux.org/api/v0/dashboard
- Fedora Changes/SwitchToDnf5: https://fedoraproject.org/wiki/Changes/SwitchToDnf5
- Fedora Changes/RPM-6.0: https://fedoraproject.org/wiki/Changes/RPM-6.0
- Fedora Changes/Enforcing signature checking by default: https://fedoraproject.org/wiki/Changes/Enforcing_signature_checking_by_default
- Fedora Changes/Package builds are expected to be reproducible (proposed 2025-03-31, deferred 2025-09): https://fedoraproject.org/wiki/Changes/Package_builds_are_expected_to_be_reproducible
- LWN on Fedora reproducible builds (2025): https://lwn.net/Articles/1014979/
- Arch Ports, AArch64: https://ports.archlinux.page/aarch64/
- Collabora, Arch Linux AArch64 port for Holo Core (2026-07): https://www.collabora.com/news-and-blog/news-and-events/building-an-arch-linux-aarch64-port-for-holo-core.html
- Arch Linux ARM, package signing: https://archlinuxarm.org/about/package-signing
- Alpine 3.23.0 release: https://alpinelinux.org/posts/Alpine-3.23.0-released.html
- Void Linux downloads: https://voidlinux.org/download/
- Gentoo, "Gentoo goes Binary!" (2023-12-29): https://www.gentoo.org/news/2023/12/29/Gentoo-binary.html
- NixOS RFC 0046, platform support tiers: https://github.com/NixOS/rfcs/blob/master/rfcs/0046-platform-support-tiers.md
- Nix manual, nix.conf: https://nix.dev/manual/nix/stable/command-ref/conf-file.html
- NixOS manual, rollback: https://nixos.org/manual/nixos/stable/#sec-rollback
- NixOS reproducibility (Lila) tracker: https://reproducibility.nixos.social/
- GNU Guix manual, GNU Distribution: https://guix.gnu.org/manual/en/html_node/GNU-Distribution.html

**Atomic updates and recovery**
- rpm-ostree documentation: https://coreos.github.io/rpm-ostree/
- greenboot README: https://github.com/fedora-iot/greenboot/blob/main/README.md
- bootc upgrades documentation: https://bootc.dev/bootc/upgrades.html
- bootc blog, deploying and verifying a sealed image (2026-05-07): https://bootc.dev/blog/2026-may-07-sealed-images-deploying/
- bootc issue #2471 (2026): https://github.com/bootc-dev/bootc/issues/2471
- Fedora Change, DNF and bootc in Image Mode: https://fedoraproject.org/wiki/Changes/DNFAndBootcInImageModeFedora
- openSUSE health-checker README: https://github.com/openSUSE/health-checker/blob/master/README.md
- ChromiumOS disk format: https://www.chromium.org/chromium-os/developer-library/reference/device/disk-format/
- AOSP A/B updates: https://source.android.com/docs/core/ota/ab
- Collabora, SteamOS 3.6 atomic updates (2024-05-10): https://www.collabora.com/news-and-blog/news-and-events/steamos-3-6-how-the-steam-deck-atomic-updates-are-improving.html
- systemd-sysupdate(8), man7 mirror: https://man7.org/linux/man-pages/man8/systemd-sysupdate.8.html
- systemd Automatic Boot Assessment: https://systemd.io/AUTOMATIC_BOOT_ASSESSMENT/
- UAPI.5 Unified Kernel Image specification: https://uapi-group.org/specifications/specs/unified_kernel_image/
- mkosi: https://github.com/systemd/mkosi
- Universal Blue: https://universal-blue.org/
- ublue-os image-template: https://github.com/ublue-os/image-template
- fedora-asahi-remix-atomic-desktops images: https://github.com/fedora-asahi-remix-atomic-desktops/images

**Apps and stores**
- Flatpak docs, sandbox permissions: https://docs.flatpak.org/en/latest/sandbox-permissions.html
- Flathub statistics (fetched 2026-09-27): https://flathub.org/en/statistics
- Flathub 2025 Year in Review: https://flathub.org/en/year-in-review/2025
- Flathub requirements: https://docs.flathub.org/docs/for-app-authors/requirements
- Flathub verified apps: https://docs.flathub.org/docs/for-users/verification
- Spotify community, aarch64 Linux request: https://community.spotify.com/t5/Desktop-Linux/spotify-desktop-for-aarch64-linux/m-p/6638997/highlight/true
- KDE Planet, keeping apps maintained on Flathub (2025-11-23): https://planet.kde.org/siosms-blog-2025-11-23-how-do-we-keep-apps-maintained-on-flathub-or-building-a-more-respectful-app-store/
- GNOME Foundation update (2026-09-17): https://blogs.gnome.org/aday/2026/09/17/gnome-foundation-update-september-2026/
- Snap docs, classic confinement: https://snapcraft.io/docs/explanation/security/classic-confinement/
- Alan Pope, snap publisher-domain takeovers (2026-01): https://blog.popey.com/2026/01/malware-purveyors-taking-over-published-snap-email-domains/
- AppImageUpdate releases: https://github.com/AppImageCommunity/AppImageUpdate/releases
- GNOME Software README: https://github.com/GNOME/gnome-software/blob/main/README.md
- ODRS: https://odrs.gnome.org/
- elementary OS 8 announcement (2024-11-26): https://blog.elementary.io/os-8-available-now/

**Apple Silicon specifics**
- Asahi Linux, About: https://asahilinux.org/about/
- Asahi blog, "Our new flagship distro: Fedora Asahi Remix" (2023-08-02): https://asahilinux.org/2023/08/fedora-asahi-remix/
- Fedora Magazine, Fedora Asahi Remix 43 (2026-03-18): https://fedoramagazine.org/fedora-asahi-remix-43-is-now-available/
- Fedora Magazine, Fedora Asahi Remix 44 (2026-04-28): https://fedoramagazine.org/?p=43273
- asahilinux.org/fedora: https://asahilinux.org/fedora/
- Asahi docs, M1 feature support: https://asahilinux.org/docs/platform/feature-support/m1/
- Asahi docs, FAQ: https://asahilinux.org/docs/project/faq/
- Asahi docs, partitioning cheatsheet: https://asahilinux.org/docs/sw/partitioning-cheatsheet/
- Asahi docs, distribution guidelines: https://asahilinux.org/docs/alt/policy/
- Asahi docs, Open OS platform interoperability: https://asahilinux.org/docs/platform/open-os-interop/
- Asahi docs, boot process guide: https://asahilinux.org/docs/alt/boot-process-guide/
- Asahi docs, broken software (16K pages): https://asahilinux.org/docs/sw/broken-software/
- Asahi Progress Report, Linux 7.2 (2026-08/09): https://asahilinux.org/2026/08/progress-report-7-2/
- Asahi blog, AAA gaming on Asahi Linux (2024-10-10): https://asahilinux.org/2024/10/aaa-gaming-on-asahi-linux/
- asahi-installer repository (pattern reference only; code not reused): https://github.com/AsahiLinux/asahi-installer
- nixos-apple-silicon release notes: https://github.com/nix-community/nixos-apple-silicon/blob/main/docs/release-notes.md
- Ubuntu Asahi: https://ubuntuasahi.org/
- jemalloc issue #2639: https://github.com/jemalloc/jemalloc/issues/2639
- fd issue #1085: https://github.com/sharkdp/fd/issues/1085
- Fedora Changes/FEX: https://fedoraproject.org/wiki/Changes/FEX
- Fedora Magazine, running x86 programs on ARM (2025-04-15): https://fedoramagazine.org/new-in-fedora-running-x86-programs-on-arm-systems/
- box86.org, box64 non-4K page-size preview (2026-08-07): https://box86.org/2026/08/preview-of-next-box64-improved-non-4k-pagesize-handling/

**Premium experience and scale**
- Ubuntu docs, TPM-backed disk encryption: https://ubuntu.com/desktop/docs/en/latest/how-to/encrypt-your-disk-with-tpm/
- Ubuntu blog, people and processes behind Ubuntu certified devices: https://ubuntu.com/blog/people-and-processes-behind-ubuntu-certified-devices
