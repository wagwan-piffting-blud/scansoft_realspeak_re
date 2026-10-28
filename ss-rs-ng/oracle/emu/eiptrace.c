/* Unique (previous EIP, EIP) pairs over a run, for checking the translation's
 * coverage (tools/xlate_cover.py). Only in rs_oracle_trace.exe
 * (build.bat trace); SSRS_EIPTRACE=<file> names the output, little-endian
 * u32 pairs. */
#ifdef SSRS_EIPTRACE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#define BITS 24
#define CAP (1u << BITS)

static uint64_t* g_tab;
static uint32_t g_prev;
static uint32_t g_n;
static const char* g_path;

static void dump(void)
{
    FILE* f = fopen(g_path, "wb");
    if (!f) return;
    for (uint32_t k = 0; k < CAP; k++) {
        uint64_t v = g_tab[k];
        if (!v) continue;
        uint32_t p[2] = {(uint32_t)(v >> 32), (uint32_t)v};
        fwrite(p, 4, 2, f);
    }
    fclose(f);
}

void ssrs_eip_hit(uint32_t eip)
{
    if (!g_tab) {
        g_path = getenv("SSRS_EIPTRACE");
        if (!g_path) g_path = "eiptrace.bin";
        g_tab = (uint64_t*)calloc(CAP, sizeof(uint64_t));
        atexit(dump);
    }
    uint64_t key = ((uint64_t)g_prev << 32) | eip;
    g_prev = eip;
    if (!key) return;
    uint32_t h = (uint32_t)((key * 0x9E3779B97F4A7C15ull) >> (64 - BITS));
    for (;;) {
        uint64_t v = g_tab[h];
        if (v == key) return;
        if (!v) {
            if (g_n < CAP - CAP / 8) {
                g_tab[h] = key;
                g_n++;
            }
            return;
        }
        h = (h + 1) & (CAP - 1);
    }
}
#endif
