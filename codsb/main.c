/* main.c -- codsb_dump: inspect a ScanSoft/RealSpeak `codsb` container.
 *
 *   codsb_dump <file.dat> [--order N] [--start K] [--count M] [--csv out.csv]
 *
 * With no options it reports the header, the body geometry, and which
 * bit-allocation variants tile the body exactly.
 *
 * ⚠ Which variant a given voice actually uses is NOT stored in the container.
 * The engine takes the LPC order from a runtime field (`param_5[1]` in
 * FUN_1000e190) supplied by the voice font, so `--probe` output can narrow the
 * choice but cannot settle it. Do not treat an exact division as proof: RS4's
 * body is 60,504,808 = 7 * 8,643,544, which divides by BOTH 28 and 49.
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "acelp.h"
#include "codsb.h"
#include "decode.h"

static void wr32(FILE *f, uint32_t v)
{
    fputc((int)(v & 0xff), f);
    fputc((int)((v >> 8) & 0xff), f);
    fputc((int)((v >> 16) & 0xff), f);
    fputc((int)((v >> 24) & 0xff), f);
}

static void wr16(FILE *f, uint16_t v)
{
    fputc((int)(v & 0xff), f);
    fputc((int)((v >> 8) & 0xff), f);
}

/* Decodes `count` frames from `start` and writes a mono 16-bit WAV.
 * Reports RMS and zero-crossing rate: a working decoder produces speech-like
 * statistics, a broken one produces either silence or full-scale noise. */
static int decode_wav(const codsb *c, size_t start, size_t count,
                      const char *path, double gain)
{
    codsb_dec d;
    int32_t v[CODSB_MAX_FIELDS];
    int16_t pcm[CODSB_FRAME];
    const int16_t *cb = codsb_lsf_codebook(c);
    size_t total = codsb_frame_count(c);
    size_t i, n = 0, zc = 0, clipped = 0;
    double sq = 0.0;
    int prev = 0;
    FILE *f;

    if (start >= total) {
        fprintf(stderr, "codsb_dump: start %zu beyond %zu frames\n",
                start, total);
        return -1;
    }
    if (count == 0 || start + count > total) {
        count = total - start;
    }
    f = fopen(path, "wb");
    if (!f) {
        fprintf(stderr, "codsb_dump: cannot write %s\n", path);
        return -1;
    }
    fwrite("RIFF", 1, 4, f);
    wr32(f, (uint32_t)(36 + count * CODSB_FRAME * 2));
    fwrite("WAVEfmt ", 1, 8, f);
    wr32(f, 16);
    wr16(f, 1);
    wr16(f, 1);
    wr32(f, (uint32_t)c->rate);
    wr32(f, (uint32_t)c->rate * 2);
    wr16(f, 2);
    wr16(f, 16);
    fwrite("data", 1, 4, f);
    wr32(f, (uint32_t)(count * CODSB_FRAME * 2));

    codsb_dec_init(&d);
    for (i = start; i < start + count; i++) {
        int k;

        if (codsb_unpack(c, i, v) != 0) {
            break;
        }
        codsb_dec_frame(&d, &c->layout, v, cb, pcm);
        for (k = 0; k < CODSB_FRAME; k++) {
            int s;

            if (gain != 1.0) {
                double t = pcm[k] * gain;

                pcm[k] = (int16_t)(t > 32767.0 ? 32767.0
                                   : (t < -32768.0 ? -32768.0 : t));
            }
            s = pcm[k];

            sq += (double)s * s;
            if ((s < 0) != (prev < 0)) {
                zc++;
            }
            if (s >= 32767 || s <= -32768) {
                clipped++;
            }
            prev = s;
            n++;
        }
        fwrite(pcm, 2, CODSB_FRAME, f);
    }
    fclose(f);
    printf("\ndecoded %zu frames -> %s\n", count, path);
    printf("  %zu samples, %.2f s at %d Hz\n", n,
           (double)n / (c->rate ? c->rate : 1), c->rate);
    printf("  RMS %.1f (%.1f dBFS)   zero-crossing %.0f Hz   clipped %.2f%%\n",
           n ? sqrt(sq / n) : 0.0,
           n ? 20.0 * log10(sqrt(sq / n) / 32768.0 + 1e-12) : -999.0,
           n ? (double)zc * c->rate / (double)n / 2.0 : 0.0,
           n ? 100.0 * (double)clipped / (double)n : 0.0);
    return 0;
}

static void usage(void)
{
    fprintf(stderr,
        "usage: codsb_dump <file.dat> [--order 15|16|17] [--start K]\n"
        "                  [--count M] [--csv out.csv] [--params]\n");
}

/* Decodes lag and fixed-codebook pulses for every subframe over a span and
 * reports whether the results are physically sane. This is a real check on the
 * layout: pulse positions are bounded by construction, but the PITCH LAG is
 * not -- odd subframes decode as prev_lag - 15 + idx5, so a wrong field
 * alignment makes the lag random-walk out of any plausible range, while a
 * correct one keeps it inside the pitch range of a human voice. */
