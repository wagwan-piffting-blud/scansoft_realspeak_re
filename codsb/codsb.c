/* codsb.c -- container parse and bitstream unpack.
 *
 * Everything here is derived from synth_155mrf22.dll and verified against the
 * real files; nothing is guessed. See RESUME-ARCH.md for the derivation.
 *
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "codsb.h"

/* Bit-allocation tables, &DAT_10012034 + (order - 15) * 0x70.
 *
 * Each is 5 LSF fields followed by 4 subframes. Two facts make these
 * self-checking: the order-17 total is exactly 392 bits, which is the size of
 * `local_188[392]` that FUN_1000ec90 allocates for the exploded frame; and
 * every variant has 5 + 4*k fields, matching the 4-subframe loop in
 * FUN_1000e190. */
static const uint16_t W15[25] = {
    8, 8, 8, 8, 8,
    9, 8, 5, 20, 6,
    5, 8, 5, 20, 6,
    9, 8, 5, 20, 6,
    5, 8, 5, 20, 6
};

static const uint16_t W16[33] = {
    8, 8, 8, 8, 8,
    9, 8, 4, 17, 6, 4, 17,
    5, 8, 4, 17, 6, 4, 17,
    9, 8, 4, 17, 6, 4, 17,
    5, 8, 4, 17, 6, 4, 17
};

static const uint16_t W17[41] = {
    8, 8, 8, 8, 8,
    9, 8, 5, 20, 6, 4, 17, 4, 17,
    5, 8, 5, 20, 6, 4, 17, 4, 17,
    9, 8, 5, 20, 6, 4, 17, 4, 17,
    5, 8, 5, 20, 6, 4, 17, 4, 17
};

static const codsb_layout LAYOUTS[3] = {
    { 15, 25, 224, 28, 1, 5, W15 },
    { 16, 33, 292, 37, 2, 4, W16 },
    { 17, 41, 392, 49, 3, 5, W17 }
};

const codsb_layout *codsb_layout_for(int order)
{
    int i;

    for (i = 0; i < 3; i++) {
        if (LAYOUTS[i].order == order) {
            return &LAYOUTS[i];
        }
    }
    return NULL;
}

codsb_field_role codsb_role_of(const codsb_layout *l, int field, int *subframe)
{
    int per, k;

    if (subframe) {
        *subframe = -1;
    }
    if (field < 5) {
        return CODSB_F_LSF;
    }
    per = (l->nfields - 5) / CODSB_SUBFRAMES;
    if (subframe) {
        *subframe = (field - 5) / per;
    }
    /* slot order within a subframe: lag, pgain, sign, pos, gain, then
     * (sign, pos) per extra codebook stage. It is NOT a parity rule -- sign
     * lands on k = 2, 5, 7 and pos on k = 3, 6, 8 for the order-17 layout. */
    k = (field - 5) % per;
    if (k == 0) {
        return CODSB_F_LAG;
    }
    if (k == 1) {
        return CODSB_F_PGAIN;
    }
    if (k == 2) {
        return CODSB_F_SIGN;
    }
    if (k == 3) {
        return CODSB_F_POS;
    }
    if (k == 4) {
        return CODSB_F_GAIN;
    }
    return ((k - 5) % 2 == 0) ? CODSB_F_SIGN : CODSB_F_POS;
}

const char *codsb_role_name(codsb_field_role r)
{
    switch (r) {
    case CODSB_F_LSF:   return "lsf";
    case CODSB_F_LAG:   return "lag";
    case CODSB_F_PGAIN: return "pgain";
    case CODSB_F_SIGN:  return "sign";
    case CODSB_F_POS:   return "pos";
    case CODSB_F_GAIN:  return "gain";
    }
    return "?";
}

static uint32_t rd32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8)
         | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

/* Trailing spaces are the padding convention in this header, per FUN_10005cb0
 * which converts them to NUL. */
static void trim_field(const uint8_t *src, size_t n, char *dst)
{
    size_t i;

    memcpy(dst, src, n);
    dst[n] = '\0';
    for (i = n; i > 0; i--) {
        if (dst[i - 1] != ' ' && dst[i - 1] != '\0') {
            break;
        }
        dst[i - 1] = '\0';
    }
}

/* The coder tag ends in the sample rate in kHz: 155mrf22, 112mrf16, 83swf11.
 * `mrf` and `swf` are coder families; only the trailing number is the rate. */
