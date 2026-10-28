/* ssrs_shims.c - Win32/MSVCRT shims the RealSpeak/ScanSoft modules need that
 * the host_emu donor stubs out or lacks. Looked up before the donor table
 * (win32_register_import -> ssrs_shim_lookup). stdcall entries carry their
 * argument bytes, cdecl (MSVCRT) entries 0.
 */
#include "emu.h"
#include "modules.h"

#include <ctype.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <windows.h>

/* ---------------- helpers ---------------- */

static void gstr(uint32_t va, char *out, int n)
{
    int i = 0;
    for (; i < n - 1; i++) {
        out[i] = (char)rd8(va + i);
        if (!out[i]) break;
    }
    out[i < n ? i : n - 1] = 0;
}

static void gstr_out(uint32_t va, const char *s, uint32_t max)
{
    uint32_t i = 0;
    if (!max) return;
    for (; s[i] && i < max - 1; i++) wr8(va + i, (uint8_t)s[i]);
    wr8(va + i, 0);
}

static uint32_t g_lasterr = 0;

/* ---------------- handles ---------------- */

enum { H_NONE, H_FILE, H_SINK, H_MAP, H_FIND };
#define HBASE 0x00a00000u
#define NHANDLES 512

typedef struct {
    int kind;
    FILE *f;
    char path[300];
    HANDLE find;
} hslot_t;

static hslot_t g_h[NHANDLES];

static uint32_t h_new(int kind)
{
    for (int i = 1; i < NHANDLES; i++) {
        if (g_h[i].kind == H_NONE) {
            memset(&g_h[i], 0, sizeof g_h[i]);
            g_h[i].kind = kind;
            return HBASE + 4 * (uint32_t)i;
        }
    }
    return 0;
}

static hslot_t *h_get(uint32_t h)
{
    if (h < HBASE || h >= HBASE + 4 * NHANDLES || (h & 3)) return NULL;
    hslot_t *s = &g_h[(h - HBASE) / 4];
    return s->kind == H_NONE ? NULL : s;
}

/* ---------------- KERNEL32: modules ---------------- */

static void k_LoadLibraryA(void)
{
    char name[300];
    gstr(arg32(0), name, sizeof name);
    int i = mod_load(name, NULL);
    module_t *m = mod_by_index(i);
    if (!m) g_lasterr = 126;
    ret_set(m ? m->base : 0);
}

static void k_FreeLibrary(void)
{
    ret_set(1);
}

static void k_GetProcAddress(void)
{
    module_t *m = mod_by_handle(arg32(0));
    uint32_t p = arg32(1), r = 0;
    if (m) {
        if (p < 0x10000) {
            r = mod_export(m, NULL, p);
        } else {
            char n[128];
            gstr(p, n, sizeof n);
            r = mod_export(m, n, 0);
        }
    }
    if (!r) g_lasterr = 127;
    ret_set(r);
}

static void k_GetModuleHandleA(void)
{
    uint32_t p = arg32(0);
    if (!p) {
        ret_set(0x00400000u);
        return;
    }
    char n[300];
    gstr(p, n, sizeof n);
    module_t *m = mod_by_name(n);
    ret_set(m ? m->base : 0);
}

static void k_GetModuleFileNameA(void)
{
    uint32_t h = arg32(0), out = arg32(1), sz = arg32(2);
    module_t *m = h ? mod_by_handle(h) : NULL;
    const char *p = m ? m->path : "C:\\ssrs_oracle.exe";
    gstr_out(out, p, sz);
    uint32_t n = (uint32_t)strlen(p);
    ret_set(n < sz ? n : sz);
}

/* ---------------- KERNEL32: files ---------------- */

static void k_CreateFileA(void)
{
    char path[300];
    gstr(arg32(0), path, sizeof path);
    uint32_t access = arg32(1), disp = arg32(4);
    int writing = (access & 0x40000000u) || disp == 1 || disp == 2 || disp == 4 || disp == 5;
    if (writing) {
        uint32_t h = h_new(H_SINK);
        snprintf(h_get(h)->path, 300, "%s", path);
        ret_set(h);
        return;
    }
    FILE *f = fopen(path, "rb");
    if (!f) {
        g_lasterr = 2;
        ret_set(0xFFFFFFFFu);
        return;
    }
    uint32_t h = h_new(H_FILE);
    h_get(h)->f = f;
    snprintf(h_get(h)->path, 300, "%s", path);
    ret_set(h);
}

