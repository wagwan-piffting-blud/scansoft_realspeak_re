/* rs_native: drive the vendor rssoloapi.dll in-process (32-bit) and write PCM.
 * Dev-time truth for the ss-rs-ng oracle; never part of the shipped engine.
 *
 *   rs_native.exe <speech_dir> <voice> <out.wav> "<text>" [product] [khz] [apiid=num ...]
 */
#include <windows.h>
#include <psapi.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef unsigned int u32;
typedef unsigned short u16;

typedef u32 (__cdecl *init_t)(const char *path, void *hcls[2]);
typedef u32 (__cdecl *uninit_t)(void *hcls, u32 magic);
typedef u32 (__cdecl *open_t)(void *hcls, u32 magic, const char *product, void *hinst[2], void *app);
typedef u32 (__cdecl *close_t)(void *hinst, u32 magic);
typedef u32 (__cdecl *setparams_t)(void *hinst, u32 magic, void *params, u16 count);
typedef u32 (__cdecl *setout_t)(void *hinst, u32 magic, void *dev[2]);
typedef u32 (__cdecl *settext_t)(void *hinst, u32 magic, u32 *text);
typedef u32 (__cdecl *process_t)(void *hinst, u32 magic, u32 zero);

#pragma pack(push, 1)
typedef struct {
    u32 id;
    union {
        u16 num;
        char str[128];
    } v;
} tts_param;
#pragma pack(pop)

static unsigned char *g_pcm;
static size_t g_pcm_len, g_pcm_cap;
static short g_buf[4096];
static int g_msgs[0x200];

static void pcm_append(const void *p, size_t n)
{
    if (g_pcm_len + n > g_pcm_cap) {
        g_pcm_cap = (g_pcm_len + n) * 2;
        g_pcm = realloc(g_pcm, g_pcm_cap);
    }
    memcpy(g_pcm + g_pcm_len, p, n);
    g_pcm_len += n;
}

static u32 __cdecl out_cb(void *hinst, u32 magic, void *ctx, u32 *msg, void *app)
{
    u32 *od = (u32 *)msg[2];
    (void)hinst; (void)magic; (void)ctx; (void)app;
    if (msg[0] < 0x200) {
        g_msgs[msg[0]]++;
    }
    if (msg[0] == 0x10 && od && od[2] && od[1]) {
        pcm_append((void *)od[2], od[1]);
    } else if (msg[0] == 8 && od) {
        od[1] = sizeof(g_buf);
        od[2] = (u32)g_buf;
        od[3] = 0;
        od[4] = 0;
    }
    return 0;
}

static void write_wav(const char *path, u32 rate)
{
    FILE *f = fopen(path, "wb");
    u32 v;
    u16 s;
    if (!f) {
        fprintf(stderr, "cannot write %s\n", path);
        exit(1);
    }
    fwrite("RIFF", 1, 4, f);
    v = 36 + (u32)g_pcm_len; fwrite(&v, 4, 1, f);
    fwrite("WAVEfmt ", 1, 8, f);
    v = 16; fwrite(&v, 4, 1, f);
    s = 1; fwrite(&s, 2, 1, f);
    s = 1; fwrite(&s, 2, 1, f);
    fwrite(&rate, 4, 1, f);
    v = rate * 2; fwrite(&v, 4, 1, f);
    s = 2; fwrite(&s, 2, 1, f);
    s = 16; fwrite(&s, 2, 1, f);
    fwrite("data", 1, 4, f);
    v = (u32)g_pcm_len; fwrite(&v, 4, 1, f);
    fwrite(g_pcm, 1, g_pcm_len, f);
    fclose(f);
}

static void list_modules(const char *tag)
{
    HMODULE mods[256];
    DWORD need = 0, i;
    char name[MAX_PATH];
    if (!EnumProcessModules(GetCurrentProcess(), mods, sizeof(mods), &need)) {
        return;
    }
    for (i = 0; i < need / sizeof(HMODULE); i++) {
        GetModuleFileNameA(mods[i], name, sizeof(name));
        if (strstr(name, "speech") || strstr(name, "ssrs_re") || strstr(name, "ScanSoft") || strstr(name, "RealSpeak")) {
            printf("%s %p %s\n", tag, (void *)mods[i], name);
        }
    }
}

#define LOAD(var, type, name) \
    var = (type)GetProcAddress(api, name); \
    if (!var) { fprintf(stderr, "missing export %s\n", name); return 1; }

