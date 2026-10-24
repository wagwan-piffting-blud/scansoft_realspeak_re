/* decode.c -- ACELP synthesis, transcribed from synth_155mrf22.dll.
 *
 * FUN_1000e190 drives the whole frame; the stages below follow it in order.
 * Fixed-point detail is reproduced in floating point: the structure, tables and
 * indices are exact, the arithmetic is not bit-exact. That is deliberate --
 * intelligible audio first, bit-exactness only if it is ever needed.
 *
 * ⚠ APPROXIMATED, and audible if wrong:
 *   - the fixed-codebook gain predictor. FUN_1000fa60 does it in Q-format
 *     through the log/exp tables; here it is the standard G.729 MA predictor in
 *     dB, which is what those tables implement. The MA coefficients are
 *     verbatim from the DLL and are exactly G.729's {0.68,0.58,0.34,0.19}.
 *   - LSF minimum separation (FUN_1000f7c0) uses a fixed floor.
 *
 * Pitch sharpening and the FUN_1000f310 output high-pass are integer-exact
 * transcriptions (2026-10-23). Remaining departures are listed in
 * ssrs_re\README_TECHNICAL.md §8.
 */
#include <math.h>
#include <string.h>

#include "acelp.h"
#include "decode.h"
#include "tables.h"

#define GAMMA_BWE  (0x7ef9 / 32768.0)   /* FUN_1000f6d0 bandwidth expansion */
#define LSF_MIN_GAP 40                  /* stability floor, in LSF units */
#define PG_PREV_INIT 0x0ccc             /* 0.2 in Q14, FUN_1000e070 */
#define HP_POLE      0x7eb8             /* 0.98999, FUN_1000f310 */

void codsb_dec_init(codsb_dec *d)
{
    memset(d, 0, sizeof(*d));
    d->exc_pos = CODSB_EXCLEN / 2;
    d->prev_lag = ACELP_LAG_BASE;
    d->pg_prev = PG_PREV_INIT;
}

static int16_t sat16(int v)
{
    if (v > 32767) {
        return 32767;
    }
    if (v < -32768) {
        return -32768;
    }
    return (int16_t)v;
}

/* FUN_1000e190, the `lag < 0x50` branch: recursive in place, so a pulse echoes
 * every `lag` samples to the end of the subframe. The added term saturates; the
 * sum wraps as int16, as in the DLL. */
static void pitch_sharpen(int16_t *code, int lag, int g_q14)
{
    int n;

    for (n = lag; n < ACELP_SUBFRAME; n++) {
        int t = sat16(((int)code[n - lag] * g_q14 * 2 + 0x4000) >> 15);

        code[n] = (int16_t)(code[n] + t);
    }
}

/* FUN_1000f310: y = sat(sat(x - x1) + round(y1 * 0x7eb8 / 32768)). */
static int16_t dc_block(codsb_dec *d, int16_t x)
{
    int16_t y = sat16(sat16((int)x - (int)d->hp_x1)
                      + (int16_t)(((int)d->hp_y1 * HP_POLE * 2 + 0x8000) >> 16));

    d->hp_x1 = x;
    d->hp_y1 = y;
    return y;
}

const int16_t *codsb_lsf_codebook(const codsb *c)
{
    return (const int16_t *)(c->data + CODSB_HDR_FIXED + CODSB_TOC_HDR);
}

/* FUN_1000f9a0: stage 0 absolute, stages 1..n-1 summed then >> 2. */
static void lsf_vq(const int32_t *idx, const int16_t *cb, int *lsf)
{
    int acc[CODSB_ORDER];
    int k, i, base;

    for (i = 0; i < CODSB_ORDER; i++) {
        acc[i] = 0;
    }
    base = CODSB_LSF_ENTRIES * CODSB_ORDER;
    for (k = 1; k < CODSB_LSF_STAGES; k++) {
        const int16_t *v = cb + base + idx[k] * CODSB_ORDER;

        for (i = 0; i < CODSB_ORDER; i++) {
            acc[i] += v[i];
        }
        base += CODSB_LSF_ENTRIES * CODSB_ORDER;
    }
    for (i = 0; i < CODSB_ORDER; i++) {
        lsf[i] = (acc[i] >> 2) + cb[idx[0] * CODSB_ORDER + i];
    }
}