static void k_ReadFile(void)
{
    hslot_t *s = h_get(arg32(0));
    uint32_t buf = arg32(1), n = arg32(2), pread = arg32(3);
    uint32_t got = 0;
    if (s && s->kind == H_FILE && n) {
        uint8_t *tmp = (uint8_t *)malloc(n);
        got = (uint32_t)fread(tmp, 1, n, s->f);
        mem_write(buf, tmp, got);
        free(tmp);
    }
    if (pread) wr32(pread, got);
    ret_set(s ? 1 : 0);
}

static void k_WriteFile(void)
{
    uint32_t n = arg32(2), pw = arg32(3);
    if (pw) wr32(pw, n);
    ret_set(1);
}

static void k_SetFilePointer(void)
{
    hslot_t *s = h_get(arg32(0));
    int32_t lo = (int32_t)arg32(1);
    uint32_t phigh = arg32(2), method = arg32(3);
    if (!s || s->kind != H_FILE) {
        ret_set(0xFFFFFFFFu);
        return;
    }
    long long off = lo;
    if (phigh) off |= (long long)rd32(phigh) << 32;
    _fseeki64(s->f, off, method == 0 ? SEEK_SET : method == 1 ? SEEK_CUR : SEEK_END);
    long long pos = _ftelli64(s->f);
    if (phigh) wr32(phigh, (uint32_t)(pos >> 32));
    ret_set((uint32_t)pos);
}

static void k_GetFileSize(void)
{
    hslot_t *s = h_get(arg32(0));
    uint32_t phigh = arg32(1);
    if (!s || s->kind != H_FILE) {
        ret_set(0xFFFFFFFFu);
        return;
    }
    long long cur = _ftelli64(s->f);
    _fseeki64(s->f, 0, SEEK_END);
    long long sz = _ftelli64(s->f);
    _fseeki64(s->f, cur, SEEK_SET);
    if (phigh) wr32(phigh, (uint32_t)(sz >> 32));
    ret_set((uint32_t)sz);
}

static void k_GetFileAttributesA(void)
{
    char path[300];
    gstr(arg32(0), path, sizeof path);
    ret_set((uint32_t)GetFileAttributesA(path));
}

/* File mappings are read-only data here. Each distinct (file, offset, size)
 * view is copied once into the mapping arena and handed out again on repeat
 * requests; unmapping is a no-op. */
#define MAP_ARENA 0x62000000u
#define MAP_ARENA_SIZE 0x0d000000u

typedef struct {
    char path[300];
    uint32_t off, size, va;
} view_t;

static view_t g_views[256];
static int g_nviews = 0;
static uint32_t g_map_next = 0;

static void k_CreateFileMappingA(void)
{
    hslot_t *f = h_get(arg32(0));
    if (!f || f->kind != H_FILE) {
        ret_set(0);
        return;
    }
    uint32_t h = h_new(H_MAP);
    snprintf(h_get(h)->path, 300, "%s", f->path);
    ret_set(h);
}

static void k_MapViewOfFile(void)
{
    hslot_t *s = h_get(arg32(0));
    uint32_t off = arg32(3), size = arg32(4);
    if (!s || s->kind != H_MAP) {
        ret_set(0);
        return;
    }
    if (!g_map_next) {
        mem_map(MAP_ARENA, MAP_ARENA_SIZE, "filemap");
        g_map_next = MAP_ARENA;
    }
    for (int i = 0; i < g_nviews; i++) {
        if (g_views[i].off == off && g_views[i].size == size && !strcmp(g_views[i].path, s->path)) {
            ret_set(g_views[i].va);
            return;
        }
    }
    FILE *f = fopen(s->path, "rb");
    if (!f) {
        ret_set(0);
        return;
    }
    _fseeki64(f, 0, SEEK_END);
    long long fsz = _ftelli64(f);
    if (!size) size = (uint32_t)(fsz - off);
    uint32_t va = g_map_next;
    if (va + size > MAP_ARENA + MAP_ARENA_SIZE || g_nviews >= 256) {
        fprintf(stderr, "[ssrs] mapping arena full (%s +%u)\n", s->path, size);
        fclose(f);
        ret_set(0);
        return;
    }
    _fseeki64(f, off, SEEK_SET);
    size_t got = fread(mem_host(va), 1, size, f);
    (void)got;
    fclose(f);
    g_map_next = (va + size + 0xffff) & ~0xffffu;
    view_t *v = &g_views[g_nviews++];
    snprintf(v->path, sizeof v->path, "%s", s->path);
    v->off = off;
    v->size = size;
    v->va = va;
    ret_set(va);
}

