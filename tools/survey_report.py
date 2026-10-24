import json, sys, collections

res = json.load(open(sys.argv[1]))
mode = sys.argv[2] if len(sys.argv) > 2 else "table"

if mode == "table":
    for r in sorted(res, key=lambda r: (r["pack"], r["file"])):
        if r["pack"] == "SPFY" and not r["file"].startswith(("SWItts", "SAPI5", "Speechify")):
            continue
        rich = r.get("rich") or []
        # dominant compiler build = most frequent build number among prodids
        builds = collections.Counter()
        for pid, bld, cnt in rich:
            builds[bld] += cnt
        top = ",".join(f"{b}" for b, _ in builds.most_common(3))
        vi = r.get("verinfo", {})
        print(f'{r["pack"]:4} {r["file"][:44]:44} {r.get("ts","?")[:19]} L{r.get("linker","?"):5} '
              f'rich[{top:18}] ov={r.get("overlay",0):6} exp={len(r.get("exports",[])):4} '
              f'{vi.get("FileVersion","")[:22]:22} {vi.get("CompanyName","")[:30]}')
elif mode == "markers":
    want = sys.argv[3].split(",")
    for r in sorted(res, key=lambda r: (r["pack"], r["file"])):
        for k, v in r.get("markers", {}).items():
            if any(w in k for w in want):
                print(f'{r["pack"]} {r["file"]} [{k}]')
                for s in v:
                    print("     ", s[:160])
elif mode == "exports":
    want = sys.argv[3]
    for r in res:
        if want.lower() in r["file"].lower():
            print(r["pack"], r["file"], r.get("imports"))
            print("   ", " ".join(r.get("exports", []))[:3000])
