import json, sys, collections

res = json.load(open(sys.argv[1]))
packs = sys.argv[2].split(",")
# string -> list of (pack:file)
where = collections.defaultdict(list)
for r in res:
    if r["pack"] not in packs:
        continue
    for k, v in r.get("markers", {}).items():
        for s in v:
            where[(k, s[:150])].append(f'{r["pack"]}:{r["file"].split(chr(92))[-1]}')
for (k, s), files in sorted(where.items()):
    fl = sorted(set(files))
    shown = ", ".join(fl[:6]) + (f" +{len(fl)-6}" if len(fl) > 6 else "")
    print(f"[{k[:14]:14}] {s!r:110}  <- {shown}")
