/* SPDX-License-Identifier: GPL-2.0-or-later */
/*
 * hvf_run: run a raw AArch64 image on this Mac's real CPU cores with Apple's
 * Hypervisor.framework (macOS on Apple Silicon only). The guest runs at EL1 with
 * its MMU off, inside a VM whose memory map this tool defines; it is not an M1
 * boot environment (no EL2, no iBoot, no Apple devices). What it adds over the
 * Unicorn tests: real instruction execution, real exception entry into the
 * guest's own vectors, and real FP/SIMD and alignment traps.
 *
 * Options (addresses and sizes accept 0x hex):
 *   --map ADDR:SIZE        guest RAM (16 KB aligned), filled with --fill (default 0)
 *   --fill BYTE            fill byte for subsequent --map regions
 *   --load FILE@ADDR       copy a file into mapped RAM
 *   --entry ADDR           initial PC
 *   --reg xN=V | sp=V      initial register (sp sets SP_EL1)
 *   --pstate V             initial PSTATE (default 0x3c5: EL1h, DAIF masked)
 *   --uart ADDR            emulate PL011 DR (+0x00) and FR (+0x18) at ADDR
 *   --input TEXT           bytes the UART delivers to the guest
 *   --dump ADDR:SIZE:FILE  write guest memory to FILE when the run stops
 *   --max-exits N          stop after N VM exits (default 50000000)
 *   --timeout SECONDS      wall-clock limit (default 30)
 *   --gic DIST:REDIST      create an in-kernel GICv3 (macOS 15+) at these guest
 *                          addresses; also enables PSCI over HVC/SMC (VERSION,
 *                          FEATURES, SYSTEM_OFF, SYSTEM_RESET) for Linux guests
 *   --gic-info             print GIC sizes/alignments and exit
 *
 * WFE does not necessarily exit to the host, so a watchdog thread interrupts
 * the vCPU every 20 ms; a vCPU found at a WFE instruction counts as parked.
 *
 * Guest UART output goes to stdout. The final status line on stderr is one of
 * "[stop: idle]" (input consumed, output ends with "\n> "), "[stop: parked]"
 * (guest waiting in WFE/WFI), "[stop: poweroff]" / "[stop: reset]" (PSCI),
 * "[stop: limit]", "[stop: timeout]", or "[stop: fault ...]".
 * Exit status: 0 idle/parked/poweroff/reset, 3 otherwise, 2 setup error.
 */
#include <Hypervisor/Hypervisor.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

#define WFE_INSN 0xd503205fU

#define MAX_MAPS 8
#define MAX_DUMPS 4
#define PAGE 0x4000ULL

struct map { uint64_t addr, size; uint8_t *host; };
struct dump { uint64_t addr, size; const char *file; };

static struct map maps[MAX_MAPS];
static int nmaps;

static uint64_t num(const char *s) { return strtoull(s, NULL, 0); }

static uint8_t *host_ptr(uint64_t addr, uint64_t size) {
    for (int i = 0; i < nmaps; i++)
        if (addr >= maps[i].addr && size <= maps[i].size && addr - maps[i].addr <= maps[i].size - size)
            return maps[i].host + (addr - maps[i].addr);
    return NULL;
}

static hv_vcpu_t watched_vcpu;
static volatile int running = 1;

static void *watchdog(void *arg) {
    (void)arg;
    while (running) {
        usleep(20000);
        hv_vcpus_exit(&watched_vcpu, 1);
    }
    return NULL;
}

static int is_wfe(uint64_t addr) {
    uint8_t *insn = host_ptr(addr, 4);
    return insn && (uint32_t)(insn[0] | insn[1] << 8 | insn[2] << 16 | (uint32_t)insn[3] << 24) == WFE_INSN;
}

/* A `wfe; b 1b` park loop can be interrupted on either instruction. */
static int at_wfe(uint64_t pc) {
    return is_wfe(pc) || (pc >= 4 && is_wfe(pc - 4));
}

static int fail(const char *msg, const char *arg) {
    fprintf(stderr, "hvf_run: %s%s%s\n", msg, arg ? ": " : "", arg ? arg : "");
    return 2;
}