static void k_UnmapViewOfFile(void)
{
    ret_set(1);
}

static void copy_find(uint32_t dst, const WIN32_FIND_DATAA *fd)
{
    mem_write(dst, fd, (uint32_t)sizeof *fd);
}

static void k_FindFirstFileA(void)
{
    char pat[300];
    gstr(arg32(0), pat, sizeof pat);
    WIN32_FIND_DATAA fd;
    HANDLE hf = FindFirstFileA(pat, &fd);
    if (hf == INVALID_HANDLE_VALUE) {
        g_lasterr = 2;
        ret_set(0xFFFFFFFFu);
        return;
    }
    uint32_t h = h_new(H_FIND);
    h_get(h)->find = hf;
    copy_find(arg32(1), &fd);
    ret_set(h);
}

static void k_FindNextFileA(void)
{
    hslot_t *s = h_get(arg32(0));
    WIN32_FIND_DATAA fd;
    if (!s || s->kind != H_FIND || !FindNextFileA(s->find, &fd)) {
        g_lasterr = 18;
        ret_set(0);
        return;
    }
    copy_find(arg32(1), &fd);
    ret_set(1);
}

static void k_FindClose(void)
{
    hslot_t *s = h_get(arg32(0));
    if (s && s->kind == H_FIND) {
        FindClose(s->find);
        s->kind = H_NONE;
    }
    ret_set(1);
}

static void k_CloseHandle(void)
{
    hslot_t *s = h_get(arg32(0));
    if (s) {
        if (s->kind == H_FILE && s->f) fclose(s->f);
        if (s->kind == H_FIND) FindClose(s->find);
        s->kind = H_NONE;
    }
    ret_set(1);
}

static void k_GetLastError(void)
{
    ret_set(g_lasterr);
}

static void k_SetLastError(void)
{
    g_lasterr = arg32(0);
}

/* ---------------- MSVCRT: stdio ---------------- */

#define NSTREAMS 64
static FILE *g_streams[NSTREAMS];
static uint32_t g_stream_va[NSTREAMS];

static int stream_of(uint32_t va)
{
    for (int i = 0; i < NSTREAMS; i++) {
        if (g_stream_va[i] == va && g_streams[i]) return i;
    }
    return -1;
}

static void c_fopen(void)
{
    char path[300], mode[16];
    gstr(arg32(0), path, sizeof path);
    gstr(arg32(1), mode, sizeof mode);
    FILE *f = strpbrk(mode, "wa+") ? fopen("NUL", "wb") : fopen(path, "rb");
    if (!f) {
        ret_set(0);
        return;
    }
    for (int i = 0; i < NSTREAMS; i++) {
        if (!g_streams[i]) {
            g_streams[i] = f;
            if (!g_stream_va[i]) g_stream_va[i] = guest_alloc(32, 1);
            ret_set(g_stream_va[i]);
            return;
        }
    }
    fclose(f);
    ret_set(0);
}

static void c_fclose(void)
{
    int i = stream_of(arg32(0));
    if (i >= 0) {
        fclose(g_streams[i]);
        g_streams[i] = NULL;
    }
    ret_set(0);
}

static void c_fread(void)
{
    uint32_t buf = arg32(0), sz = arg32(1), n = arg32(2);
    int i = stream_of(arg32(3));
    if (i < 0 || !sz || !n) {
        ret_set(0);
        return;
    }
    uint8_t *tmp = (uint8_t *)malloc((size_t)sz * n);
    size_t got = fread(tmp, sz, n, g_streams[i]);
    mem_write(buf, tmp, (uint32_t)(got * sz));
    free(tmp);
    ret_set((uint32_t)got);
}

