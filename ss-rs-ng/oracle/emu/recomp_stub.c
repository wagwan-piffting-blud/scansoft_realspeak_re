/* No recompiled functions: cpu.c's static-recompilation hook stays off
 * (rc_image_matches() fails on base 0), so everything is interpreted. */
#include <stdint.h>
#include "recomp.h"

static int rc_none(void) { return RC_EXIT; }

const uint32_t rc_entry_va[1] = {0};
int (*const rc_entry_fn[1])(void) = {rc_none};
const int rc_n_entries = 0;
const uint32_t rc_image_base = 0, rc_image_size = 0, rc_image_stamp = 0;
