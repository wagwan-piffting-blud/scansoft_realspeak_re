/* modules.c - multi-image PE32 loader for the ss-rs-ng oracle.
 *
 * Replaces host_emu's single-image loader.c. Every vendor module is linked at
 * 0x10000000, so each gets its own 64 KB-aligned base, in load order, and is
 * relocated. Imports from another vendor module bind to its export; imports
 * from system DLLs go to the shim table (win32_register_import); data imports
 * (_pctype, __mb_cur_max, _iob) get the address of a guest variable. DllMain
 * runs after the module's dependencies, through a nested guest call, so a
 * guest LoadLibraryA in the middle of a run is safe.
 */
#include "emu.h"
#include "modules.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

pe_info_t PE;

static module_t g_mods[MAX_MODULES];
static int g_nmods = 0;
static uint32_t g_next_base = MODULE_BASE0;
static char g_search[8][300];
static int g_nsearch = 0;

static const char *SYSTEM_DLLS[] = {
    "kernel32.dll", "msvcrt.dll", "user32.dll", "advapi32.dll", "ole32.dll",
    "oleaut32.dll", "winmm.dll", "version.dll", "gdi32.dll", "shell32.dll", NULL
};

static uint32_t g_var_pctype, g_var_mb_cur_max, g_var_iob;

static void lower(char *s)
{
    for (; *s; s++) {
        *s = (char)tolower((unsigned char)*s);
    }
}

static const char *base_name(const char *path)
{
    const char *a = strrchr(path, '\\'), *b = strrchr(path, '/');
    const char *p = a > b ? a : b;
    return p ? p + 1 : path;
}

static int is_system_dll(const char *name)
{
    char n[64];
    snprintf(n, sizeof n, "%s", name);
    lower(n);
    for (int i = 0; SYSTEM_DLLS[i]; i++) {
        if (!strcmp(n, SYSTEM_DLLS[i])) {
            return 1;
        }
    }
    return 0;
}

void mod_add_search_dir(const char *dir)
{
    if (g_nsearch < 8) {
        snprintf(g_search[g_nsearch++], sizeof g_search[0], "%s", dir);
    }
}

module_t *mod_by_index(int i)
{
    return (i >= 0 && i < g_nmods) ? &g_mods[i] : NULL;
}

int mod_count(void)
{
    return g_nmods;
}

module_t *mod_by_handle(uint32_t h)
{
    for (int i = 0; i < g_nmods; i++) {
        if (g_mods[i].base == h) {
            return &g_mods[i];
        }
    }
    return NULL;
}

module_t *mod_by_name(const char *name)
{
    char n[64];
    snprintf(n, sizeof n, "%s", base_name(name));
    lower(n);
    for (int i = 0; i < g_nmods; i++) {
        if (!strcmp(g_mods[i].name, n)) {
            return &g_mods[i];
        }
    }
    return NULL;
}

module_t *mod_by_va(uint32_t va)
{
    for (int i = 0; i < g_nmods; i++) {
        if (va >= g_mods[i].base && va < g_mods[i].base + g_mods[i].size) {
            return &g_mods[i];
        }
    }
    return NULL;
}

static void guest_str(uint32_t va, char *out, int n)
{
    int i = 0;
    for (; i < n - 1; i++) {
        out[i] = (char)rd8(va + i);
        if (!out[i]) {
            break;
        }
    }
    out[i < n ? i : n - 1] = 0;
}