/* FUN_1000f730 + FUN_1000f7c0: ascending order, then a separation floor. */
static void lsf_stabilise(int *lsf)
{
    int i, j, t;

    for (i = 0; i < CODSB_ORDER - 1; i++) {
        for (j = 0; j < CODSB_ORDER - 1 - i; j++) {
            if (lsf[j + 1] < lsf[j]) {
                t = lsf[j];
                lsf[j] = lsf[j + 1];
                lsf[j + 1] = t;
            }
        }
    }
    if (lsf[0] < LSF_MIN_GAP) {
        lsf[0] = LSF_MIN_GAP;
    }
    for (i = 1; i < CODSB_ORDER; i++) {
        if (lsf[i] < lsf[i - 1] + LSF_MIN_GAP) {
            lsf[i] = lsf[i - 1] + LSF_MIN_GAP;
        }
    }
    if (lsf[CODSB_ORDER - 1] > CODSB_LSF_MAX - LSF_MIN_GAP) {
        lsf[CODSB_ORDER - 1] = CODSB_LSF_MAX - LSF_MIN_GAP;
    }
}

/* FUN_1000f480: index the 8192-entry cosine table by lsf * 0x4000 / 0x6488 >> 1. */
static double lsf_to_lsp(int lsf)
{
    int v = (int)(((long long)lsf * 0x4000) / CODSB_LSF_MAX) >> 1;

    if (v < 0 || v > 0x1fff) {
        v = 0;
    }
    return CODSB_COS[v] / 32768.0;
}

/* Standard LSP -> LPC polynomial expansion, the float form of FUN_1000f4e0. */
static void lsp_poly(const double *lsp, double *f, int n)
{
    int i, j;

    /* `lsp` is already the even- or odd-indexed half, so the stride is 1 here.
     * Indexing it as 2*i-2 (the interleaved form) reads the wrong coefficients
     * and produces a near-DC filter -- that was the 2 Hz zero-crossing bug. */
    f[0] = 1.0;
    f[1] = -2.0 * lsp[0];
    for (i = 2; i <= n; i++) {
        double b = -2.0 * lsp[i - 1];

        f[i] = b * f[i - 1] + 2.0 * f[i - 2];
        for (j = i - 1; j >= 2; j--) {
            f[j] += b * f[j - 1] + f[j - 2];
        }
        f[1] += b;
    }
}

static void lsp_to_lpc(const double *lsp, double *a)
{
    double f1[CODSB_ORDER / 2 + 1], f2[CODSB_ORDER / 2 + 1];
    double odd[CODSB_ORDER / 2], even[CODSB_ORDER / 2];
    int n = CODSB_ORDER / 2;
    int i;

    for (i = 0; i < n; i++) {
        even[i] = lsp[2 * i];
        odd[i] = lsp[2 * i + 1];
    }
    lsp_poly(even, f1, n);
    lsp_poly(odd, f2, n);
    for (i = n; i >= 1; i--) {
        f1[i] += f1[i - 1];
        f2[i] -= f2[i - 1];
    }
    a[0] = 1.0;
    for (i = 1; i <= n; i++) {
        a[i] = 0.5 * (f1[i] + f2[i]);
        a[CODSB_ORDER + 1 - i] = 0.5 * (f1[i] - f2[i]);
    }
}

/* FUN_1000de90 -- interpolated table lookup, low 16 bits are what callers use. */
static int q_log(int v, const int16_t *tbl, int nent)
{
    short sv = (short)v;
    int idx = sv >> 5;
    int s1, dd;
    short s2;

    if (idx == 0x3ff) {
        return 0;
    }
    if (idx < 0) {
        idx = 0;
    }
    if (idx > nent - 2) {
        idx = nent - 2;
    }
    s1 = tbl[idx];
    dd = (int)tbl[idx + 1] - s1;
    s2 = (short)((unsigned int)(((int)sv - idx * 0x20) * dd * 2 + 0x8000) >> 16);
    return (short)(s1 + (s2 >> 8));
}

