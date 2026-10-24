"""Where were the builds made? PE link times (UTC) against candidate office time zones.

A build farm's link times cluster in its working day. For each pack, every distinct
(PE stamp) is converted to local time for each candidate zone (with that year's DST),
and the share falling in 08:00-20:00 local on a weekday is reported.
Speechify (Boston, SpeechWorks) is the calibration.

    python -I tools\\build_clock.py
"""
import datetime as dt
import json
from zoneinfo import ZoneInfo
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ZONES = ["America/New_York", "Europe/Brussels", "Europe/Berlin", "Asia/Tokyo", "Asia/Seoul",
         "America/Los_Angeles", "Asia/Kolkata"]
res = json.load(open(ROOT + r"\tools\pe_survey_2026-10-23.json"))


def stamps(pack, pred=lambda r: True):
    out = set()
    for r in res:
        if r["pack"] == pack and "ts" in r and pred(r):
            out.add(dt.datetime.fromisoformat(r["ts"]).replace(tzinfo=dt.timezone.utc))
    return sorted(out)


groups = {
    "Speechify 3.0.5 (Boston, calibration)": stamps("SPFY", lambda r: r["file"].startswith(("SWItts", "SAPI5", "Speechify"))),
    "SS 2004 pack": stamps("SS"),
    "RS 2006 pack": stamps("RS"),
}
print(f"{'group':40} {'n':>3}  " + "  ".join(f"{z.split('/')[1][:9]:>9}" for z in ZONES))
for g, ts in groups.items():
    row = []
    for z in ZONES:
        zi = ZoneInfo(z)
        loc = [t.astimezone(zi) for t in ts]
        ok = sum(1 for l in loc if 8 <= l.hour < 20 and l.weekday() < 5)
        row.append(ok / len(ts))
    print(f"{g:40} {len(ts):3d}  " + "  ".join(f"{v:9.0%}" for v in row))
for g, ts in groups.items():
    print(f"\n{g}: UTC hours of distinct link times")
    print("   ", sorted({t.hour for t in ts}), " weekdays:", sorted({t.strftime('%a') for t in ts}))