int main(int argc, char **argv)
{
    const char *speech, *voice, *out, *text, *product;
    u32 khz;
    char common[MAX_PATH], apipath[MAX_PATH];
    HMODULE api;
    init_t p_init; uninit_t p_uninit; open_t p_open; close_t p_close;
    setparams_t p_setparams; setout_t p_setout; settext_t p_settext; process_t p_process;
    void *hcls[2] = {0, 0}, *hinst[2] = {0, 0}, *dev[2];
    tts_param params[16];
    u16 nparams;
    u32 textrec[3];
    u32 r;
    int i;

    if (argc < 5) {
        fprintf(stderr, "usage: rs_native <speech_dir> <voice> <out.wav> \"text\" [product] [khz]\n");
        return 2;
    }
    speech = argv[1];
    voice = argv[2];
    out = argv[3];
    text = argv[4];
    product = argc > 5 ? argv[5] : "RealSpeak Solo v4.0";
    khz = argc > 6 ? (u32)atoi(argv[6]) : 22;

    snprintf(common, sizeof(common), "%s\\components\\common", speech);
    snprintf(apipath, sizeof(apipath), "%s\\rssoloapi.dll", common);
    SetDllDirectoryA(common);
    api = LoadLibraryA(apipath);
    if (!api) {
        fprintf(stderr, "LoadLibrary %s failed: %lu\n", apipath, GetLastError());
        return 1;
    }
    LOAD(p_init, init_t, "ssft_ttsInitialize");
    LOAD(p_uninit, uninit_t, "ssft_ttsUnInitialize");
    LOAD(p_open, open_t, "ssft_ttsOpen");
    LOAD(p_close, close_t, "ssft_ttsClose");
    LOAD(p_setparams, setparams_t, "ssft_ttsSetParamList");
    LOAD(p_setout, setout_t, "ssft_ttsSetOutDevice");
    LOAD(p_settext, settext_t, "ssft_ttsSetText");
    LOAD(p_process, process_t, "ssft_ttsProcess");

    r = p_init(speech, hcls);
    printf("ssft_ttsInitialize -> %08x  hcls=%p/%u\n", r, hcls[0], (u32)(size_t)hcls[1]);
    if (r) return 1;
    r = p_open(hcls[0], (u32)(size_t)hcls[1], product, hinst, NULL);
    printf("ssft_ttsOpen(\"%s\") -> %08x  hinst=%p/%08x\n", product, r, hinst[0], (u32)(size_t)hinst[1]);
    if (r) return 1;

    memset(params, 0, sizeof(params));
    params[0].id = 0x40;
    strcpy(params[0].v.str, "American English");
    params[1].id = 0x80;
    strcpy(params[1].v.str, voice);
    params[2].id = 0x01;
    params[2].v.num = (u16)khz;
    nparams = 3;
    for (i = 7; i < argc && nparams < 16; i++) {
        char *eq = strchr(argv[i], '=');
        if (!eq) continue;
        params[nparams].id = (u32)strtoul(argv[i], NULL, 0);
        params[nparams].v.num = (u16)strtoul(eq + 1, NULL, 0);
        printf("param 0x%x = %u\n", params[nparams].id, params[nparams].v.num);
        nparams++;
    }
    r = p_setparams(hinst[0], (u32)(size_t)hinst[1], params, nparams);
    printf("ssft_ttsSetParamList -> %08x\n", r);
    if (r) return 1;

    dev[0] = NULL;
    dev[1] = (void *)out_cb;
    r = p_setout(hinst[0], (u32)(size_t)hinst[1], dev);
    printf("ssft_ttsSetOutDevice -> %08x\n", r);
    if (r) return 1;

    textrec[0] = 0;
    textrec[1] = (u32)strlen(text);
    textrec[2] = (u32)text;
    r = p_settext(hinst[0], (u32)(size_t)hinst[1], textrec);
    printf("ssft_ttsSetText -> %08x\n", r);
    if (r) return 1;

    r = p_process(hinst[0], (u32)(size_t)hinst[1], 0);
    printf("ssft_ttsProcess -> %08x  pcm=%u bytes\n", r, (u32)g_pcm_len);
    for (i = 0; i < 0x200; i++) {
        if (g_msgs[i]) printf("  out msg 0x%x x%d\n", i, g_msgs[i]);
    }
    list_modules("module");
    write_wav(out, khz == 22 ? 22050 : khz == 11 ? 11025 : khz * 1000);
    p_close(hinst[0], (u32)(size_t)hinst[1]);
    p_uninit(hcls[0], (u32)(size_t)hcls[1]);
    return 0;
}
