/* acelp.c -- ACELP parameter decoders, transcribed from synth_155mrf22.dll. */
#include <string.h>

#include "acelp.h"

/* FUN_1000fd30 / FUN_10010140 build these on the stack every call. Track 0 is
 * an ABSOLUTE position; tracks 1..n-1 are RELATIVE increments accumulated
 * modulo 80. The 5-pulse variant uses a 16-entry track 0 with step 5; the
 * 4-pulse variant uses a 32-entry track 0 pairing each step-5 slot with its
 * successor, which is why its first index is 5 bits and the rest are 4. */
static const int TRK0_5[16] = {
    0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75
};

static const int TRK_REL[16] = {
    1, 6, 11, 16, 21, 26, 31, 36, 41, 46, 51, 56, 61, 66, 71, 76
};

static const int TRK0_4[32] = {
     0,  1,  5,  6, 10, 11, 15, 16, 20, 21, 25, 26, 30, 31, 35, 36,
    40, 41, 45, 46, 50, 51, 55, 56, 60, 61, 65, 66, 70, 71, 75, 76
};

static void put_pulse(int16_t *code, int pos, int positive)
{
    code[pos] = positive ? (int16_t)ACELP_PULSE_AMP
                         : (int16_t)(int32_t)0xffffe000;  /* 0xe000 */
}

int acelp_fixed_codebook(int16_t *code, int *pos_out, int npulse,
                         uint32_t sign_idx, uint32_t pos_idx)
{
    int pos, carry = 0;
    int k;

    memset(code, 0, sizeof(int16_t) * ACELP_SUBFRAME);

    if (npulse == 5) {
        pos = TRK0_5[pos_idx & 0xf];
        put_pulse(code, pos, (sign_idx & 1) == 1);
        pos_out[0] = pos;
        for (k = 1; k < 5; k++) {
            int delta = TRK_REL[(pos_idx >> (4 * k)) & 0xf];
            int sum = delta + pos;

            /* the LAST accumulation also yields the wrap count the engine
             * keeps as a return value (FUN_1000fd30) */
            if (k == 4) {
                carry = sum / ACELP_SUBFRAME;
            }
            pos = sum % ACELP_SUBFRAME;
            put_pulse(code, pos, ((sign_idx >> k) & 1) == 1);
            pos_out[k] = pos;
        }
        return carry;
    }

    /* npulse == 4: 5-bit track 0, then three 4-bit relative tracks */
    pos = TRK0_4[pos_idx & 0x1f];
    put_pulse(code, pos, (sign_idx & 1) == 1);
    pos_out[0] = pos;
    for (k = 1; k < 4; k++) {
        int delta = TRK_REL[(pos_idx >> (5 + 4 * (k - 1))) & 0xf];
        int sum = delta + pos;

        if (k == 3) {
            carry = sum / ACELP_SUBFRAME;
        }
        pos = sum % ACELP_SUBFRAME;
        put_pulse(code, pos, ((sign_idx >> k) & 1) == 1);
        pos_out[k] = pos;
    }
    return carry;
}

int acelp_pitch_lag(int subframe, int lpc_order, int idx, int prev_lag)
{
    /* FUN_10010550 tests the subframe index for oddness via
     * (n & 0x80000001) == 0, which is just "n is even" for non-negative n. */
    if ((subframe & 1) == 0) {
        if (lpc_order < 6) {
            return idx + 0x1e;
        }
        if (lpc_order < 12) {
            return idx + 0x28;
        }
        if (lpc_order < 18) {
            return idx + ACELP_LAG_BASE;
        }
        return prev_lag;                 /* order >= 18 leaves it unchanged */
    }
    /* odd subframe: a window around the previous lag whose width follows the
     * order. Every order this codec ships (15, 16, 17) uses 5 bits. */
    {
        int nbits = 5;

        if (lpc_order < 9) {
            nbits = 4;
        } else if (lpc_order > 11 && lpc_order < 15) {
            nbits = 3;
        }
        return prev_lag - (1 << (nbits - 1)) + 1 + idx;
    }
}

void acelp_lsf_vq(int16_t *out, int order, int stages, const int *idx,
                  const int *dim, const int16_t *cb)
{
    int base, k, i;

    memset(out, 0, sizeof(int16_t) * (size_t)order);

    base = dim[0] * order;
    for (k = 1; k < stages; k++) {
        const int16_t *v = cb + (size_t)idx[k] * order + base;

        for (i = 0; i < order; i++) {
            out[i] = (int16_t)(out[i] + v[i]);
        }
        base += dim[k] * order;
    }
    /* stage 0 is added at full scale after the refinements are scaled down */
    {
        const int16_t *v = cb + (size_t)idx[0] * order;

        for (i = 0; i < order; i++) {
            out[i] = (int16_t)((out[i] >> 2) + v[i]);
        }
    }
}