uint32_t mod_export(module_t *m, const char *name, uint32_t ordinal)
{
    if (!m || !m->export_rva) {
        return 0;
    }
    uint32_t e = m->base + m->export_rva;
    uint32_t ord_base = rd32(e + 0x10);
    uint32_t nfuncs = rd32(e + 0x14);
    uint32_t nnames = rd32(e + 0x18);
    uint32_t funcs = m->base + rd32(e + 0x1c);
    uint32_t names = m->base + rd32(e + 0x20);
    uint32_t ords = m->base + rd32(e + 0x24);
    uint32_t idx = 0xffffffffu;
    if (name) {
        char buf[128];
        for (uint32_t i = 0; i < nnames; i++) {
            guest_str(m->base + rd32(names + i * 4), buf, sizeof buf);
            if (!strcmp(buf, name)) {
                idx = rd16(ords + i * 2);
                break;
            }
        }
    } else if (ordinal >= ord_base) {
        idx = ordinal - ord_base;
    }
    if (idx >= nfuncs) {
        return 0;
    }
    uint32_t rva = rd32(funcs + idx * 4);
    return rva ? m->base + rva : 0;
}

/* MSVCRT "C" locale _ctype table: _pctype points at entry 0, entry -1 (EOF) is
 * the word before it. Bits: 1 upper, 2 lower, 4 digit, 8 space, 0x10 punct,
 * 0x20 control, 0x40 blank, 0x80 hex, 0x100 alpha. */
static void build_data_vars(void)
{
    uint32_t tab = guest_alloc(2 * 257 + 16, 1);
    for (int c = 0; c < 256; c++) {
        uint16_t f = 0;
        if (c < 0x80) {
            if (isupper(c)) f |= 0x101;
            if (islower(c)) f |= 0x102;
            if (isdigit(c)) f |= 0x4;
            if (c == ' ' || (c >= 9 && c <= 13)) f |= 0x8;
            if (ispunct(c)) f |= 0x10;
            if (c < 0x20 || c == 0x7f) f |= 0x20;
            if (c == ' ') f |= 0x40;
            if (isxdigit(c)) f |= 0x80;
        }
        if (c == 9) f |= 0x40;
        wr16(tab + 2 + 2 * c, f);
    }
    g_var_pctype = guest_alloc(4, 1);
    wr32(g_var_pctype, tab + 2);
    g_var_mb_cur_max = guest_alloc(4, 1);
    wr32(g_var_mb_cur_max, 1);
    g_var_iob = guest_alloc(0x60, 1);
}

uint32_t mod_pctype_table(void)
{
    return rd32(g_var_pctype);
}

static uint32_t data_import(const char *name)
{
    if (!strcmp(name, "_pctype")) return g_var_pctype;
    if (!strcmp(name, "__mb_cur_max")) return g_var_mb_cur_max;
    if (!strcmp(name, "_iob")) return g_var_iob;
    return 0;
}

static int find_file(const char *name, const char *importer_dir, char *out, int n)
{
    FILE *f;
    if (strchr(name, '\\') || strchr(name, '/')) {
        if ((f = fopen(name, "rb"))) {
            fclose(f);
            snprintf(out, n, "%s", name);
            return 1;
        }
        name = base_name(name);
    }
    if (importer_dir) {
        snprintf(out, n, "%s\\%s", importer_dir, name);
        if ((f = fopen(out, "rb"))) {
            fclose(f);
            return 1;
        }
    }
    for (int i = 0; i < g_nsearch; i++) {
        snprintf(out, n, "%s\\%s", g_search[i], name);
        if ((f = fopen(out, "rb"))) {
            fclose(f);
            return 1;
        }
    }
    return 0;
}

uint32_t call_nested_args(uint32_t fn, const uint32_t *args, int n)
{
    cpu_t save = CPU;
    if (!CPU.r[ESP]) {
        CPU.r[ESP] = STACK_ESP0;
    }
    CPU.r[ESP] -= 64;
    for (int i = n - 1; i >= 0; i--) {
        cpu_push32(args[i]);
    }
    cpu_push32(RET_SENTINEL);
    CPU.eip = fn;
    CPU.halted = 0;
    CPU.faulted = 0;
    cpu_run(4000000000ULL);
    uint32_t eax = CPU.r[EAX];
    int faulted = CPU.faulted;
    uint32_t feip = CPU.eip;
    CPU = save;
    if (faulted) {
        fprintf(stderr, "[nested] call %08x FAULTED at eip=%08x\n", fn, feip);
        CPU.faulted = 1;
    }
    return eax;
}