static void c_fwrite(void)
{
    ret_set(arg32(2));
}

static void c_fseek(void)
{
    int i = stream_of(arg32(0));
    ret_set(i < 0 ? (uint32_t)-1 : (uint32_t)fseek(g_streams[i], (long)(int32_t)arg32(1), (int)arg32(2)));
}

static void c_ftell(void)
{
    int i = stream_of(arg32(0));
    ret_set(i < 0 ? (uint32_t)-1 : (uint32_t)ftell(g_streams[i]));
}

static void c_fflush(void)
{
    ret_set(0);
}

/* ---------------- MSVCRT: sprintf bridge ---------------- */

static uint32_t format_guest(uint32_t dst, uint32_t fmtva, uint32_t argp)
{
    char fmt[1024], out[4096];
    int o = 0;
    gstr(fmtva, fmt, sizeof fmt);
    for (const char *p = fmt; *p && o < (int)sizeof out - 1;) {
        if (*p != '%') {
            out[o++] = *p++;
            continue;
        }
        char spec[32];
        int k = 0;
        spec[k++] = *p++;
        if (*p == '%') {
            out[o++] = '%';
            p++;
            continue;
        }
        while (*p && strchr("-+ #0", *p) && k < 20) spec[k++] = *p++;
        if (*p == '*') {
            k += snprintf(spec + k, sizeof spec - k, "%d", (int32_t)rd32(argp));
            argp += 4;
            p++;
        } else {
            while (isdigit((unsigned char)*p) && k < 24) spec[k++] = *p++;
        }
        if (*p == '.') {
            spec[k++] = *p++;
            if (*p == '*') {
                k += snprintf(spec + k, sizeof spec - k, "%d", (int32_t)rd32(argp));
                argp += 4;
                p++;
            } else {
                while (isdigit((unsigned char)*p) && k < 28) spec[k++] = *p++;
            }
        }
        int is64 = 0;
        if (p[0] == 'I' && p[1] == '6' && p[2] == '4') {
            is64 = 1;
            p += 3;
        } else {
            while (*p == 'h' || *p == 'l' || *p == 'L') p++;
        }
        char conv = *p ? *p++ : 0;
        int room = (int)sizeof out - o;
        switch (conv) {
        case 'd': case 'i': case 'u': case 'x': case 'X': case 'o':
            if (is64) {
                uint64_t v = rd32(argp) | ((uint64_t)rd32(argp + 4) << 32);
                argp += 8;
                spec[k++] = 'l'; spec[k++] = 'l'; spec[k++] = conv; spec[k] = 0;
                o += snprintf(out + o, room, spec, v);
            } else {
                uint32_t v = rd32(argp);
                argp += 4;
                spec[k++] = conv; spec[k] = 0;
                if (conv == 'd' || conv == 'i') o += snprintf(out + o, room, spec, (int32_t)v);
                else o += snprintf(out + o, room, spec, v);
            }
            break;
        case 'c':
            spec[k++] = 'c'; spec[k] = 0;
            o += snprintf(out + o, room, spec, (int)(rd32(argp) & 0xff));
            argp += 4;
            break;
        case 's': {
            char s[1024];
            uint32_t sv = rd32(argp);
            argp += 4;
            if (sv) gstr(sv, s, sizeof s);
            else snprintf(s, sizeof s, "(null)");
            spec[k++] = 's'; spec[k] = 0;
            o += snprintf(out + o, room, spec, s);
            break;
        }
        case 'p':
            o += snprintf(out + o, room, "%08X", rd32(argp));
            argp += 4;
            break;
        case 'f': case 'e': case 'E': case 'g': case 'G': {
            uint64_t bits = rd32(argp) | ((uint64_t)rd32(argp + 4) << 32);
            double d;
            memcpy(&d, &bits, 8);
            argp += 8;
            spec[k++] = conv; spec[k] = 0;
            o += snprintf(out + o, room, spec, d);
            break;
        }
        case 'n':
            argp += 4;
            break;
        default:
            break;
        }
        if (o > (int)sizeof out - 1) o = (int)sizeof out - 1;
    }
    out[o] = 0;
    mem_write(dst, out, (uint32_t)o + 1);
    return (uint32_t)o;
}

