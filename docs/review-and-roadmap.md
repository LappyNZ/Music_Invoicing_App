# Code review and roadmap

*Reviewed September 2026 against `main` @ `32d6a47`. The repo history starts at "Initial public release" (12 Apr 2026), followed by the GHCR workflow (13 Apr 2026). Updated after comparing with a copy of the Unraid server folder ([§2](#2-what-is-running-on-unraid-resolved)).*

Contents: [1 Summary](#1-summary) · [Status](#status-27-september-2026) · [2 What is running on Unraid](#2-what-is-running-on-unraid-resolved) · [3 Invoicing this week?](#3-invoicing-this-week-work-around-the-bugs-like-this) · [4 Confirmed bugs](#4-confirmed-bugs) · [5 Root causes](#5-structural-issues-root-causes) · [6 What's good](#6-whats-good-keep-it) · [7 UX proposal](#7-ux-proposal-organise-the-app-around-the-term) · [8 Roadmap](#8-roadmap) · [9 Decisions needed](#9-decisions-needed) · [Appendices](#appendix-a-proposed-data-model)

---

## 1. Summary

- **The foundations are fine, so no rewrite is needed.** Flask, SQLite and server-rendered pages are the right size for a one-teacher studio. The code is already split into routes and services, uses parameterised SQL throughout, and has good email safety switches.
- **The server runs this repo's code.** Since April 2026 the Unraid container has used the GitHub image built from this repo ([§2](#2-what-is-running-on-unraid-resolved)), so every bug below is live. The live data backs several of them up: the Lessons page is already over 10 MB, some paid invoices are hidden because their students were deleted, and wrong invoices are being retired by marking them paid at $0 because there's no Void.
- **I found 22 problems ([§4](#4-confirmed-bugs)).** Most were reproduced by running the app the way Docker does (gunicorn) and clicking through it in a real browser. The "buttons that don't work" have two causes: a form nested inside another form, which makes the top **Mark sent** do nothing (B1), and the actions menu getting clipped by the table (B2).
- **The most dangerous bug for day-to-day use is B5.** On *Create*, if you preview one student, switch to another and press *Preview* again, the page keeps the **first student's lessons**. Pressing *Generate PDF* then bills the second student for them.
- **The biggest structural gap: an invoice is stored only as a total plus a PDF file.** The lines (which lessons, which extras) are never saved. So an invoice can't be edited, re-issued or credited, and the app can't tell which lessons have already been billed. This is why changes after sending are done by hand, and it also blocks payment tracking and rentals. Fixing it is the core of the roadmap.
- **The biggest UX opportunity is a term register.** Today invoices are built one student at a time, so the diary is read once per student. The register would be a students × weeks grid, pre-filled from each student's regular lesson, where you only mark the exceptions. That takes **one pass through the diary, week by week**, and then produces every draft invoice at once ([§7](#7-ux-proposal-organise-the-app-around-the-term)).
- **Do this first:** keep the server backup safe and tidy the leftover files on the server ([§2](#2-what-is-running-on-unraid-resolved)). Then start Phase 1, fixes only ([§8](#8-roadmap)).

---

## Status (27 September 2026)

The quick fixes before Term 3 invoicing are done. They go live on the server with `update.sh` once merged
([deploy/unraid/README.md](../deploy/unraid/README.md)).

- **Fixed:**
  - B1: *Mark sent* works on every row.
  - B2: action menus open next to their button instead of being cut off.
  - B3: *Weeks Repeating* can be left blank.
  - B5: changing student or dates reloads the lessons, and stale rows are never billed.
  - B6: extras are kept on a second Preview.
  - B9: a confirmation shows count, total and re-sends, and paid or void invoices can't be emailed.
  - B11: the compose files' TZ and healthcheck.
  - B12: database upgrades run at start-up, safely with several workers.
  - B18 (part): **Void** and **Restore**.
- **Also done:**
  - The Create page no longer crashes on a lesson time containing a "T" (part of B4).
  - It says when there are no lessons, refuses to make an empty invoice, and ignores double clicks.
  - The version shows in the footer.
  - GitHub runs the tests before publishing an image.
  - New scripts for backups, updates, the server tidy-up and restoring ([deploy/unraid/](../deploy/unraid/)).
- **Rehearsed** end to end in Docker on a copy of the live database: backup, tidy, upgrade, restore and rollback.
- **Still open from Phase 1:**
  - B4 (the lesson edit box itself), B7, B8, B10, B13, B14, B15, B16, B17, B20 and B22.
  - The rest of B19.
  - Undoing *Mark paid*.

---

## 2. What is running on Unraid (resolved)

Checked against a copy of the server folder (code and configuration only; the secrets in it were not opened, and nothing from it has been added to this repository).

**The container runs this repo's code**, specifically the GitHub image built from commit `32d6a47`:

- The server's `docker-compose.prod.yml` (edited 13 April 2026, about 20 minutes after GitHub published the image) uses `image: ghcr.io/lappynz/music_invoicing_app:latest` and mounts only `data` and `secrets`. No source folder is mounted over the image.
- Only one image has ever been published, and it was built from `32d6a47`.
- The invoice PDFs agree. Up to early April they carry an older ReportLab signature; from early May onward they carry exactly the signature this repo's pinned ReportLab produces, with an identical layout.

To confirm with one command on Unraid (it should print `32d6a4778dd7…`):

```sh
docker inspect music-invoice --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}'
```

**Tidy the server folder.** Some of what's in it is unused, and some of it quietly matters:

| Item | Status | What to do |
|---|---|---|
| `app/`, `Dockerfile`, `docker-compose.yml`, `start.sh` | **Unused** leftovers from the old build-from-folder setup: a single `app.py` from October 2025. It contains personal details hard-coded in the source. | Move them into an `old/` folder, or delete them after keeping a private copy. **Never publish them.** |
| `.env` (next to `docker-compose.prod.yml`) | **Used, but not obviously.** Docker Compose reads it to fill in `${TZ}` and `${PORT}`, which is why the timezone bug B11 doesn't affect your server. | Keep it until the B11 fix is deployed. |
| `.env.prod` | Used: the container's settings. | Keep; private. |
| `certs/` | Unused by the current setup. | Archive. |
| `data/`, `secrets/` | Live data and the Gmail credentials. | Back up regularly and keep private. |

**Backups:** a zip of that folder is a complete backup (database, PDFs and credentials). Keep it somewhere private, because it contains the Gmail token and bank details, and automate it (Phase 0). NZ requires business records to be kept for 7 years.

**Gmail check:** in Google Cloud Console, go to APIs & Services, then OAuth consent screen. If *Publishing status* is **Testing**, Google expires the refresh token after 7 days and sending fails until you re-authorise. Switching it to **In production** stops that. For your own account you can click through the "unverified app" warning.

**What changed when the server switched to this code in April:** the app behaves the same (the templates and CSS are identical apart from renamed routes, and so are most functions), with two exceptions. The email safety switches were added, and the invoice email wording changed (B22).

---

## 3. Invoicing this week? Work around the bugs like this

Term 3 ended on Friday 25 September, and Term 4 starts on Monday 12 October. Until the fixes land:

> **Once the September 2026 update is deployed**, only two rows still apply: the lesson-time format and not deleting students. For a wrong invoice, use the new **Void** button instead of the $0 workaround.

| Do this | Because |
|---|---|
| Click **Create** in the menu to start fresh for each student. Don't switch student or dates on a page you have already previewed. | Otherwise the previous student's lessons are kept (B5). |
| Add extra items **last**, just before *Generate PDF*. | Pressing *Preview* again wipes them (B6). |
| Always fill in *Weeks Repeating* (type 1 for a single lesson). | Leaving it blank gives a server error (B3). |
| When editing a lesson time, keep the exact format `2026-07-20 15:30`. | Other formats either crash that student's invoice preview or make the lesson silently vanish from invoices (B4). |
| Set the filter to *Status = Draft* **before** *Select all*, then *Send Selected*. | Otherwise invoices already sent or paid are emailed again, with no confirmation (B9). |
| Don't delete a student who has invoices. | Their invoices disappear from the list (B8). |
| If a **⋯** menu is cut off, widen the filter so that invoice isn't in the last two rows. | The menu gets clipped (B2). |
| Don't rely on *Mark sent* for the top-most draft invoice. | It does nothing, and there's no UI workaround (B1, a small fix). |
| To retire a wrong invoice, keep marking it paid at $0 with a reference naming its replacement. | There's no Void yet (B18). This keeps it out of *Select all*, but it muddles the payment figures until Phase 1 adds Void. |

---

## 4. Confirmed bugs

B1–B13, B17 and parts of B19 were reproduced or measured against a running copy of the app. B14, B16 and B22 come from reading the code (and, for B14, the Google library's source). B15 needs real Gmail to reproduce. B18, B20 and B21 are gaps or risks rather than defects. **Live** notes come from aggregate checks of the server's database (counts and formats only). **Severity:** 🔴 wrong result or lost data · 🟠 broken feature or crash · 🟡 annoyance, risk or robustness.

| # | | What happens | Where / why | Fix |
|---|---|---|---|---|
| B1 | 🟠 | **Mark sent** on the top-most draft invoice does nothing; it works on the other rows. | `invoice_list.html:193` is a `<form>` inside the bulk-send `<form>` (`:66`). Browsers drop the first nested form tag, so that button submits the bulk-send form instead. | Take the row actions out of the bulk form (e.g. `formaction` on the button). |
| B2 | 🟠 | The **⋯** actions menu is cut off for invoices in the last rows of the table; with one or two invoices listed, it's unusable. | `.table { overflow: hidden }` (`style.css:55`) and the `.table-responsive` wrapper (`invoice_list.html:84`) both clip it. | `data-bs-popper-config='{"strategy":"fixed"}'` on the toggle (tested: fixes it). |
| B3 | 🟠 | Adding a lesson with *Weeks Repeating* blank gives "Internal Server Error". | `lessons.py:18` runs `int("")`. | Default to 1. |
| B4 | 🟠 | Editing a lesson time into any other format (e.g. `2026-07-20T15:30`) makes that student's invoice preview crash. Other text isn't recognised as a date at all, so that lesson silently drops out of invoices and filters. **Live:** one lesson is already stored this way (it looks like a leftover duplicate). | The edit box is free text (`lessons.html:112`), is saved as typed (`lessons.py:94-108`), and is parsed strictly (`invoices.py:62`). | Date-time picker, normalise on save, clean up existing rows. |
| B5 | 🔴 | *Create*: after a preview, changing the student or dates and pressing *Preview* keeps the previous student's lessons, and *Generate PDF* bills the new student for them. | `invoices.py:33-50` reuses the posted rows whenever `lesson_count > 0`. | Reload from the DB when the student or dates change. |
| B6 | 🟠 | Extra items disappear from the form when *Preview* is pressed again, and the total drops. | `invoices.html:63-76` always renders five empty rows. | Re-fill them from `extras`. |
| B7 | 🟡 | The Lessons filter leaves out lessons on the *end* date. | `lessons.py:59-61` compares `'2026-07-20 15:00' <= '2026-07-20'` as text. | Compare `date(lesson_time)`, as the invoice query already does. |
| B8 | 🔴 | Deleting a student removes their invoices from the invoice list (the rows stay orphaned in the DB) and deletes all their lessons. **Live:** some paid 2025 invoices are already hidden this way, so any income total taken from the list comes up short. | `students.py:78-86`, `db.py:28` (`ON DELETE CASCADE`), `invoices.py:195` (inner join). | Archive students instead; block deletion when invoices exist. |
| B9 | 🔴 | *Send Selected Invoices* has no confirmation, and *Select all* includes sent and paid invoices, so one click can re-email every family. | `invoice_list.html:72-81`, `invoices.py:252-305`. | "Send 27 invoices ($8,450)?" confirmation; skip paid invoices; make re-sending an explicit action. |
| B10 | 🟡 | Times mix UTC and NZ time, and the invoice number is recomputed in three places from different clocks. An invoice created on NZ New Year's morning gets a PDF named `INV-2027-…` but is listed and emailed as `INV-2026-…`, so it shows "PDF file is missing" and can't be emailed. **Live:** `paid_at` is stored in three different formats. | UTC: `db.py:41`, `invoices.py:128`. Local: `invoices.py:290`, `:352`, `pdf_service.py:54`. Recomputed: `invoice_list.html:100`, `invoices.py:400`, `utils.py:4-6`. | Store the invoice number and PDF filename when the invoice is created; use one time convention. |
| B11 | 🟡 | In the compose files, `TZ=${TZ}` and the healthcheck's `${PORT}` are filled in when Compose starts, from the shell or a `.env` file beside the compose file, **not** from `.env.prod`. Without them the container gets `TZ=""` (UTC), so PDFs made before midday (1 pm in summer) show yesterday's *Date Issued*, and the healthcheck calls port 80, so Docker marks the container "unhealthy". **Not live on your server:** the `.env` beside the compose file supplies both (PDFs generated at 9 am carry the right date). It does affect the repo's `docker/` layout, and would affect the server if that `.env` were removed. | `docker-compose.prod.yml:11-12, 26` (dev file too). Checked with `docker compose config`. | Default the values in the compose file (`${TZ:-Pacific/Auckland}`, `$${PORT}`). |
| B12 | 🟠 | Database setup and migrations never run in Docker. On a fresh database every page errors (`no such table`), and new columns added in future will never reach the live DB. | `init_db()` only runs under `python app.py` (`app.py:43-45`), but the container starts gunicorn (`start.sh`). | Run versioned migrations when the container starts. |
| B13 | 🟡 | `scripts/reset_dev_db.py` builds a database the app can't use: it has no `lessons` table, and `invoices` is missing its dates, total and `created_at`. Even running the app's own `init_db()` afterwards leaves the invoice list broken (`no such column: invoices.start_date`). | `reset_dev_db.py:15-36` | Reuse `init_db()` and seed sample data. |
| B14 | 🟠 | Gmail re-authorisation runs *inside a web request*. If the token is missing or revoked, the app opens a listener on port 8090 and waits (gunicorn kills it after 60 s). Google also redirects the browser to `http://0.0.0.0:8090/`, which can't reach the container. | `email_service.py:26-39`. | Separate "Connect Gmail" step, or SMTP with a Google app password. |
| B15 | 🟡 | *(Not reproduced; needs real Gmail.)* A bulk send runs in one web request. With enough invoices it can pass gunicorn's 60 s timeout (`start.sh:7`), leaving the batch half-sent with an error page. A new Gmail client is also built for every email. | `invoices.py:271-305`, `email_service.py:93`. | Send one invoice per request, with a progress bar. |
| B16 | 🟡 | The email asks payers to use the student's name as the reference; the PDF asks for "name + INV-2026-0042". NZ bank reference fields hold 12 characters, and `INV-2026-0042` has 13. Inconsistent references make payments harder to match. | `invoice_service.py:30`, `pdf_service.py:96`. | One short reference everywhere, e.g. `INV26-0042`. |
| B17 | 🟡 | The Lessons page lists every lesson ever stored, each with two hidden dialogs containing the whole student list. With two years × 30 students that's **16.5 MB of HTML, 4,800 dialogs and 72,000 `<option>` tags** (measured), which will be very slow, especially on a tablet. **Live:** your Lessons page is already over 10 MB. | `lessons.py:39-65`, `lessons.html:84-153`. | Default to the current term; use one shared edit dialog. |
| B18 | 🟠 | Missing features rather than bugs: you can't undo *Mark paid*, record a part-payment, or void a wrong invoice (it stays a draft and gets caught by *Select all*), and you can't change an invoice once it's generated. **Live:** wrong invoices are being retired by marking them paid at $0, which distorts the payment figures, and part-payments are common. | | Covered in Phases 1 and 2. |
| B19 | 🟡 | Smaller robustness issues: text in `<angle brackets>` silently disappears from PDFs (ReportLab markup, `pdf_service.py:58`); long extra-item descriptions don't wrap (`:76`); non-numeric amounts cause server errors (`invoices.py:132,144`); nothing checks that start date ≤ end date; *Preview* with no lessons shows nothing instead of a message; double-clicking *Generate PDF* can create a duplicate invoice; the "(blank)" school filter can't be chosen (`students.html:17-19`). | | Phase 1. |
| B20 | 🟡 | Security is acceptable on a trusted home network, but needs fixing before remote access or card payments. There's no login and no CSRF protection, so any web page open on a device on the LAN could submit the app's forms. The `SECRET_KEY` falls back to a default value. | All routes; `config.py:11`. | Phase 2. |
| B21 | 🟡 | The deployment is ambiguous. The repo's prod compose file builds locally and mounts the source folder over the image, but the server pulls the GitHub image using its own compose file, which isn't in the repo. The server folder also still holds the old build files, and the UI shows no version. That is why it was unclear what is live. | `docker/docker-compose.prod.yml:15`; the server folder. | Make the repo's compose file match the server's image-based one; show the version in the footer. |
| B22 | 🟡 | The invoice email changed when the server switched to this code in April. The old email ended with a full signature (qualification, address, phone numbers, bank name) and asked for the reference "name + invoice file name". The current one ends with just the sender's name and asks for the student's name as the reference, which also differs from the PDF (B16). | `invoice_service.py:24-33`. | Put the signature in `.env.prod` (e.g. `EMAIL_SIGNATURE`) and use one reference everywhere. |

Minor tidy-ups: the PDF doesn't show the bill-to parent or the business name as text (`BUSINESS_NAME` in `config.py` is unused, and the name is hard-coded in `base.html`). `requirements.txt` is saved as UTF-16: pip copes, but GitHub's dependency tools don't. The Docker image installs `build-essential` and `libpq-dev`, which nothing needs.

---

## 5. Structural issues (root causes)

1. **Invoices don't remember their contents.** Only the student, period and total are saved; the lessons and extras live only inside the PDF. That blocks editing, re-issuing, credits and regenerating a PDF. It also means the app can't tell which lessons are billed, so nothing stops a lesson being billed twice if two invoice periods overlap. **Fix:** an `invoice_lines` table, and lessons that link to the invoice that billed them.
2. **The app has no idea of terms, attendance or a regular timetable.** Lessons are just timestamps. "Term" is approximated by calendar quarters (`utils.py:9-17`; the filter says "Term 1 (Jan–Mar)"). The real 2026 terms are: T1 to 2 Apr, T2 20 Apr–3 Jul, T3 20 Jul–25 Sep, T4 12 Oct–18 Dec. **Fix:** a `terms` table seeded with the [Ministry of Education dates](https://www.education.govt.nz/school/school-terms-and-holiday-dates), a status on each lesson, and each student's regular slot and rate.
3. **Schema changes have no route to production** (B12). **Fix:** numbered migrations, run at start-up and tracked with `PRAGMA user_version`.
4. **Money is stored as floating point, timestamps use mixed zones, and identifiers are derived rather than stored** (B10). **Fix:** integer cents, one timestamp convention, stored invoice numbers.
5. **Slow work happens inside web requests** (B14, B15).
6. **There are no tests.** Every bug above is cheap to pin down with one. **Fix:** pytest with Flask's test client, plus a few browser checks (Playwright) for the button-level bugs, run by CI before the image is published.
7. **The deployment isn't described in the repo, and no version is visible** (B21). The server already uses the right approach (pull the GitHub image), but that setup exists only on the server.

---

## 6. What's good: keep it

- A clear structure: blueprints for pages, services for email and PDFs, configuration from environment variables.
- SQL is parameterised everywhere (no SQL-injection risk), and Jinja auto-escaping is on.
- The email safety switches (`EMAIL_ENABLED`, `EMAIL_REDIRECT_TO`), which made this review safe to run.
- Filters are kept across actions.
- Friendly email wording (Kia ora / Ngā mihi).
- Docker on Unraid, with the data kept outside the container.

---

## 7. UX proposal: organise the app around the term

### How it works today

For each student: *Create* → pick the student → type the dates → *Preview* → check the diary and delete or adjust rows → add extras → *Generate PDF* → land on the invoice list → *Create* again, about 30 times over. Then filter, select and send. Changes after sending happen outside the app.

The diary is organised **by date**, but the app makes you work **by student**, so the diary gets read once per student.

### Proposed flow

1. **Start of term (once, about two minutes):** *Start Term 4* creates the expected lessons for every active student from their regular slot (e.g. Tue 4:00 pm, 30 min, $60/h). Public holidays can be marked in advance.
2. **Register (replaces the diary session):** one screen per term, with students down the side and weeks across the top. Every expected lesson starts as ✓. Read the diary week by week and click only the exceptions:

   | Student | 20 Jul | 27 Jul | 3 Aug | 10 Aug | … | Charged | Amount |
   |---|:-:|:-:|:-:|:-:|:-:|--:|--:|
   | Alice Aroha | ✓ | ✓ | ✗ | ✓ | … | 9 | $270.00 |
   | Ben Brown | ✓ | $ | ✓ | ✓ | … | 10 | $450.00 |
   | Chloe Chen | ✓ | ✓ | ✓ | ✓＋ | … | 11 | $330.00 |

   ✓ taught · ✗ cancelled, not charged · $ missed but charged · ＋ extra or makeup lesson. Clicking a cell cycles through these; cells are large enough to tap on an iPad.
3. **Generate drafts:** one button creates a draft for every student (lessons, instrument rental and any extras), stored line by line.
4. **Review drafts:** a list with totals. Open any draft to adjust lines or add extras; the PDF regenerates automatically.
5. **Send:** a confirmation ("Send 27 invoices totalling $8,450?"), then a progress bar, one email at a time, each logged.
6. **After sending:** *Edit* creates a revised version (same number, marked "Revised") and offers *Resend*. Alternatively, add a credit to next term's invoice. *Void* is for mistakes.
7. **Payments:** see who has and hasn't paid, and import the bank statement to tick them off automatically (Phase 4).

Design principles for a non-technical main user:

- A home screen that says what to do next, e.g. "Term 3: register complete ✓ · 27 drafts ready → Review & send" or "5 invoices unpaid: $1,350".
- Plain words and a visible label on every field, instead of placeholders. On the Lessons page the duration box is currently labelled "Lesson Time (mins)" and sits next to the date-time box.
- Larger text and high contrast: keep the cello photo in the header rather than behind the forms, because white labels on the frosted background are hard to read.
- Archive instead of delete, and undo where possible. Confirmations are only for actions that email people or can't be undone.
- Later, optionally: a phone "Today" view for ticking lessons off straight after teaching, which removes the diary session entirely.

The navigation would become **Home · Register · Invoices · Payments · Students · Instruments**, instead of Students · Lessons · Create · View.

> **Build or buy?** Studio software (e.g. My Music Staff, TutorBird) and Xero already cover attendance, invoices, card payments and reconciliation for a monthly fee. Building your own makes sense for NZ-term billing, cello rentals, no subscription, and because it's fun. It's still worth deciding deliberately before the payments phases.

---

## 8. Roadmap

Rough sizes, assuming AI-assisted work: **S** is about an evening, **M** about a weekend, **L** several weekends. Phases 0 and 1 are prerequisites for everything else. Phase 2 unlocks Phases 3 and 4 (which can be done in either order), and Phase 5 builds on Phase 4.

### Phase 0: Know what's live and protect the data (S, before any code change)
- 0.1 ✅ Find out what's live: it's this repo's code ([§2](#2-what-is-running-on-unraid-resolved)). Optionally confirm with the one-line `docker inspect`.
- 0.2 Keep the server zip as a private backup. Set up a nightly automatic backup (✅ script ready: `deploy/unraid/backup.sh`) of `data/` and `secrets/` (e.g. the Unraid *User Scripts* plugin, keeping 30 days, copied off the server).
- 0.3 Tidy the server folder (✅ script ready: `deploy/unraid/tidy-server.sh`): archive the unused old build files and `certs/`, but **keep `.env`** until the B11 fix is deployed ([§2](#2-what-is-running-on-unraid-resolved)).
- 0.4 Check the Gmail consent screen status.

### Phase 1: Stabilise (M): fixes only, no new behaviour
- 1.1 **Test harness:** ✅ pytest and Flask test client (29 tests); a sample-data seed and fixing `reset_dev_db.py` (B13) are still to do. Every fix below comes with a test.
- 1.2 **Deployment:**
  - ✅ Run migrations at start-up (B12).
  - ✅ Show the version (git commit) in the footer and at `/version`.
  - ✅ Put the server's image-based compose file into the repo, with safe defaults for `TZ`/`PORT` (B11, B21). Deploying an update then means `docker compose pull && docker compose up -d` on Unraid; pin a commit tag to roll back.
  - ✅ Save `requirements.txt` as UTF-8 and have CI run the tests before publishing. (Slimming the image is still to do.)
- 1.3 ✅ **Buttons:** B1, B2.
- 1.4 **Lessons:** ✅ B3; B4 (the invoice preview no longer crashes; the edit box and existing times still to do); B7; open the Lessons page on the current term by default (B17).
- 1.5 ✅ **Create invoice:** B5, B6; stop double-submits; show "no lessons found" when there are none.
- 1.6 **Safe sending:** ✅ confirmation, skip paid invoices, explicit re-send (B9); one email per request with progress (B15); Gmail authorisation outside web requests (B14).
- 1.7 **Keep history:** archive students instead of deleting them, and keep their invoices visible (B8).
- 1.8 **Stable invoice numbers:** store the invoice number and PDF filename, with consistent timestamps (B10). Optionally switch to a short number like `INV26-0042` and one payment reference everywhere (B16); this needs your OK (Q6).
- 1.9 **Void and undo** (✅ Void and Restore; part of B18; high value, because the $0 "Mark paid" workaround is already in use): void an invoice, optionally pointing to its replacement; undo *Mark paid*. Existing $0 "payments" become voids.
- 1.10 **Email wording:** signature from settings, one consistent payment reference (B16, B22).
- 1.11 **Data clean-up migration:** repair the unreadable lesson time, normalise `paid_at` formats, and show invoices of deleted students again as archived (B4, B8, B10).

### Phase 2: Term-based workflow (L): the big UX improvement
- 2.1 **Data model:** terms (seeded 2026–27), each student's regular slot, rate, active flag and billing contact(s), lesson status, `invoice_lines`, and money in cents ([Appendix A](#appendix-a-proposed-data-model)).
- 2.2 **Start term:** creates the expected lessons from regular slots, optionally skipping public holidays.
- 2.3 **Register grid:** click to cycle a lesson's status, with live totals. Probably [htmx](https://htmx.org), so cells update without reloading the page.
- 2.4 **Drafts:** generate drafts for all students; review and edit them; regenerate PDFs automatically. The PDF should show the bill-to parent, a due date and the business name.
- 2.5 **After sending:** revisions, credits and void; *Resend*; an email log.
- 2.6 **Look and feel:** home dashboard, new navigation, visual refresh (labels, contrast, bigger targets).
- 2.7 **Security:** a login for each of you, plus CSRF protection (B20).
- **Existing data:** old invoices keep their total and PDF as "legacy" invoices without lines; past lessons become "taught".

### Phase 3: Instruments and rentals (M)
- 3.1 **Inventory:** code, size (1/10 to 4/4), maker, serial number, value, condition, status (available, rented, in repair, retired), optional photo.
- 3.2 **Rentals and hand-overs:** who has which instrument, start and end dates, rate and period, deposit, condition out and in. A hand-over log answers "where is each cello?" at any time, including "at the luthier".
- 3.3 **Billing:** term invoices automatically include active rentals, with a pro-rata option for mid-term starts.
- 3.4 **"Where are the cellos?" board:** filter by size and see who has what, and since when. Also a maintenance log, and a flag for students who may need the next size up.

### Phase 4: Payments, semi-automatic (M)
- 4.1 **Payments:** recorded separately and allocated to invoices, which handles part-payments, one transfer covering siblings, balances and overdue status.
- 4.2 **Bank import:** import a bank CSV (all the main NZ banks export one), auto-match on reference, amount and payer name, then confirm ("18 matches found: confirm all").
- 4.3 **Reminders:** one-click friendly reminders for overdue invoices.
- 4.4 **Reports:** invoiced vs received per term and per tax year (1 Apr–31 Mar), with CSV export for the accountant.

### Phase 5: Automation and card payments (optional, M each)
- 5.1 **Automatic bank feed** via [Akahu](https://www.akahu.nz/pricing), replacing the CSV step. Akahu's "personal app" gives free API access to your own accounts; check the current terms.
- 5.2 **Card payments via Stripe:**
  - Each invoice gets a "Pay by card" link and QR code (a Stripe-hosted Payment Link).
  - The app checks Stripe for completed payments and marks invoices paid, so the home server never needs to be opened to the internet.
  - Fees are about 2.65% + 30c per NZ card, roughly $8 on a $300 invoice (check [stripe.com/nz/pricing](https://stripe.com/nz/pricing)).
  - On passing the fee on: NZ's proposed surcharge ban targets *in-store* payments, and online payments are excluded. Check the current rules first.
- 5.3 **Access away from home:** use Tailscale on Unraid rather than opening router ports, plus a phone "Today" view for ticking off lessons.

---

## 9. Decisions needed

1. ~~**Unraid check**~~: answered. The server runs this repo's code ([§2](#2-what-is-running-on-unraid-resolved)).
2. **Siblings:** the data shows very few families with more than one student, so one invoice per student looks fine. Say so if you'd prefer family invoices.
3. **Billing rules:** the data shows you invoice at the end of each term (in arrears), which the register design fits. Still open: which absences are charged (e.g. short notice)? How are makeup lessons handled? Are lessons that fall in the school holidays real (e.g. makeups to bill) or leftovers from *Weeks Repeating*?
4. **Rates:** some students' rates changed partway through the data. Do rates change at a set time (e.g. the start of the year)?
5. **Rentals:** are they charged per term or per month? Is there a deposit? Do rentals continue through the holidays?
6. **Invoice numbers:** OK to switch to a short format like `INV26-0042` for new invoices (old ones unchanged)?
7. **Email:** does Gmail sending work reliably at the moment, or do you often have to re-authorise?
8. **Card payments:** interested enough to open a Stripe account? Would you absorb the fees or pass them on?
9. **Devices:** will the app be used only at the desk, or also on a phone or iPad?
10. **GST:** are you GST-registered? This only matters if so: invoices would need "Tax invoice" wording and a GST number.

---

## Appendix A: proposed data model

New tables and columns (`+` means added to an existing table):

```
terms               id, year, number, start_date, end_date
students          + active, regular_day, regular_time, default_duration, default_rate_cents,
                    billing_name, billing_emails, notes          (or a families table; see Q2)
lessons           + status (scheduled|taught|cancelled|missed_charged|extra), invoice_id, note
invoices          + invoice_number (unique), term_id, issue_date, due_date, pdf_filename,
                    total_cents, revision, voided_at
invoice_lines       id, invoice_id, kind (lesson|rental|extra|credit), lesson_id, rental_id,
                    description, quantity, unit_cents, amount_cents, position
email_log           id, invoice_id, to_address, subject, sent_at, status, error
instruments         id, code, size, maker, serial, value_cents, condition, status, location_note
rentals             id, instrument_id, student_id, start_date, end_date, rate_cents, period, deposit_cents
instrument_events   id, instrument_id, date, kind (handover|repair|note), from_where, to_where, note
payments            id, date, amount_cents, method, payer, reference, source, external_id
payment_allocations payment_id, invoice_id, amount_cents
```

## Appendix B: how this review was done

- I read every file in the repository: about 2,100 lines of Python, templates and CSS, plus the Docker, script and configuration files.
- I ran the app under gunicorn with a fresh database (as the container does), and with Flask's test client against made-up students and lessons, with email disabled.
- I drove the UI in Chromium (via Playwright), clicking the actual buttons and menus, and measured page sizes with two years of made-up data.
- I checked the compose files' variable substitution with `docker compose config`.
- I compared a copy of the Unraid server folder with this repo: the code and configuration files, and the layout and metadata of the generated PDFs. The secrets in it were not opened. I checked the live database with aggregate queries only (counts and formats); nothing from the server copy was added to this repository.
- **Not tested:** real Gmail sending, and the running container itself (it isn't reachable from here).