int main(int argc, char **argv) {
    struct dump dumps[MAX_DUMPS];
    int ndumps = 0;
    const char *input = "";
    uint64_t entry = 0, pstate = 0x3c5, uart = 0, max_exits = 50000000, timeout = 30;
    int have_uart = 0, fill = 0, have_gic = 0;
    uint64_t gic_dist = 0, gic_redist = 0;
    uint64_t regs[31] = {0}, sp = 0;
    int reg_set[31] = {0}, sp_set = 0;
    struct { const char *file; uint64_t addr; } loads[MAX_MAPS];
    int nloads = 0;

    if (argc == 2 && !strcmp(argv[1], "--gic-info")) {
        size_t ds = 0, da = 0, rs = 0, rr = 0, ra = 0;
        uint32_t spi_base = 0, spi_count = 0;
        if (hv_gic_get_distributor_size(&ds) || hv_gic_get_distributor_base_alignment(&da) ||
            hv_gic_get_redistributor_size(&rs) || hv_gic_get_redistributor_region_size(&rr) ||
            hv_gic_get_redistributor_base_alignment(&ra) || hv_gic_get_spi_interrupt_range(&spi_base, &spi_count))
            return fail("GIC parameters unavailable (needs macOS 15 or later)", NULL);
        printf("distributor_size=0x%zx distributor_align=0x%zx redistributor_size=0x%zx "
               "redistributor_region_size=0x%zx redistributor_align=0x%zx spi_base=%u spi_count=%u\n",
               ds, da, rs, rr, ra, spi_base, spi_count);
        return 0;
    }
    for (int i = 1; i < argc; i++) {
        const char *opt = argv[i], *val = i + 1 < argc ? argv[i + 1] : NULL;
        if (!val) return fail("missing value for", opt);
        i++;
        if (!strcmp(opt, "--map")) {
            if (nmaps == MAX_MAPS) return fail("too many --map", NULL);
            char *colon = strchr(val, ':');
            if (!colon) return fail("--map needs ADDR:SIZE", val);
            uint64_t addr = num(val), size = num(colon + 1);
            if ((addr | size) & (PAGE - 1) || !size) return fail("--map must be 16 KB aligned", val);
            void *mem = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_ANON | MAP_PRIVATE, -1, 0);
            if (mem == MAP_FAILED) return fail("mmap failed", val);
            memset(mem, fill, size);
            maps[nmaps++] = (struct map){addr, size, mem};
        } else if (!strcmp(opt, "--fill")) {
            fill = (int)num(val);
        } else if (!strcmp(opt, "--load")) {
            char *at = strrchr(val, '@');
            if (!at || nloads == MAX_MAPS) return fail("--load needs FILE@ADDR", val);
            *at = 0;
            loads[nloads].file = val;
            loads[nloads++].addr = num(at + 1);
        } else if (!strcmp(opt, "--entry")) {
            entry = num(val);
        } else if (!strcmp(opt, "--reg")) {
            if (!strncmp(val, "sp=", 3)) { sp = num(val + 3); sp_set = 1; }
            else if (val[0] == 'x' && strchr(val, '=')) {
                int n = atoi(val + 1);
                if (n < 0 || n > 30) return fail("bad register", val);
                regs[n] = num(strchr(val, '=') + 1);
                reg_set[n] = 1;
            } else return fail("bad --reg", val);
        } else if (!strcmp(opt, "--pstate")) {
            pstate = num(val);
        } else if (!strcmp(opt, "--uart")) {
            uart = num(val);
            have_uart = 1;
        } else if (!strcmp(opt, "--input")) {
            input = val;
        } else if (!strcmp(opt, "--dump")) {
            char *a = strchr(val, ':'), *b = a ? strchr(a + 1, ':') : NULL;
            if (!b || ndumps == MAX_DUMPS) return fail("--dump needs ADDR:SIZE:FILE", val);
            dumps[ndumps++] = (struct dump){num(val), num(a + 1), b + 1};
        } else if (!strcmp(opt, "--max-exits")) {
            max_exits = num(val);
        } else if (!strcmp(opt, "--timeout")) {
            timeout = num(val);
        } else if (!strcmp(opt, "--gic")) {
            char *colon = strchr(val, ':');
            if (!colon) return fail("--gic needs DIST:REDIST", val);
            gic_dist = num(val);
            gic_redist = num(colon + 1);
            have_gic = 1;
        } else {
            return fail("unknown option", opt);
        }
    }

    for (int i = 0; i < nloads; i++) {
        FILE *f = fopen(loads[i].file, "rb");
        if (!f) return fail("cannot open", loads[i].file);
        fseek(f, 0, SEEK_END);
        long size = ftell(f);
        fseek(f, 0, SEEK_SET);
        uint8_t *dst = size > 0 ? host_ptr(loads[i].addr, (uint64_t)size) : NULL;
        if (!dst || fread(dst, 1, (size_t)size, f) != (size_t)size) {
            fclose(f);
            return fail("--load outside mapped RAM", loads[i].file);
        }
        fclose(f);
    }

    hv_vm_config_t config = hv_vm_config_create();
    uint32_t max_ipa = 0;
    if (hv_vm_config_get_max_ipa_size(&max_ipa) == HV_SUCCESS && max_ipa >= 40)
        hv_vm_config_set_ipa_size(config, 40);
    if (hv_vm_create(config) != HV_SUCCESS)
        return fail("hv_vm_create failed (needs Apple Silicon, virtualization support, and the "
                    "com.apple.security.hypervisor entitlement)", NULL);
    for (int i = 0; i < nmaps; i++)
        if (hv_vm_map(maps[i].host, maps[i].addr, maps[i].size,
                      HV_MEMORY_READ | HV_MEMORY_WRITE | HV_MEMORY_EXEC) != HV_SUCCESS)
            return fail("hv_vm_map failed", NULL);
    if (have_gic) { /* must precede vCPU creation */
        hv_gic_config_t gic = hv_gic_config_create();
        if (hv_gic_config_set_distributor_base(gic, gic_dist) != HV_SUCCESS ||
            hv_gic_config_set_redistributor_base(gic, gic_redist) != HV_SUCCESS ||
            hv_gic_create(gic) != HV_SUCCESS)
            return fail("hv_gic_create failed (check alignment with --gic-info)", NULL);
    }

    hv_vcpu_t vcpu;
    hv_vcpu_exit_t *exit_info;
    if (hv_vcpu_create(&vcpu, &exit_info, NULL) != HV_SUCCESS) return fail("hv_vcpu_create failed", NULL);
    hv_vcpu_set_trap_debug_exceptions(vcpu, false); /* BRK goes to the guest's own vectors */
    if (have_gic) /* GICv3 routes by affinity: this vCPU is Aff0 = 0 (bit 31 is RES1) */
        hv_vcpu_set_sys_reg(vcpu, HV_SYS_REG_MPIDR_EL1, 0x80000000ULL);
    hv_vcpu_set_reg(vcpu, HV_REG_PC, entry);
    hv_vcpu_set_reg(vcpu, HV_REG_CPSR, pstate);
    for (int n = 0; n < 31; n++)
        if (reg_set[n]) hv_vcpu_set_reg(vcpu, (hv_reg_t)(HV_REG_X0 + n), regs[n]);
    if (sp_set) hv_vcpu_set_sys_reg(vcpu, HV_SYS_REG_SP_EL1, sp);

    watched_vcpu = vcpu;
    pthread_t watcher;
    pthread_create(&watcher, NULL, watchdog, NULL);
    time_t deadline = time(NULL) + (time_t)timeout;
    size_t in_pos = 0, in_len = strlen(input);
    char tail[3] = {0, 0, 0};
    const char *stop = "limit";
    int status = 3;
    char fault[160] = "";
    uint64_t psci_calls = 0, sysreg_traps = 0;

    for (uint64_t exits = 0; exits < max_exits; exits++) {
        if (hv_vcpu_run(vcpu) != HV_SUCCESS) { stop = "fault"; snprintf(fault, sizeof fault, " hv_vcpu_run failed"); break; }
        uint64_t pc;
        hv_vcpu_get_reg(vcpu, HV_REG_PC, &pc);
        if (exit_info->reason == HV_EXIT_REASON_CANCELED) {
            if (at_wfe(pc)) { stop = "parked"; status = 0; break; }
            if (time(NULL) > deadline) { stop = "timeout"; break; }
            continue;
        }
        if (exit_info->reason == HV_EXIT_REASON_VTIMER_ACTIVATED) {
            hv_vcpu_set_vtimer_mask(vcpu, false); /* the in-kernel GIC delivers it */
            continue;
        }
        if (exit_info->reason != HV_EXIT_REASON_EXCEPTION) continue;
        uint64_t esr = exit_info->exception.syndrome, ipa = exit_info->exception.physical_address;
        uint32_t ec = (uint32_t)(esr >> 26);
        if (ec == 0x01) {
            if (!have_gic) { stop = "parked"; status = 0; break; } /* WFI/WFE */
            hv_vcpu_set_reg(vcpu, HV_REG_PC, pc + 4);
            continue;
        }
        if (ec == 0x18 && have_gic) {
            /* Trapped system register (the hypervisor traps debug registers such
             * as OSDLR_EL1/OSLAR_EL1): there is no debugger, so writes are
             * ignored and reads return 0. Only enabled for Linux-style guests. */
            unsigned rt = (esr >> 5) & 31, read = esr & 1;
            if (read && rt != 31) hv_vcpu_set_reg(vcpu, (hv_reg_t)(HV_REG_X0 + rt), 0);
            sysreg_traps++;
            hv_vcpu_set_reg(vcpu, HV_REG_PC, pc + 4);
            continue;
        }
        if (have_gic && (ec == 0x16 || ec == 0x17)) { /* PSCI via HVC or SMC */
            uint64_t fn = 0, arg = 0, ret = (uint64_t)-1; /* NOT_SUPPORTED */
            hv_vcpu_get_reg(vcpu, HV_REG_X0, &fn);
            hv_vcpu_get_reg(vcpu, HV_REG_X1, &arg);
            if (++psci_calls > 100000) { stop = "fault"; snprintf(fault, sizeof fault, " PSCI call storm"); break; }
            fn &= 0xffffffffULL;
            if (fn == 0x84000000) ret = 0x10000;                 /* PSCI_VERSION: 1.0 */
            else if (fn == 0x8400000a && ((arg & 0xffffffffULL) == 0x84000000 ||
                                          (arg & 0xffffffffULL) == 0x84000008 ||
                                          (arg & 0xffffffffULL) == 0x84000009)) ret = 0;
            else if (fn == 0x84000008) { stop = "poweroff"; status = 0; break; }
            else if (fn == 0x84000009) { stop = "reset"; status = 0; break; }
            hv_vcpu_set_reg(vcpu, HV_REG_X0, ret);
            if (ec == 0x17) hv_vcpu_set_reg(vcpu, HV_REG_PC, pc + 4); /* SMC traps before retiring */
            continue;
        }
        if (ec == 0x24 && have_uart && (esr & (1U << 24)) && ipa - uart < 0x1000) {
            unsigned srt = (esr >> 16) & 31, write = (esr >> 6) & 1;
            uint64_t off = ipa - uart, value = 0;
            if (write) {
                if (srt != 31) hv_vcpu_get_reg(vcpu, (hv_reg_t)(HV_REG_X0 + srt), &value);
                if (off == 0) {
                    putchar((int)(value & 0xff));
                    if ((value & 0xff) == '\n') fflush(stdout);
                    tail[0] = tail[1];
                    tail[1] = tail[2];
                    tail[2] = (char)value;
                }
            } else {
                int more = in_pos < in_len;
                if (off == 0x18) {
                    /* Idle: input consumed and the prompt "> " begins a line. */
                    if (!more && tail[0] == '\n' && tail[1] == '>' && tail[2] == ' ') { stop = "idle"; status = 0; break; }
                    value = more ? 0 : 0x10; /* FR.RXFE when empty */
                } else if (off == 0) {
                    value = more ? (unsigned char)input[in_pos++] : 0;
                }
                if (srt != 31) hv_vcpu_set_reg(vcpu, (hv_reg_t)(HV_REG_X0 + srt), value);
            }
            hv_vcpu_set_reg(vcpu, HV_REG_PC, pc + 4);
            continue;
        }
        stop = "fault";
        snprintf(fault, sizeof fault, " EC=0x%x ESR=0x%llx IPA=0x%llx PC=0x%llx", ec,
                 (unsigned long long)esr, (unsigned long long)ipa, (unsigned long long)pc);
        break;
    }
    running = 0;
    pthread_join(watcher, NULL);
    fflush(stdout);
    if (!strcmp(stop, "timeout") || !strcmp(stop, "fault")) {
        uint64_t pc = 0;
        hv_vcpu_get_reg(vcpu, HV_REG_PC, &pc);
        if (!fault[0]) snprintf(fault, sizeof fault, " PC=0x%llx", (unsigned long long)pc);
    }

    for (int i = 0; i < ndumps; i++) {
        uint8_t *src = host_ptr(dumps[i].addr, dumps[i].size);
        FILE *f = src ? fopen(dumps[i].file, "wb") : NULL;
        if (!f || fwrite(src, 1, dumps[i].size, f) != dumps[i].size) return fail("dump failed", dumps[i].file);
        fclose(f);
    }
    if (have_gic)
        fprintf(stderr, "[psci calls: %llu, trapped sysreg accesses: %llu]\n",
                (unsigned long long)psci_calls, (unsigned long long)sysreg_traps);
    fprintf(stderr, "[stop: %s%s]\n", stop, fault);
    return status;
}