static int map_image(module_t *m, const uint8_t *file, uint32_t len)
{
#define F16(o) ((uint32_t)file[o] | ((uint32_t)file[(o) + 1] << 8))
#define F32(o) (F16(o) | (F16((o) + 2) << 16))
    if (len < 0x40 || F16(0) != 0x5A4D) return -1;
    uint32_t lfanew = F32(0x3c);
    if (F32(lfanew) != 0x00004550) return -1;
    uint32_t coff = lfanew + 4;
    uint32_t nsec = F16(coff + 2), optsz = F16(coff + 16), opt = coff + 20;
    if (F16(opt) != 0x10b) return -1;
    uint32_t pref = F32(opt + 28);
    m->size = F32(opt + 56);
    m->entry_rva = F32(opt + 16);
    m->export_rva = F32(opt + 96);
    m->import_rva = F32(opt + 96 + 8);
    uint32_t reloc_rva = F32(opt + 96 + 5 * 8), reloc_sz = F32(opt + 96 + 5 * 8 + 4);
    m->base = g_next_base;
    g_next_base = (g_next_base + m->size + 0xffff) & ~0xffffu;
    uint8_t *img = mem_map(m->base, m->size, m->name);
    memcpy(img, file, F32(opt + 60));
    uint32_t sectab = opt + optsz;
    for (uint32_t i = 0; i < nsec; i++) {
        uint32_t s = sectab + i * 40;
        uint32_t vsize = F32(s + 8), vaddr = F32(s + 12), rawsz = F32(s + 16), rawptr = F32(s + 20);
        uint32_t n = rawsz < vsize ? rawsz : vsize;
        if (vsize == 0) n = rawsz;
        if (rawptr + n <= len && vaddr + n <= m->size) memcpy(img + vaddr, file + rawptr, n);
    }
    int32_t delta = (int32_t)(m->base - pref);
    if (delta && reloc_rva && reloc_sz) {
        uint32_t p = reloc_rva, end = reloc_rva + reloc_sz;
        while (p < end) {
            uint32_t page = rd32(m->base + p), blk = rd32(m->base + p + 4);
            if (blk < 8) break;
            for (uint32_t k = 0; k < (blk - 8) / 2; k++) {
                uint16_t e = rd16(m->base + p + 8 + k * 2);
                if ((e >> 12) == 3) {
                    uint32_t a = m->base + page + (e & 0xfff);
                    wr32(a, rd32(a) + (uint32_t)delta);
                }
            }
            p += blk;
        }
    }
    wr32(m->base + lfanew + 52, m->base);
    return 0;
#undef F16
#undef F32
}

static int bind_imports(module_t *m)
{
    if (!m->import_rva) return 0;
    for (uint32_t d = m->base + m->import_rva;; d += 20) {
        uint32_t oft = rd32(d), name_rva = rd32(d + 12), ft = rd32(d + 16);
        if (!oft && !name_rva && !ft) break;
        char dll[128];
        guest_str(m->base + name_rva, dll, sizeof dll);
        module_t *dep = NULL;
        if (!is_system_dll(dll)) {
            int di = mod_load(dll, m->dir);
            if (di < 0) {
                fprintf(stderr, "[modules] %s: cannot load dependency %s\n", m->name, dll);
                return -1;
            }
            dep = &g_mods[di];
        }
        uint32_t thunks = m->base + (oft ? oft : ft);
        for (uint32_t t = 0;; t += 4) {
            uint32_t ent = rd32(thunks + t);
            if (!ent) break;
            char fname[128];
            uint32_t ord = 0;
            if (ent & 0x80000000u) {
                ord = ent & 0xffff;
                snprintf(fname, sizeof fname, "#%u", ord);
            } else {
                guest_str(m->base + ent + 2, fname, sizeof fname);
            }
            uint32_t target;
            if (dep) {
                target = mod_export(dep, ord ? NULL : fname, ord);
                if (!target) {
                    fprintf(stderr, "[modules] %s: %s!%s not exported\n", m->name, dll, fname);
                    return -1;
                }
            } else if (!(target = data_import(fname))) {
                target = (uint32_t)win32_register_import(dll, fname);
            }
            wr32(m->base + ft + t, target);
        }
    }
    return 0;
}