static void c_sprintf(void)
{
    ret_set(format_guest(arg32(0), arg32(1), CPU.r[ESP] + 12));
}

static void c_vsprintf(void)
{
    ret_set(format_guest(arg32(0), arg32(1), arg32(2)));
}

static void c_snprintf(void)
{
    uint32_t n = arg32(1);
    char tmp[4096];
    uint32_t scratch = guest_alloc(4096, 0);
    uint32_t len = format_guest(scratch, arg32(2), CPU.r[ESP] + 16);
    mem_read(scratch, tmp, len + 1);
    guest_free(scratch);
    if (n) mem_write(arg32(0), tmp, len < n ? len + 1 : n);
    ret_set(len < n ? len : (uint32_t)-1);
}

/* ---------------- MSVCRT: misc ---------------- */

static double *fpu_st0(void)
{
    return &CPU.st[CPU.fpu_top & 7];
}

/* _ftol: ST(0) -> int64 in EDX:EAX, truncating, popped. */
static void c_ftol(void)
{
    double v = *fpu_st0();
    CPU.fpu_top = (CPU.fpu_top + 1) & 7;
    int64_t r;
    if (v != v || v >= 9223372036854775808.0 || v < -9223372036854775808.0) r = INT64_MIN;
    else r = (int64_t)v;
    CPU.r[EAX] = (uint32_t)r;
    CPU.r[EDX] = (uint32_t)((uint64_t)r >> 32);
}

static void c_isctype(void)
{
    int c = (int)arg32(0);
    uint32_t mask = arg32(1);
    uint32_t tab = mod_pctype_table();
    ret_set((c >= -1 && c <= 255) ? (rd16(tab + 2 * c) & mask) : 0);
}

static void c_tolower(void)
{
    int c = (int)arg32(0);
    ret_set((uint32_t)((c >= 'A' && c <= 'Z') ? c + 32 : c));
}

static void c_time(void)
{
    uint32_t p = arg32(0), t = 0x44697751u;
    if (p) wr32(p, t);
    ret_set(t);
}

static void c_ctime(void)
{
    static uint32_t buf = 0;
    if (!buf) buf = guest_alloc(32, 1);
    gstr_out(buf, "Tue May 16 06:38:41 2006\n", 32);
    ret_set(buf);
}

static void c_fail(void)
{
    ret_set((uint32_t)-1);
}

static void c_strncat(void)
{
    uint32_t d = arg32(0), s = arg32(1), n = arg32(2), e = d;
    while (rd8(e)) e++;
    uint32_t i = 0;
    for (; i < n; i++) {
        uint8_t c = rd8(s + i);
        if (!c) break;
        wr8(e + i, c);
    }
    wr8(e + i, 0);
    ret_set(d);
}

static void c_strpbrk(void)
{
    uint32_t s = arg32(0);
    char set[256];
    gstr(arg32(1), set, sizeof set);
    for (;; s++) {
        uint8_t c = rd8(s);
        if (!c) {
            ret_set(0);
            return;
        }
        if (strchr(set, c)) {
            ret_set(s);
            return;
        }
    }
}

static void c_strrchr(void)
{
    uint32_t s = arg32(0), r = 0;
    uint8_t ch = (uint8_t)arg32(1);
    for (;; s++) {
        uint8_t c = rd8(s);
        if (c == ch) r = s;
        if (!c) break;
    }
    ret_set(r);
}

static void c_strtoul(void)
{
    char buf[128];
    gstr(arg32(0), buf, sizeof buf);
    char *end;
    unsigned long v = strtoul(buf, &end, (int)arg32(2));
    if (arg32(1)) wr32(arg32(1), arg32(0) + (uint32_t)(end - buf));
    ret_set((uint32_t)v);
}

static uint32_t wlen(uint32_t s)
{
    uint32_t n = 0;
    while (rd16(s + 2 * n)) n++;
    return n;
}

static void c_wcslen(void)
{
    ret_set(wlen(arg32(0)));
}

static void c_wcscpy(void)
{
    uint32_t d = arg32(0), s = arg32(1), i = 0;
    for (;; i++) {
        uint16_t c = rd16(s + 2 * i);
        wr16(d + 2 * i, c);
        if (!c) break;
    }
    ret_set(d);
}

