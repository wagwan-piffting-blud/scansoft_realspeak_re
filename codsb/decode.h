/* decode.h -- full ACELP frame synthesis for the ScanSoft `codsb` codec. */
#ifndef CODSB_DECODE_H
#define CODSB_DECODE_H

#include <stdint.h>

#include "codsb.h"

#define CODSB_ORDER    16      /* hardcoded 0x10 at every call site */
#define CODSB_EXCLEN   2048    /* > max lag (565) + subframe */
#define CODSB_LSF_MAX  0x6488  /* 25736 == pi, the divisor in FUN_1000f480 */

/* The LSF codebook lives in the container's TOC, not the DLL: 5 stages x 256
 * entries x 16 coefficients of int16, after a 72-byte TOC header. Stage 0 is an
 * ABSOLUTE vector (0..24068, ascending); stages 1-4 are zero-mean corrections
 * with monotonically shrinking spread. */
#define CODSB_LSF_STAGES  5
#define CODSB_LSF_ENTRIES 256
#define CODSB_TOC_HDR     72

typedef struct {
    double  exc[CODSB_EXCLEN];
    int     exc_pos;
    double  syn[CODSB_ORDER];
    int     lsf_prev[CODSB_ORDER];
    int16_t gp[4];                 /* MA gain-predictor history, FUN_1000fbb0 */
    int16_t pg_prev;               /* previous subframe's pitch gain, Q14 (state+0x5e8) */
    int16_t hp_x1;                 /* FUN_1000f310 high-pass memories (state+0x5f0/0x5f6) */
    int16_t hp_y1;
    int     prev_lag;
    int     primed;
} codsb_dec;

void codsb_dec_init(codsb_dec *d);

/* Decodes one frame of CODSB_FRAME (320) samples.
 * `f` is the unpacked field array, `lsfcb` the codebook base (TOC + 72).
 * Returns 0. */
int  codsb_dec_frame(codsb_dec *d, const codsb_layout *l, const int32_t *f,
                     const int16_t *lsfcb, int16_t *out);

/* Convenience: the LSF codebook pointer for an opened container. */
const int16_t *codsb_lsf_codebook(const codsb *c);

#endif /* CODSB_DECODE_H */