/* FUN_1000dee0 -- the same shape but an 11-bit index and unsigned entries. */
static int q_exp(int t, const int16_t *tbl, int nent)
{
    unsigned u2 = ((unsigned)t >> 5) & 0x7ff;
    int u1, dd, r;

    if ((int)u2 > nent - 2) {
        u2 = (unsigned)(nent - 2);
    }
    u1 = (int)(unsigned short)tbl[u2];
    dd = (int)(unsigned short)tbl[u2 + 1] - u1;
    r = (int)(((((unsigned)t & 0xffff) - u2 * 0x20) * (unsigned)dd + 0x10) >> 5);
    return (short)(r + u1);
}

/* FUN_1000fa60 -- predicted gain from code energy and the MA history. */
static int predict_gain(const codsb_dec *d, const int16_t *code, int n)
{
    int acc = 0x51eb, dot = 0, i, scale, v, lg, val, t;

    for (i = 0; i < n; i++) {
        acc += ((int)code[i] * (int)code[i]) >> 5;
    }
    scale = (short)(((unsigned)n & 0xff) << 8);
    if (scale == 0) {
        return 0;
    }
    v = (acc / scale) >> 1;
    lg = q_log(v, CODSB_LOG, 1024);
    for (i = 0; i < 4; i++) {
        dot += (int)d->gp[i] * (int)CODSB_GAIN_MA[i];
    }
    val = ((dot + 0x100) >> 9) + (int)(short)(0x2400 - lg) * 0x80;
    t = (val / 0x28) >> 1;
    return (short)(q_exp(t, CODSB_EXP, 2048) << 1);
}

/* FUN_1000fbf0 -- correction table times the predicted gain, with a shift that
 * steps at idx 59/61/63, then FUN_1000fbb0 updates the MA history. */
static int fixed_gain(codsb_dec *d, const int16_t *code, int n, int idx)
{
    int pred = predict_gain(d, code, n);
    int t = (int)(unsigned short)CODSB_FGAIN[idx];
    int res, off, i;

    if (idx < 0x3b) {
        res = (t * pred * 2 + 0x2000) >> 14;
        off = 0;
    } else if (idx < 0x3d) {
        res = (t * pred * 2 + 0x1000) >> 13;
        off = 0x302;
    } else if (idx < 0x3f) {
        res = (t * pred * 2 + 0x800) >> 12;
        off = 0x605;
    } else {
        res = (t * pred * 2 + 0x200) >> 10;
        off = 0xc0a;
    }
    for (i = 3; i > 0; i--) {
        d->gp[i] = d->gp[i - 1];
    }
    d->gp[0] = (short)((q_log(t, CODSB_LOG, 1024) + off) * 4);
    return (short)res;
}

/* Pulses stay at the DLL's +/-0x2000 (Q13): predict_gain reads the raw energy,
 * and the excitation applies gain*code*2 >> 16 exactly as FUN_1000e190 does. */
static void add_pulses(int16_t *code, int n, int npulse, uint32_t sign,
                       uint32_t pos)
{
    int16_t tmp[ACELP_SUBFRAME];
    int p[8], i;

    acelp_fixed_codebook(tmp, p, npulse, sign, pos);
    for (i = 0; i < n; i++) {
        code[i] = (int16_t)(code[i] + tmp[i]);
    }
}

