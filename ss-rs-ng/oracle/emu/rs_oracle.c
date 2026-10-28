/* rs_oracle: the vendor engine under the x86 interpreter, driven exactly as
 * oracle/native/rs_native.c drives it on the real CPU. Must produce the same
 * PCM byte for byte; it is the reference the Rust translation is gated on.
 *
 *   rs_oracle.exe <speech_dir> <voice> <out.wav> "<text>" [product] [khz] [apiid=num ...]
 */
#include "emu.h"
#include "modules.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned char *g_pcm;
static size_t g_pcm_len, g_pcm_cap;
static uint32_t g_buf_va;
static int g_msgs[0x200];

#define OUTBUF_BYTES 8192u

static void pcm_append_guest(uint32_t va, uint32_t n)
{
    if (g_pcm_len + n > g_pcm_cap) {
        g_pcm_cap = (g_pcm_len + n) * 2;
        g_pcm = realloc(g_pcm, g_pcm_cap);
    }
    mem_read(va, g_pcm + g_pcm_len, n);
    g_pcm_len += n;
}

/* cdecl cb(hinst, magic, ctx, msg*, appdata) */
static void out_cb(void)
{
    uint32_t msg = arg32(3);
    uint32_t type = rd32(msg), od = rd32(msg + 8);
    if (type < 0x200) g_msgs[type]++;
    if (type == 0x10 && od && rd32(od + 8) && rd32(od + 4)) {
        pcm_append_guest(rd32(od + 8), rd32(od + 4));
    } else if (type == 8 && od) {
        wr32(od + 4, OUTBUF_BYTES);
        wr32(od + 8, g_buf_va);
        wr32(od + 12, 0);
        wr32(od + 16, 0);
    }
    ret_set(0);
}

static uint32_t gstrdup(const char *s)
{
    uint32_t n = (uint32_t)strlen(s) + 1, va = guest_alloc(n, 1);
    mem_write(va, s, n);
    return va;
}

static uint32_t call(const char *exp, const uint32_t *a, int n)
{
    uint32_t fn = mod_export(mod_by_name("rssoloapi.dll"), exp, 0);
    if (!fn) {
        fprintf(stderr, "missing export %s\n", exp);
        exit(1);
    }
    uint32_t r = call_nested_args(fn, a, n);
    if (CPU.faulted) {
        fprintf(stderr, "%s FAULTED: %s at %08x (eip %08x)\n", exp, CPU.fault_msg ? CPU.fault_msg : "?",
                CPU.fault_addr, CPU.eip);
        exit(1);
    }
    return r;
}

static void write_wav(const char *path, uint32_t rate)
{
    FILE *f = fopen(path, "wb");
    uint32_t v;
    uint16_t s;
    if (!f) {
        fprintf(stderr, "cannot write %s\n", path);
        exit(1);
    }
    fwrite("RIFF", 1, 4, f);
    v = 36 + (uint32_t)g_pcm_len; fwrite(&v, 4, 1, f);
    fwrite("WAVEfmt ", 1, 8, f);
    v = 16; fwrite(&v, 4, 1, f);
    s = 1; fwrite(&s, 2, 1, f);
    s = 1; fwrite(&s, 2, 1, f);
    fwrite(&rate, 4, 1, f);
    v = rate * 2; fwrite(&v, 4, 1, f);
    s = 2; fwrite(&s, 2, 1, f);
    s = 16; fwrite(&s, 2, 1, f);
    fwrite("data", 1, 4, f);
    v = (uint32_t)g_pcm_len; fwrite(&v, 4, 1, f);
    fwrite(g_pcm, 1, g_pcm_len, f);
    fclose(f);
}

