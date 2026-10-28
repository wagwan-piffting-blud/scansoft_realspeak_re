#ifndef MODULES_H
#define MODULES_H
#include <stdint.h>

#define MAX_MODULES 32
#define MODULE_BASE0 0x10000000u

typedef struct {
    char name[64];
    char path[300];
    char dir[300];
    uint32_t base, size, entry_rva, export_rva, import_rva;
    int refs, inited;
} module_t;

void mod_env_init(void);
void mod_add_search_dir(const char *dir);
int mod_load(const char *name, const char *importer_dir);
int mod_count(void);
module_t *mod_by_index(int i);
module_t *mod_by_handle(uint32_t h);
module_t *mod_by_name(const char *name);
module_t *mod_by_va(uint32_t va);
uint32_t mod_export(module_t *m, const char *name, uint32_t ordinal);
uint32_t mod_pctype_table(void);
uint32_t call_nested_args(uint32_t fn, const uint32_t *args, int n);

#endif