static void dump_params(const codsb *c, size_t start, size_t count)
{
    const codsb_layout *l = &c->layout;
    int32_t v[CODSB_MAX_FIELDS];
    int16_t code[ACELP_SUBFRAME];
    int pos[8];
    size_t total = codsb_frame_count(c);
    size_t i, nsub = 0, out_of_range = 0;
    int lag_min = 1 << 30, lag_max = -(1 << 30);
    int prev_lag = ACELP_LAG_BASE;
    double lag_sum = 0.0, abs_sum = 0.0;
    size_t abs_n = 0;
    int per, npulse;

    if (start >= total) {
        fprintf(stderr, "codsb_dump: start %zu beyond %zu frames\n",
                start, total);
        return;
    }
    if (count == 0 || start + count > total) {
        count = total - start;
    }
    per = (l->nfields - 5) / CODSB_SUBFRAMES;
    npulse = (l->order == 16) ? 4 : 5;

    printf("\nparameter decode: order %d, %d pulses/stage, %zu frames from %zu\n",
           l->order, npulse, count, start);
    printf("%-9s%-4s%-7s%-8s%s\n", "frame", "sf", "lag", "Hz", "pulse positions");
    for (i = start; i < start + count; i++) {
        int s, lag0 = -1;

        if (codsb_unpack(c, i, v) != 0) {
            break;
        }
        for (s = 0; s < CODSB_SUBFRAMES; s++) {
            const int32_t *f = v + 5 + s * per;
            int lag = acelp_pitch_lag(s, l->order, (int)f[0], prev_lag);
            int k;

            acelp_fixed_codebook(code, pos, npulse,
                                 (uint32_t)f[2], (uint32_t)f[3]);
            prev_lag = lag;
            nsub++;
            lag_sum += lag;
            if (s == 0) {
                lag0 = lag;
            } else if (s == 2 && lag0 >= 0) {
                abs_sum += (double)abs(lag - lag0);
                abs_n++;
            }
            if (lag < lag_min) {
                lag_min = lag;
            }
            if (lag > lag_max) {
                lag_max = lag;
            }
            /* a lag outside this span is not a pitch period at 22 kHz */
            if (lag < 40 || lag > 640) {
                out_of_range++;
            }
            if (i - start < 8) {
                printf("%-9zu%-4d%-7d%-8.1f", i, s, lag,
                       lag > 0 && c->rate ? (double)c->rate / lag : 0.0);
                for (k = 0; k < npulse; k++) {
                    printf("%4d", pos[k]);
                }
                printf("\n");
            }
        }
    }
    printf("\n  subframes %zu   lag min %d  max %d  mean %.1f\n",
           nsub, lag_min, lag_max, nsub ? lag_sum / (double)nsub : 0.0);
    /* ⚠ VACUOUS: lag = idx9 + 54 with a 9-bit index is bounded to [54,565] by
     * construction, so this can never fail. Kept only to make that visible. */
    printf("  lag outside 40..640: %zu (%.2f%%)  <-- bounded by construction,"
           " NOT a test\n", out_of_range,
           nsub ? 100.0 * (double)out_of_range / (double)nsub : 0.0);

    /* THE test that can fail. Subframes 0 and 2 each carry an INDEPENDENT
     * absolute 9-bit lag. Under a correct layout they are one speaker's pitch
     * ~7 ms apart and must be close; under a wrong one they are independent
     * uniforms over 512 values, whose mean |difference| is 512/3 = 170.7. */
    if (abs_n > 0) {
        double got = abs_sum / (double)abs_n;
        double null_exp = 512.0 / 3.0;

        printf("\n  mean |lag(sf2) - lag(sf0)| = %.1f over %zu frames\n",
               got, abs_n);
        printf("  null (independent uniform 9-bit) = %.1f\n", null_exp);
        printf("  >>> %s\n", got < 0.35 * null_exp
               ? "COHERENT -- consistent with a correct field alignment"
               : "NOT COHERENT -- indistinguishable from random alignment");
    }
}

static void report_header(const codsb *c)
{
    printf("type        %s\n", c->type);
    printf("coder       %s\n", c->coder);
    printf("rate        %d Hz\n", c->rate);
    printf("hdr_len     %u (+0x14)\n", c->hdr_len);
    printf("toc_len     %u (+0x7c)\n", c->toc_len);
    printf("tag_num     %u (+0x80)\n", c->tag_num);
    printf("file        %zu B\n", c->size);
    printf("body        %zu B at +%u\n", c->body_size, c->toc_len);
}