static int rate_from_coder(const char *coder)
{
    size_t n = strlen(coder);
    int khz;

    if (n < 2) {
        return 0;
    }
    khz = (coder[n - 2] - '0') * 10 + (coder[n - 1] - '0');
    switch (khz) {
    case 22: return 22050;
    case 16: return 16000;
    case 11: return 11025;
    case  8: return 8000;
    }
    return 0;
}

int codsb_open(codsb *c, const char *path)
{
    FILE *f;
    long n;

    memset(c, 0, sizeof(*c));
    f = fopen(path, "rb");
    if (!f) {
        fprintf(stderr, "codsb: cannot open %s\n", path);
        return -1;
    }
    if (fseek(f, 0, SEEK_END) != 0) {
        fclose(f);
        return -1;
    }
    n = ftell(f);
    if (n < CODSB_HDR_FIXED) {
        fprintf(stderr, "codsb: %s is too small (%ld B)\n", path, n);
        fclose(f);
        return -1;
    }
    rewind(f);
    c->data = (uint8_t *)malloc((size_t)n);
    if (!c->data) {
        fclose(f);
        return -1;
    }
    if (fread(c->data, 1, (size_t)n, f) != (size_t)n) {
        fprintf(stderr, "codsb: short read on %s\n", path);
        fclose(f);
        free(c->data);
        c->data = NULL;
        return -1;
    }
    fclose(f);
    c->size = (size_t)n;

    /* FUN_100032e0 checks exactly these two before touching anything else. */
    if (rd32(c->data) != 0xFEFFu || memcmp(c->data + 4, "SCANSOFT", 8) != 0) {
        fprintf(stderr, "codsb: %s is not a SCANSOFT container\n", path);
        free(c->data);
        c->data = NULL;
        return -1;
    }
    trim_field(c->data + 0x0c, 8, c->type);
    trim_field(c->data + 0x54, 32, c->coder);
    c->hdr_len = rd32(c->data + 0x14);
    c->toc_len = rd32(c->data + 0x7c);
    c->tag_num = (uint32_t)atoi((const char *)c->data + 0x80);
    c->rate = rate_from_coder(c->coder);

    if (c->toc_len > c->size) {
        fprintf(stderr, "codsb: TOC length %u exceeds file size %zu\n",
                c->toc_len, c->size);
        free(c->data);
        c->data = NULL;
        return -1;
    }
    c->body = c->data + c->toc_len;
    c->body_size = c->size - c->toc_len;
    /* Order 17 (27.0 kbps). Three independent lines agree: it is the only
     * variant that tiles BOTH containers exactly; its pitch lags are 2.2x more
     * coherent than the random-alignment null in both; and 392 bits at
     * 22050/320 frames per second is 27,011 bps, matching the `270` in
     * vf_tom_full_155mrf22_270_06.dat. `155mrf22` names the DECODER FAMILY,
     * not the data rate -- one DLL serves 15.5 / 20.1 / 27.0 kbps. */
    c->layout = LAYOUTS[2];
    return 0;
}

void codsb_close(codsb *c)
{
    free(c->data);
    c->data = NULL;
    c->body = NULL;
    c->size = c->body_size = 0;
}

int codsb_select_order(codsb *c, int order)
{
    const codsb_layout *l = codsb_layout_for(order);

    if (!l) {
        return -1;
    }
    c->layout = *l;
    return 0;
}

size_t codsb_frame_count(const codsb *c)
{
    return c->body_size / (size_t)c->layout.nbytes;
}

void codsb_unpack_bytes(const codsb_layout *l, const uint8_t *frame,
                        int32_t *out)
{
    uint8_t bits[CODSB_MAX_BITS];
    int i, j, p, nb;

    /* FUN_1000ec90: explode to one bit per byte, LSB-first within each byte. */
    nb = l->nbits;
    for (i = 0; i < nb; i++) {
        bits[i] = (uint8_t)((frame[i >> 3] >> (i & 7)) & 1);
    }
    /* FUN_1000ed30: each field accumulates bit[j] << j, so LSB-first again. */
    p = 0;
    for (i = 0; i < l->nfields; i++) {
        int32_t v = 0;

        for (j = 0; j < (int)l->width[i]; j++) {
            v += (int32_t)bits[p + j] << j;
        }
        out[i] = v;
        p += (int)l->width[i];
    }
}

int codsb_unpack(const codsb *c, size_t frame, int32_t *out)
{
    size_t off = frame * (size_t)c->layout.nbytes;

    if (off + (size_t)c->layout.nbytes > c->body_size) {
        return -1;
    }
    codsb_unpack_bytes(&c->layout, c->body + off, out);
    return 0;
}