int main(int argc, char **argv)
{
    if (argc < 5) {
        fprintf(stderr, "usage: rs_oracle <speech_dir> <voice> <out.wav> \"text\" [product] [khz] [apiid=num ...]\n");
        return 2;
    }
    const char *speech = argv[1], *voice = argv[2], *out = argv[3], *text = argv[4];
    const char *product = argc > 5 ? argv[5] : "RealSpeak Solo v4.0";
    uint32_t khz = argc > 6 ? (uint32_t)atoi(argv[6]) : 22;
    char common[300], api[300];
    snprintf(common, sizeof common, "%s\\components\\common", speech);
    snprintf(api, sizeof api, "%s\\rssoloapi.dll", common);

    mem_init();
    cpu_reset();
    win32_reset();
    win32_init();
    mod_env_init();
    mod_add_search_dir(common);
    if (mod_load(api, NULL) < 0) {
        fprintf(stderr, "cannot load %s\n", api);
        return 1;
    }

    uint32_t hcls = guest_alloc(8, 1), hinst = guest_alloc(8, 1);
    uint32_t a[5];
    a[0] = gstrdup(speech);
    a[1] = hcls;
    uint32_t r = call("ssft_ttsInitialize", a, 2);
    printf("ssft_ttsInitialize -> %08x  hcls=%08x/%u\n", r, rd32(hcls), rd32(hcls + 4));
    if (r) return 1;

    a[0] = rd32(hcls);
    a[1] = rd32(hcls + 4);
    a[2] = gstrdup(product);
    a[3] = hinst;
    a[4] = 0;
    r = call("ssft_ttsOpen", a, 5);
    printf("ssft_ttsOpen(\"%s\") -> %08x  hinst=%08x/%08x\n", product, r, rd32(hinst), rd32(hinst + 4));
    if (r) return 1;
    uint32_t h0 = rd32(hinst), h1 = rd32(hinst + 4);

    uint32_t params = guest_alloc(16 * 0x84, 1);
    uint32_t np = 0;
    wr32(params, 0x40);
    mem_write(params + 4, "American English", 17);
    wr32(params + 0x84, 0x80);
    mem_write(params + 0x84 + 4, voice, (uint32_t)strlen(voice) + 1);
    wr32(params + 2 * 0x84, 0x01);
    wr16(params + 2 * 0x84 + 4, (uint16_t)khz);
    np = 3;
    for (int i = 7; i < argc && np < 16; i++) {
        char *eq = strchr(argv[i], '=');
        if (!eq) continue;
        wr32(params + np * 0x84, (uint32_t)strtoul(argv[i], NULL, 0));
        wr16(params + np * 0x84 + 4, (uint16_t)strtoul(eq + 1, NULL, 0));
        np++;
    }
    a[0] = h0; a[1] = h1; a[2] = params; a[3] = np;
    r = call("ssft_ttsSetParamList", a, 4);
    printf("ssft_ttsSetParamList -> %08x\n", r);
    if (r) return 1;

    g_buf_va = guest_alloc(OUTBUF_BYTES, 1);
    uint32_t dev = guest_alloc(8, 1);
    wr32(dev, 0);
    wr32(dev + 4, host_register_callback(out_cb, 0, "out_cb"));
    a[0] = h0; a[1] = h1; a[2] = dev;
    r = call("ssft_ttsSetOutDevice", a, 3);
    printf("ssft_ttsSetOutDevice -> %08x\n", r);
    if (r) return 1;

    uint32_t trec = guest_alloc(12, 1), tlen = (uint32_t)strlen(text);
    uint32_t tva = guest_alloc(tlen + 1, 1);
    mem_write(tva, text, tlen + 1);
    wr32(trec, 0);
    wr32(trec + 4, tlen);
    wr32(trec + 8, tva);
    a[0] = h0; a[1] = h1; a[2] = trec;
    r = call("ssft_ttsSetText", a, 3);
    printf("ssft_ttsSetText -> %08x\n", r);
    if (r) return 1;

    a[0] = h0; a[1] = h1; a[2] = 0;
    r = call("ssft_ttsProcess", a, 3);
    printf("ssft_ttsProcess -> %08x  pcm=%u bytes\n", r, (unsigned)g_pcm_len);
    for (int i = 0; i < 0x200; i++) {
        if (g_msgs[i]) printf("  out msg 0x%x x%d\n", i, g_msgs[i]);
    }
    for (int i = 0; i < mod_count(); i++) {
        module_t *m = mod_by_index(i);
        printf("module %08x %s\n", m->base, m->path);
    }
    write_wav(out, khz == 22 ? 22050 : khz == 11 ? 11025 : khz * 1000);
    return 0;
}