int mod_load(const char *name, const char *importer_dir)
{
    module_t *have = mod_by_name(name);
    if (have) {
        have->refs++;
        return (int)(have - g_mods);
    }
    if (g_nmods >= MAX_MODULES) {
        fprintf(stderr, "[modules] too many modules\n");
        return -1;
    }
    char path[300];
    if (!find_file(name, importer_dir, path, sizeof path)) {
        fprintf(stderr, "[modules] not found: %s\n", name);
        return -1;
    }
    FILE *f = fopen(path, "rb");
    fseek(f, 0, SEEK_END);
    long len = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *buf = (uint8_t *)malloc((size_t)len);
    if (fread(buf, 1, (size_t)len, f) != (size_t)len) {
        fclose(f);
        free(buf);
        return -1;
    }
    fclose(f);
    int idx = g_nmods++;
    module_t *m = &g_mods[idx];
    memset(m, 0, sizeof *m);
    snprintf(m->path, sizeof m->path, "%s", path);
    snprintf(m->name, sizeof m->name, "%s", base_name(path));
    lower(m->name);
    snprintf(m->dir, sizeof m->dir, "%s", path);
    char *slash = strrchr(m->dir, '\\');
    if (slash) *slash = 0;
    m->refs = 1;
    if (map_image(m, buf, (uint32_t)len) != 0) {
        fprintf(stderr, "[modules] bad PE: %s\n", path);
        free(buf);
        return -1;
    }
    free(buf);
    if (getenv("SSRS_MODLOG")) {
        fprintf(stderr, "[modules] %-22s base %08x size %06x  %s\n", m->name, m->base, m->size, m->path);
    }
    if (bind_imports(m) != 0) return -1;
    if (m->entry_rva) {
        uint32_t a[3] = {m->base, 1, 0};
        uint32_t ok = call_nested_args(m->base + m->entry_rva, a, 3);
        m->inited = 1;
        if (!ok) fprintf(stderr, "[modules] DllMain(%s) returned FALSE\n", m->name);
    }
    if (idx == 0) {
        PE.image_base = m->base;
        PE.size_of_image = m->size;
        PE.entry_rva = m->entry_rva;
        PE.export_rva = m->export_rva;
    }
    return idx;
}

void mod_env_init(void)
{
    mem_map(STACK_TOP - STACK_SIZE, STACK_SIZE, "stack");
    mem_map(IMP_BASE, MAX_IMPORTS * IMP_STRIDE, "imports");
    mem_map(TEB_BASE, 0x1000, "teb");
    mem_map(PEB_BASE, 0x1000, "peb");
    wr32(TEB_BASE + 0x00, 0xFFFFFFFF);
    wr32(TEB_BASE + 0x04, STACK_TOP);
    wr32(TEB_BASE + 0x08, STACK_TOP - STACK_SIZE);
    wr32(TEB_BASE + 0x18, TEB_BASE);
    wr32(TEB_BASE + 0x20, 0x1000);
    wr32(TEB_BASE + 0x24, 0x2000);
    wr32(TEB_BASE + 0x30, PEB_BASE);
    wr32(PEB_BASE + 0x08, MODULE_BASE0);
    CPU.seg_fs_base = TEB_BASE;
    CPU.r[ESP] = STACK_ESP0;
    build_data_vars();
}

uint32_t pe_get_export(const char *name)
{
    return mod_export(mod_by_index(0), name, 0);
}