int codsb_dec_frame(codsb_dec *d, const codsb_layout *l, const int32_t *f,
                    const int16_t *lsfcb, int16_t *out)
{
    int lsf[CODSB_ORDER], lsf_s[CODSB_ORDER];
    double lsp[CODSB_ORDER], a[CODSB_ORDER + 1];
    int16_t code[ACELP_SUBFRAME];
    int per = (l->nfields - 5) / CODSB_SUBFRAMES;
    int s, i, k;

    lsf_vq(f, lsfcb, lsf);
    lsf_stabilise(lsf);
    if (!d->primed) {
        memcpy(d->lsf_prev, lsf, sizeof(lsf));
        d->primed = 1;
    }

    for (s = 0; s < CODSB_SUBFRAMES; s++) {
        const int32_t *sf = f + 5 + s * per;
        int lag, np;
        double pg, w;
        int fg;
        int base = d->exc_pos;

        /* FUN_100067e0 interpolates for subframes 0..2 and FUN_10006780 copies
         * for subframe 3 (the `param_7 < 0x1e0` branch, 240 samples). */
        w = (s < 3) ? CODSB_LSP_INTERP[s] / 32768.0 : 1.0;
        for (i = 0; i < CODSB_ORDER; i++) {
            lsf_s[i] = (int)(d->lsf_prev[i] * (1.0 - w) + lsf[i] * w + 0.5);
            lsp[i] = lsf_to_lsp(lsf_s[i]);
        }
        lsp_to_lpc(lsp, a);
        for (i = 1; i <= CODSB_ORDER; i++) {
            a[i] *= pow(GAMMA_BWE, (double)i);
        }

        lag = acelp_pitch_lag(s, l->order, (int)sf[0], d->prev_lag);
        if (lag < 20) {
            lag = 20;
        }
        if (lag > base) {
            lag = base;
        }
        d->prev_lag = lag;

        /* adaptive codebook: repeat the excitation at the pitch period */
        for (i = 0; i < ACELP_SUBFRAME; i++) {
            d->exc[base + i] = d->exc[base + i - lag];
        }
        pg = CODSB_PGAIN[sf[1] & 0xff] / 16384.0;
        for (i = 0; i < ACELP_SUBFRAME; i++) {
            d->exc[base + i] *= pg;
        }

        /* fixed codebook: stage 1 has 5 pulses, stages 2 and 3 have 4.
         * FUN_1000e190 scales stage 2 by 0xaaaa/65536 and stage 3 by 1/2. */
        np = (l->order == 16) ? 4 : 5;
        memset(code, 0, sizeof(code));
        add_pulses(code, ACELP_SUBFRAME, np, (uint32_t)sf[2], (uint32_t)sf[3]);
        if (lag < ACELP_SUBFRAME) {
            pitch_sharpen(code, lag, d->pg_prev);
        }
        fg = fixed_gain(d, code, ACELP_SUBFRAME, (int)(sf[4] & 0x3f));
        /* exc += (gain * code * 2) >> 16, i.e. gain*code/32768 */
        for (i = 0; i < ACELP_SUBFRAME; i++) {
            d->exc[base + i] += (double)fg * code[i] / 32768.0;
        }
        for (k = 1; k < l->stages; k++) {
            double scale = (k == 1) ? (0xaaaa / 65536.0) : 0.5;

            memset(code, 0, sizeof(code));
            add_pulses(code, ACELP_SUBFRAME, 4,
                       (uint32_t)sf[3 + 2 * k], (uint32_t)sf[4 + 2 * k]);
            if (lag < ACELP_SUBFRAME) {
                pitch_sharpen(code, lag, d->pg_prev);
            }
            for (i = 0; i < ACELP_SUBFRAME; i++) {
                d->exc[base + i] += (double)fg * scale * code[i] / 32768.0;
            }
        }

        /* FUN_1000f390: y[n] = x[n] - sum a[k] y[n-k] */
        for (i = 0; i < ACELP_SUBFRAME; i++) {
            double acc = d->exc[base + i];
            double y;

            for (k = 1; k <= CODSB_ORDER; k++) {
                acc -= a[k] * d->syn[k - 1];
            }
            y = acc;
            for (k = CODSB_ORDER - 1; k > 0; k--) {
                d->syn[k] = d->syn[k - 1];
            }
            d->syn[0] = y;
            if (y > 32767.0) {
                y = 32767.0;
            }
            if (y < -32768.0) {
                y = -32768.0;
            }
            out[s * ACELP_SUBFRAME + i] = dc_block(d, (int16_t)y);
        }
        d->pg_prev = CODSB_PGAIN[sf[1] & 0xff];

        d->exc_pos += ACELP_SUBFRAME;
        if (d->exc_pos + ACELP_SUBFRAME >= CODSB_EXCLEN) {
            memmove(d->exc, d->exc + d->exc_pos - 1024,
                    sizeof(double) * 1024);
            d->exc_pos = 1024;
        }
    }
    memcpy(d->lsf_prev, lsf, sizeof(lsf));
    return 0;
}
