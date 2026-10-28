/* opstep: run one instruction per case through the oracle's own cpu.c and
 * write the resulting state back. `xtask opgate` generates the cases and
 * compares against ss-rs-ng-xrt. Code at 0x10000000, data at 0x20000000. */
#include "../emu/emu.h"
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int EMU_VERBOSE = 0;
pe_info_t PE;

void emu_log(const char* fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
}

int win32_is_import_va(uint32_t va) { (void)va; return 0; }
void win32_dispatch(uint32_t va) { (void)va; }

#define CODE_VA 0x10000000u
#define DATA_VA 0x20000000u

#pragma pack(push, 1)
typedef struct {
    uint8_t  code[16];
    uint32_t r[8];
    uint32_t eflags;
    uint32_t top;
    uint16_t cw, sw;
    uint32_t faulted;
    uint32_t eip;
    uint32_t pad;
    uint64_t st[8];
    uint8_t  data[256];
} opcase_t;
#pragma pack(pop)

int main(int argc, char** argv)
{
    if (argc != 3) {
        fprintf(stderr, "usage: opstep cases.bin results.bin\n");
        return 2;
    }
    FILE* fi = fopen(argv[1], "rb");
    FILE* fo = fopen(argv[2], "wb");
    if (!fi || !fo) {
        fprintf(stderr, "opstep: cannot open %s or %s\n", argv[1], argv[2]);
        return 2;
    }
    mem_init();
    uint8_t* code = mem_map(CODE_VA, 0x1000, "code");
    uint8_t* data = mem_map(DATA_VA, 0x1000, "data");
    cpu_reset();
    opcase_t c;
    while (fread(&c, sizeof c, 1, fi) == 1) {
        memset(code, 0x90, 0x1000);
        memcpy(code, c.code, 16);
        memset(data, 0, 0x1000);
        memcpy(data, c.data, 256);
        memcpy(CPU.r, c.r, 32);
        CPU.eflags = c.eflags;
        CPU.fpu_top = (int)(c.top & 7);
        CPU.fpu_cw = c.cw;
        CPU.fpu_sw = c.sw;
        memcpy(CPU.st, c.st, 64);
        CPU.eip = CODE_VA;
        CPU.halted = 0;
        CPU.faulted = 0;
        cpu_run(1);
        memcpy(c.r, CPU.r, 32);
        c.eflags = CPU.eflags;
        c.top = (uint32_t)CPU.fpu_top & 7;
        c.cw = CPU.fpu_cw;
        c.sw = CPU.fpu_sw;
        memcpy(c.st, CPU.st, 64);
        c.faulted = (uint32_t)CPU.faulted;
        c.eip = CPU.eip;
        memcpy(c.data, data, 256);
        fwrite(&c, sizeof c, 1, fo);
    }
    fclose(fi);
    fclose(fo);
    return 0;
}