static void c_wcsncpy(void)
{
    uint32_t d = arg32(0), s = arg32(1), n = arg32(2), i = 0;
    for (; i < n; i++) {
        uint16_t c = rd16(s + 2 * i);
        wr16(d + 2 * i, c);
        if (!c) break;
    }
    for (; i < n; i++) wr16(d + 2 * i, 0);
    ret_set(d);
}

static void c_wcscmp(void)
{
    uint32_t a = arg32(0), b = arg32(1);
    for (;; a += 2, b += 2) {
        uint16_t x = rd16(a), y = rd16(b);
        if (x != y) {
            ret_set(x < y ? (uint32_t)-1 : 1);
            return;
        }
        if (!x) break;
    }
    ret_set(0);
}

static void c_wcschr(void)
{
    uint32_t s = arg32(0);
    uint16_t ch = (uint16_t)arg32(1);
    for (;; s += 2) {
        uint16_t c = rd16(s);
        if (c == ch) {
            ret_set(s);
            return;
        }
        if (!c) break;
    }
    ret_set(0);
}

/* ---------------- table ---------------- */

typedef struct {
    const char *name;
    shim_fn fn;
    int argb;
} sreg_t;

static const sreg_t SREG[] = {
    {"LoadLibraryA", k_LoadLibraryA, 4},
    {"LoadLibraryExA", k_LoadLibraryA, 12},
    {"FreeLibrary", k_FreeLibrary, 4},
    {"GetProcAddress", k_GetProcAddress, 8},
    {"GetModuleHandleA", k_GetModuleHandleA, 4},
    {"GetModuleFileNameA", k_GetModuleFileNameA, 12},
    {"CreateFileA", k_CreateFileA, 28},
    {"ReadFile", k_ReadFile, 20},
    {"WriteFile", k_WriteFile, 20},
    {"SetFilePointer", k_SetFilePointer, 16},
    {"GetFileSize", k_GetFileSize, 8},
    {"GetFileAttributesA", k_GetFileAttributesA, 4},
    {"CreateFileMappingA", k_CreateFileMappingA, 24},
    {"MapViewOfFile", k_MapViewOfFile, 20},
    {"UnmapViewOfFile", k_UnmapViewOfFile, 4},
    {"FindFirstFileA", k_FindFirstFileA, 8},
    {"FindNextFileA", k_FindNextFileA, 8},
    {"FindClose", k_FindClose, 4},
    {"CloseHandle", k_CloseHandle, 4},
    {"GetLastError", k_GetLastError, 0},
    {"SetLastError", k_SetLastError, 4},
    {"fopen", c_fopen, 0},
    {"fclose", c_fclose, 0},
    {"fread", c_fread, 0},
    {"fwrite", c_fwrite, 0},
    {"fseek", c_fseek, 0},
    {"ftell", c_ftell, 0},
    {"fflush", c_fflush, 0},
    {"sprintf", c_sprintf, 0},
    {"vsprintf", c_vsprintf, 0},
    {"_snprintf", c_snprintf, 0},
    {"_ftol", c_ftol, 0},
    {"_isctype", c_isctype, 0},
    {"tolower", c_tolower, 0},
    {"time", c_time, 0},
    {"ctime", c_ctime, 0},
    {"remove", c_fail, 0},
    {"rename", c_fail, 0},
    {"strncat", c_strncat, 0},
    {"strpbrk", c_strpbrk, 0},
    {"strrchr", c_strrchr, 0},
    {"strtoul", c_strtoul, 0},
    {"wcslen", c_wcslen, 0},
    {"wcscpy", c_wcscpy, 0},
    {"wcsncpy", c_wcsncpy, 0},
    {"wcscmp", c_wcscmp, 0},
    {"wcschr", c_wcschr, 0},
    {NULL, NULL, 0}
};

int ssrs_shim_lookup(const char *name, shim_fn *fn, int *argb)
{
    for (const sreg_t *r = SREG; r->name; r++) {
        if (!strcmp(r->name, name)) {
            *fn = r->fn;
            *argb = r->argb;
            return 1;
        }
    }
    return 0;
}
