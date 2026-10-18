#!/usr/bin/env python3
"""Turn the Eversports venue iCal feed into the small JSON the /schedule page patches itself from.

Source: https://app.eversportsmanager.com/public/scheduler/ics?token=<TOKEN>&scope=venue
The token is a SECRET. It is passed in via the environment, never hardcoded, and it never
appears in the output.

Why iCal and not a scrape: the public schedule page is behind Cloudflare. Plain curl gets 403
"Just a moment...", and a real browser was served an interactive Turnstile challenge on its
second automated visit. The feed needs no browser, no login and no Cloudflare.

Output shape, one object per class occurrence:
    {"uid", "date" (YYYY-MM-DD, Vienna), "time" ("HH:MM", Vienna), "mins", "name", "teacher",
     "cancelled"}
plus a header carrying the window the feed actually covers, which the page MUST respect.
"""
import json, os, re, sys, urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

VIENNA = ZoneInfo("Europe/Vienna")
FEED = "https://app.eversportsmanager.com/public/scheduler/ics?token={token}&scope=venue"

# The language tag rides inline in the summary ("MEGA SCULPT · DE"). The live DATA carries no
# name with a middot, so it is stripped here exactly as build-schedule-data.py strips it.
LANG = re.compile(r"\s*·\s*(DE/ENG|DE/EN|DE|ENG|EN)\s*$")
SUMMARY = re.compile(r"^(?P<name>.+?)\s+@\s+.*?\s+by\s+(?P<teacher>.+?)\s*$")
# ⚠ A CLASS WITH NO TEACHER YET IS STILL A REAL, BOOKABLE CLASS and must be published (owner
# 2026-10-18: "nothing should get skipped"). Eversports writes "HOT GLOW™ @ Alchemy37 Studio" with
# no "by ..." while a slot is unstaffed, which the regex above cannot match. Skipping those made the
# page DELETE them, because the page reads absence from this file as a cancellation. Measured on
# 2026-10-18: 2 inside the feed window, 5 across November.
SUMMARY_NO_TEACHER = re.compile(r"^(?P<name>.+?)\s+@\s+.+?\s*$")


def unfold(text):
    """iCal folds long lines with a leading space on the continuation. Rejoin before parsing,
    or a DESCRIPTION or SUMMARY that wrapped is silently truncated."""
    out = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if line[:1] in (" ", "\t") and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def unescape(v):
    return v.replace("\\,", ",").replace("\\;", ";").replace("\\n", "\n").replace("\\\\", "\\")


def parse_dt(raw):
    """DTSTART is UTC (trailing Z). Convert through the Vienna zone, NEVER a fixed +2:
    the feed spans the DST change (a Thursday 08:30 class is 06:30Z on 8 Oct and 07:30Z on
    29 Oct 2026), so a fixed offset puts every class after the switch an hour out."""
    raw = raw.split(";")[-1] if ";" in raw else raw
    if raw.endswith("Z"):
        dt = datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    else:
        dt = datetime.strptime(raw, "%Y%m%dT%H%M%S").replace(tzinfo=VIENNA)
    return dt.astimezone(VIENNA)


def parse(text):
    classes, skipped = [], []
    cur = None
    for line in unfold(text):
        if line == "BEGIN:VEVENT":
            cur = {}
            continue
        if line == "END:VEVENT":
            if cur is not None:
                row = build(cur, skipped)
                if row:
                    classes.append(row)
            cur = None
            continue
        if cur is None or ":" not in line:
            continue
        key, val = line.split(":", 1)
        cur[key.split(";")[0]] = val
    classes.sort(key=lambda c: (c["date"], c["time"], c["name"]))
    return classes, skipped


def build(ev, skipped):
    uid = ev.get("UID", "").strip()
    start, end = ev.get("DTSTART"), ev.get("DTEND")
    summary = unescape(ev.get("SUMMARY", "")).strip()
    if not (uid and start and summary):
        skipped.append(("missing field", summary or uid)); return None
    m = SUMMARY.match(summary)
    teacher = m.group("teacher").strip() if m else ""
    if not m:
        m = SUMMARY_NO_TEACHER.match(summary)
        if not m:
            skipped.append(("unparsed summary", summary)); return None
    s = parse_dt(start)
    mins = int((parse_dt(end) - s).total_seconds() // 60) if end else None
    return {
        "uid": uid,
        "date": s.strftime("%Y-%m-%d"),
        "time": s.strftime("%H:%M"),
        "mins": mins,
        "name": LANG.sub("", m.group("name").strip()).strip(),
        "teacher": teacher,
        "cancelled": ev.get("STATUS", "").strip().upper() == "CANCELLED",
    }


def main():
    if len(sys.argv) > 1 and sys.argv[1] != "-":
        text = open(sys.argv[1], encoding="utf-8").read()
        source = sys.argv[1]
    else:
        token = os.environ.get("EVERSPORTS_ICS_TOKEN", "").strip()
        if not token:
            sys.exit("EVERSPORTS_ICS_TOKEN is not set. It is a secret: pass it in the "
                     "environment, never on the command line and never in a file.")
        req = urllib.request.Request(FEED.format(token=token),
                                     headers={"User-Agent": "alchemy37-schedule/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read().decode("utf-8")
        source = "live feed"

    classes, skipped = parse(text)
    if not classes:
        sys.exit("refusing to write: the feed produced zero classes")

    live = [c for c in classes if not c["cancelled"]]
    # ⚠ THE PAGE MUST NOT TREAT "absent" AS "cancelled" OUTSIDE THIS WINDOW. The feed only runs
    # to a horizon (past ~1 week, next ~4 weeks), so beyond `to` there is simply no information,
    # and a page that deleted what it could not see would render the end of the month as gone.
    out = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "from": classes[0]["date"],
        "to": classes[-1]["date"],
        "count": len(classes),
        "classes": classes,
    }
    sys.stderr.write(
        "source: %s\n  %d classes, %d cancelled, %s to %s\n"
        % (source, len(classes), len(classes) - len(live), out["from"], out["to"]))
    for kind, what in skipped[:10]:
        sys.stderr.write("  SKIPPED (%s): %s\n" % (kind, what[:90]))
    if skipped:
        sys.stderr.write("  %d skipped in total\n" % len(skipped))
    json.dump(out, sys.stdout, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