static void probe(const codsb *c)
{
    int orders[3] = { 15, 16, 17 };
    int i;

    printf("\nvariant fit (body %% frame_bytes):\n");
    printf("  %-6s %-8s %-8s %-14s %-10s %s\n",
           "order", "fields", "bits", "frames", "remainder", "duration");
    for (i = 0; i < 3; i++) {
        const codsb_layout *l = codsb_layout_for(orders[i]);
        size_t frames = c->body_size / (size_t)l->nbytes;
        size_t rem = c->body_size % (size_t)l->nbytes;
        double secs = 0.0;

        if (c->rate > 0) {
            secs = (double)frames * CODSB_FRAME / (double)c->rate;
        }
        printf("  %-6d %-8d %-8d %-14zu %-10zu %.2f h%s\n",
               l->order, l->nfields, l->nbits, frames, rem, secs / 3600.0,
               rem == 0 ? "   <== exact" : "");
    }
}

static void dump_frames(const codsb *c, size_t start, size_t count, FILE *csv)
{
    const codsb_layout *l = &c->layout;
    int32_t v[CODSB_MAX_FIELDS];
    size_t total = codsb_frame_count(c);
    size_t i;
    int j;

    if (start >= total) {
        fprintf(stderr, "codsb_dump: start %zu beyond %zu frames\n",
                start, total);
        return;
    }
    if (count == 0 || start + count > total) {
        count = total - start;
    }
    if (csv) {
        fprintf(csv, "frame");
        for (j = 0; j < l->nfields; j++) {
            int sf;
            codsb_field_role r = codsb_role_of(l, j, &sf);

            if (sf < 0) {
                fprintf(csv, ",%s%d", codsb_role_name(r), j);
            } else {
                fprintf(csv, ",sf%d_%s", sf, codsb_role_name(r));
            }
        }
        fprintf(csv, "\n");
    } else {
        printf("\norder %d: %d fields, %d bits, %d B/frame, %zu frames\n",
               l->order, l->nfields, l->nbits, l->nbytes, total);
        printf("%-10s", "frame");
        for (j = 0; j < l->nfields; j++) {
            int sf;
            codsb_field_role r = codsb_role_of(l, j, &sf);
            char lbl[16];

            if (sf < 0) {
                snprintf(lbl, sizeof(lbl), "%s", codsb_role_name(r));
            } else {
                snprintf(lbl, sizeof(lbl), "%d%s", sf, codsb_role_name(r));
            }
            printf("%8s", lbl);
        }
        printf("\n");
    }
    for (i = start; i < start + count; i++) {
        if (codsb_unpack(c, i, v) != 0) {
            break;
        }
        if (csv) {
            fprintf(csv, "%zu", i);
            for (j = 0; j < l->nfields; j++) {
                fprintf(csv, ",%d", v[j]);
            }
            fprintf(csv, "\n");
        } else {
            printf("%-10zu", i);
            for (j = 0; j < l->nfields; j++) {
                printf("%8d", v[j]);
            }
            printf("\n");
        }
    }
}

int main(int argc, char **argv)
{
    codsb c;
    const char *path = NULL;
    const char *csvpath = NULL;
    FILE *csv = NULL;
    int order = 17;   /* 27.0 kbps -- see codsb.c for the three lines of evidence */
    size_t start = 0, count = 0;
    const char *wavpath = NULL;
    double wavgain = 1.0;
    int i, want_dump = 0, want_params = 0;

    for (i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--order") == 0 && i + 1 < argc) {
            order = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--start") == 0 && i + 1 < argc) {
            start = (size_t)strtoull(argv[++i], NULL, 10);
            want_dump = 1;
        } else if (strcmp(argv[i], "--count") == 0 && i + 1 < argc) {
            count = (size_t)strtoull(argv[++i], NULL, 10);
            want_dump = 1;
        } else if (strcmp(argv[i], "--csv") == 0 && i + 1 < argc) {
            csvpath = argv[++i];
            want_dump = 1;
        } else if (strcmp(argv[i], "--params") == 0) {
            want_params = 1;
        } else if (strcmp(argv[i], "--wav") == 0 && i + 1 < argc) {
            wavpath = argv[++i];
        } else if (strcmp(argv[i], "--gain") == 0 && i + 1 < argc) {
            wavgain = atof(argv[++i]);
        } else if (argv[i][0] == '-') {
            usage();
            return 2;
        } else {
            path = argv[i];
        }
    }
    if (!path) {
        usage();
        return 2;
    }
    if (codsb_open(&c, path) != 0) {
        return 1;
    }
    report_header(&c);
    probe(&c);

    if (codsb_select_order(&c, order) != 0) {
        fprintf(stderr, "codsb_dump: order must be 15, 16 or 17\n");
        codsb_close(&c);
        return 2;
    }
    if (wavpath) {
        decode_wav(&c, start, count ? count : 3000, wavpath, wavgain);
    }
    if (want_params) {
        dump_params(&c, start, count ? count : 20000);
    }
    if (want_dump) {
        if (csvpath) {
            csv = fopen(csvpath, "w");
            if (!csv) {
                fprintf(stderr, "codsb_dump: cannot write %s\n", csvpath);
                codsb_close(&c);
                return 1;
            }
        }
        dump_frames(&c, start, count ? count : 16, csv);
        if (csv) {
            fclose(csv);
            printf("\nwrote %s\n", csvpath);
        }
    }
    codsb_close(&c);
    return 0;
}
