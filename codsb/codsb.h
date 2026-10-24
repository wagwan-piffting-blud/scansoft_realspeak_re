/* codsb.h -- ScanSoft / RealSpeak `codsb` coded-speech-database reader.
 *
 * Handles BOTH installs; the decoder DLL `synth_155mrf22.dll` is byte-identical
 * between NextUp-ScanSoft (2004) and RealSpeakSolo v4 (2006), so one set of
 * tables covers both containers:
 *
 *   NextUp   speech/components/data/vf_tom_full_155mrf22_270_06.dat  49,531,617 B
 *   RS4      speech/components/data/vf_tom_full_155mrf22_270_06.dat  60,545,984 B
 *
 * The coded format is ACELP: 320 samples per frame in 4 subframes of 80,
 * LPC order 15/16/17, algebraic codebook with 4-5 pulses, 1-3 stages, and
 * log-domain MA gain prediction.
 *
 * Naming: <bitrate><family><rate>, e.g. 155mrf22 = 15.5 kbps at 22 kHz.
 * Confirmed arithmetically: 224 bits / (320 samples / 22050 Hz) = 15,435 bps.
 */
#ifndef CODSB_H
#define CODSB_H

#include <stddef.h>
#include <stdint.h>

#define CODSB_HDR_FIXED   0x90   /* fixed part of every SCANSOFT header */
#define CODSB_MAX_FIELDS  64
#define CODSB_MAX_BITS    392    /* == local_188[392] in FUN_1000ec90 */
#define CODSB_SUBFRAMES   4
#define CODSB_SUBFRAME    80
#define CODSB_FRAME       (CODSB_SUBFRAMES * CODSB_SUBFRAME)  /* 320 samples */

/* One bit-allocation variant, read from
 * (uint16_t *)(&DAT_10012034 + (order - 15) * 0x70) in synth_155mrf22.dll. */
typedef struct {
    int             order;      /* LPC order: 15, 16 or 17 */
    int             nfields;
    int             nbits;
    int             nbytes;     /* bytes a frame occupies, nbits rounded up */
    int             stages;     /* algebraic codebook stages, 1..3 */
    int             pulses;     /* pulses per stage */
    const uint16_t *width;      /* nfields entries */
} codsb_layout;

typedef struct {
    uint8_t        *data;
    size_t          size;
    char            type[9];    /* +0x0c, e.g. "codsb"   */
    char            coder[33];  /* +0x54, e.g. "155mrf22" */
    uint32_t        hdr_len;    /* +0x14, always 0x90     */
    uint32_t        toc_len;    /* +0x7c, header + TOC    */
    uint32_t        tag_num;    /* +0x80, 3 ASCII digits  */
    int             rate;       /* derived from `coder`   */
    const uint8_t  *body;       /* data + toc_len         */
    size_t          body_size;
    codsb_layout    layout;     /* selected variant       */
} codsb;

/* Field roles for the order-15 variant: 5 LSF, then 4 subframes of
 * [lag, pitch gain, pulse signs, pulse positions, fixed gain]. Lag is
 * 9 bits (absolute) in subframes 0 and 2, 5 bits (delta) in 1 and 3. */
typedef enum {
    CODSB_F_LSF = 0,
    CODSB_F_LAG,
    CODSB_F_PGAIN,
    CODSB_F_SIGN,
    CODSB_F_POS,
    CODSB_F_GAIN
} codsb_field_role;

const codsb_layout *codsb_layout_for(int order);
codsb_field_role    codsb_role_of(const codsb_layout *l, int field, int *subframe);
const char         *codsb_role_name(codsb_field_role r);

int    codsb_open(codsb *c, const char *path);
void   codsb_close(codsb *c);

/* Selects a bit-allocation variant. The LPC order is a runtime value in the
 * engine (`param_5[1]`), not stored in the container, so it must be chosen.
 * Returns 0 on success, -1 if `order` is not 15..17. */
int    codsb_select_order(codsb *c, int order);

size_t codsb_frame_count(const codsb *c);

/* Unpacks one frame into `out` (at least layout.nfields entries).
 * Bit order is LSB-first within each byte AND LSB-first within each field,
 * exactly as FUN_1000ec90 / FUN_1000ed30 do it. Returns 0 on success. */
int    codsb_unpack(const codsb *c, size_t frame, int32_t *out);

/* Unpacks directly from a caller-supplied frame buffer of layout.nbytes. */
void   codsb_unpack_bytes(const codsb_layout *l, const uint8_t *frame,
                          int32_t *out);

#endif /* CODSB_H */
