#!/usr/bin/env python3
"""Decide whether a freshly fetched schedule is safe to publish, and whether it changed.

Run as:  python3 check.py schedule.next.json [schedule.json]

Exit codes
    0  publish it (something changed)
    1  REFUSE, it looks wrong          -> the workflow fails loudly, old file stays up
    2  nothing changed, skip the commit

A separate file rather than a heredoc inside the workflow YAML on purpose: Python inside shell
inside YAML is three quoting layers, and that only ever fails once it is already live.
"""
import json, sys

MIN_CLASSES = 50
MAX_DROP = 0.40


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    new = load(sys.argv[1])
    classes = new.get("classes") or []

    # A feed that suddenly empties is far more likely to be a dead token or an Eversports
    # change than a studio with no classes. Refuse rather than publish it.
    if len(classes) < MIN_CLASSES:
        sys.exit("REFUSING: only %d classes, expected at least %d" % (len(classes), MIN_CLASSES))
    if not new.get("from") or not new.get("to"):
        sys.exit("REFUSING: no date window in the payload")

    # Every class needs the fields the page patches on, or the page's own validation drops the
    # whole file and the fetch was pointless.
    # ⚠ TEACHER IS NOT IN THIS LIST, deliberately (2026-10-18). An unstaffed class has no teacher
    # and is still real, so refusing the file over one would mean publishing nothing at all. The
    # page's own validator was relaxed to match IN THE SAME CHANGE; a page pasted before that still
    # drops the whole file on an empty teacher, so THE PAGE GOES LIVE FIRST, then this.
    for c in classes:
        for k in ("uid", "date", "time", "name"):
            if not c.get(k):
                sys.exit("REFUSING: a class is missing %r: %r" % (k, c))
        if not (len(c["uid"]) == 36 and c["date"][4] == "-" and ":" in c["time"]):
            sys.exit("REFUSING: malformed class %r" % (c,))

    old = None
    if len(sys.argv) > 2:
        try:
            old = load(sys.argv[2])
        except Exception:
            old = None

    if old:
        drop = len(old.get("classes", [])) - len(classes)
        # A real month loses classes gradually as the window rolls forward, never half at once.
        # A big drop is the signature of a partial fetch.
        if drop > len(old["classes"]) * MAX_DROP:
            sys.exit("REFUSING: class count fell from %d to %d in one run"
                     % (len(old["classes"]), len(classes)))
        # `generated` moves every run, so comparing whole files would commit eight times a day
        # forever. Compare only the classes.
        if old.get("classes") == classes:
            print("unchanged: %d classes, %s to %s" % (len(classes), new["from"], new["to"]))
            sys.exit(2)

    cancelled = sum(1 for c in classes if c.get("cancelled"))
    print("publish: %d classes (%d cancelled), %s to %s"
          % (len(classes), cancelled, new["from"], new["to"]))
    sys.exit(0)


if __name__ == "__main__":
    main()
