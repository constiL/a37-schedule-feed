# a37-schedule-feed

Keeps `schedule.json` current so **alchemy37.com/schedule** can correct itself between monthly
rebuilds. Nothing else lives here.

The page draws its own baked class list instantly, then fetches this file and patches anything that
differs. If this repo, GitHub, or the fetch is down, the page is exactly the page that exists today.

## Where the data comes from

Eversports publishes an iCal feed of the whole venue calendar:

```
https://app.eversportsmanager.com/public/scheduler/ics?token=<TOKEN>&scope=venue
```

**The token is a secret.** It lives only in this repo's Actions secrets as
`EVERSPORTS_ICS_TOKEN`. It is not in any file here and never appears in `schedule.json`.

```bash
gh secret set EVERSPORTS_ICS_TOKEN --repo <owner>/a37-schedule-feed
```

**Why not scrape the public schedule page.** `eversports.at/scl/alchemy37-studio` is behind
Cloudflare. A plain fetch returns `403 Just a moment...`, and a real browser was served an
interactive Turnstile challenge on its *second* automated visit. Anything scraping it on a timer
gets challenged more over time, not less, and fails silently. The feed needs no browser, no login
and no Cloudflare, so this runs on a GitHub runner instead of depending on a Mac being awake.

## What runs

`.github/workflows/refresh.yml`, every 3 hours and on demand. It fetches, parses, checks, and
commits **only when the class list actually changed** — `generated` moves every run, so comparing
whole files would commit eight times a day forever.

Two guards refuse to publish rather than publish something wrong:

- fewer than 50 classes (a broken token looks like an empty studio)
- the count dropping by more than 40% in one run (the signature of a partial fetch; a real month
  loses classes gradually as the window rolls, never half at once)

## The file

```json
{"generated":"2026-10-11T14:47:36Z","from":"2026-10-04","to":"2026-10-31","count":233,
 "classes":[{"uid":"…","date":"2026-10-12","time":"19:00","mins":60,
             "name":"HOT HIIT","teacher":"Zoe","cancelled":false}]}
```

About 7.5 KB gzipped. `uid` is the Eversports activity id, so the booking link is
`https://www.eversports.at/activity/<uid>`.

## Three things that will break it if ignored

1. **Times are UTC in the source and Vienna changes offset inside the window.** A Thursday 08:30
   class is `06:30Z` in summer and `07:30Z` after the October clock change. The parser converts
   through `Europe/Vienna`. A fixed `+2` would put every class after the switch an hour out.
2. **`from`/`to` is the limit of what the feed knows**, roughly the past week and the next four.
   **Outside that window there is no information, which is not the same as "cancelled".** A page
   that deleted what it could not see would render the end of the month as gone.
3. **No room and no level.** The feed has neither. Room is derivable from the name prefix
   (`HOT ` / `MEGA `), level is hand-maintained. Both stay baked into the page.

## Checking it is alive

The page prints the `generated` stamp. That is not decoration: without it, a pipeline that quietly
stopped two months ago looks exactly like one that is working.
