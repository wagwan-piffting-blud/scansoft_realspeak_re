/* acelp.h -- the ACELP parameter decoders of the ScanSoft `codsb` codec.
 *
 * Everything declared here is fully derived from synth_155mrf22.dll and each
 * piece independently corroborates the bit-allocation table in codsb.c:
 *
 *   FUN_1000fd30   5-pulse algebraic codebook, consumes 5x4 = 20 position bits
 *                  and 5 sign bits  -> matches the order-15/17 rows exactly
 *   FUN_10010140   4-pulse variant, consumes 5+4+4+4 = 17 position bits and
 *                  4 sign bits      -> matches the order-16 row exactly
 *   FUN_10010550   pitch lag: idx9 + 54 on even subframes, lag_prev - 15 + idx5
 *                  on odd ones      -> matches the 9,5,9,5 lag widths
 *   FUN_1000f9a0   multi-stage LSF VQ over `stages` indices
 *
 * The synthesis chain (LSP->LPC, filter, postfilter) is NOT here yet; those
 * routines are identified but not transcribed.
 */
#ifndef ACELP_H
#define ACELP_H

#include <stdint.h>

#define ACELP_SUBFRAME   80
#define ACELP_PULSE_AMP  0x2000   /* Q13; negative pulses store 0xe000 */
#define ACELP_LAG_BASE   54       /* 0x36, for LPC order in [12, 18) */
#define ACELP_LAG_DELTA  15       /* odd subframes: prev - 15 + idx5 */

/* Builds the fixed-codebook excitation for one subframe.
 *
 * `code` is zeroed then given `npulse` pulses of +/-ACELP_PULSE_AMP.
 * Positions accumulate modulo ACELP_SUBFRAME from per-track tables; the first
 * track is absolute, the rest are relative increments.
 *
 *   npulse == 5 : sign_idx is 5 bits, pos_idx is 20 bits (4 per track)
 *   npulse == 4 : sign_idx is 4 bits, pos_idx is 17 bits (5 then 4,4,4)
 *
 * `pos_out` receives the npulse absolute positions. Returns the wrap count of
 * the final accumulation, which the engine keeps (FUN_1000fd30 returns it).
 */
int acelp_fixed_codebook(int16_t *code, int *pos_out, int npulse,
                         uint32_t sign_idx, uint32_t pos_idx);

/* Pitch lag for one subframe. `subframe` selects absolute vs delta decoding;
 * `prev_lag` is ignored on even subframes. `lpc_order` selects the base, which
 * is ACELP_LAG_BASE for every order this codec ships (15, 16, 17). */
int acelp_pitch_lag(int subframe, int lpc_order, int idx, int prev_lag);

/* Multi-stage LSF vector quantiser, FUN_1000f9a0.
 *
 *   out[i] = (sum over stages k>=1 of cb[(base_k + idx[k]) * order + i]) >> 2
 *            + cb[idx[0] * order + i]
 *
 * `dim` supplies the per-stage codebook sizes that advance base_k. `cb` is the
 * codebook base (`param_5[0x17b]` at runtime); its location in .rdata is not
 * yet identified, so callers must supply it.
 */
void acelp_lsf_vq(int16_t *out, int order, int stages, const int *idx,
                  const int *dim, const int16_t *cb);

#endif /* ACELP_H */
