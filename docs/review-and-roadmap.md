# Code review and roadmap

*Reviewed September 2026 against `main` @ `32d6a47`. The repo history starts at "Initial public release" (12 Apr 2026), followed by the GHCR workflow (13 Apr 2026).*

Contents: [1 Summary](#1-summary) · [2 What is running on Unraid?](#2-step-zero-what-is-running-on-unraid) · [3 Invoicing this week?](#3-invoicing-this-week-work-around-the-bugs-like-this) · [4 Confirmed bugs](#4-confirmed-bugs) · [5 Root causes](#5-structural-issues-root-causes) · [6 What's good](#6-whats-good-keep-it) · [7 UX proposal](#7-ux-proposal-organise-the-app-around-the-term) · [8 Roadmap](#8-roadmap) · [9 Decisions needed](#9-decisions-needed) · [Appendices](#appendix-a-proposed-data-model)

---

## 1. Summary

- **The foundations are fine, so no rewrite is needed.** Flask, SQLite and server-rendered pages are the right size for a one-teacher studio. The code is already split into routes and services, uses parameterised SQL throughout, and has good email safety switches.
- **I found 21 problems ([§4](#4-confirmed-bugs)).** Most were reproduced by running the app the way Docker does (gunicorn) and clicking through it in a real browser. The "buttons that don't work" have two causes: a form nested inside another form, which makes the top **Mark sent** do nothing (B1), and the actions menu getting clipped by the table (B2).
- **The most dangerous bug for day-to-day use is B5.** On *Create*, if you preview one student, switch to another and press *Preview* again, the page keeps the **first student's lessons**. Pressing *Generate PDF* then bills the second student for them.
- **The biggest structural gap: an invoice is stored only as a total plus a PDF file.** The lines (which lessons, which extras) are never saved. So an invoice can't be edited, re-issued or credited, and the app can't tell which lessons have already been billed. This is why changes after sending are done by hand, and it also blocks payment tracking and rentals. Fixing it is the core of the roadmap.
- **The biggest UX opportunity is a term register.** Today invoices are built one student at a time, so the diary is read once per student. The register would be a students × weeks grid, pre-filled from each student's regular lesson, where you only mark the exceptions. That takes **one pass through the diary, week by week**, and then produces every draft invoice at once ([§7](#7-ux-proposal-organise-the-app-around-the-term)).
- **Do this first:** find out exactly what is running on Unraid and take a backup ([§2](#2-step-zero-what-is-running-on-unraid)). Nothing records which version is deployed, and two compose-file bugs (UTC clock, "unhealthy" status) may be affecting the live container.

---

## 2. Step zero: what is running on Unraid?

Run these in the Unraid terminal. If your container isn't called `music-invoice`, use the name that `docker ps` shows.

```sh
# 1. Which container and image is it, and is it healthy?
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}' | grep -i invoice

# 2. Where does its code come from? A line ending in "-> /app" means the code is a folder on the server (compose setup).
docker inspect music-invoice --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}'

# 3. Fingerprint the code the container is actually running (ignores Windows/Linux line endings).
docker exec music-invoice sh -c 'cd /app && for f in $(find . -type f \( -name "*.py" -o -name "*.html" -o -name "*.css" \) ! -path "*/__pycache__/*" | LC_ALL=C sort); do printf "%s  %s\n" "$(tr -d "\r" < "$f" | md5sum | cut -c1-32)" "$f"; done' | md5sum
```

- **`ab6cfbb6e36a1554d8f32cbd96c8be74`** means the live code is identical to this repo.
- **Anything else** means it differs. Run command 3 again without the final `| md5sum` and compare the output with the list below to see which files changed. Before changing anything, copy the live code into this repo on a branch so that GitHub matches what is actually running.

<details><summary>Per-file fingerprints for this repo (commit 32d6a47)</summary>

```
63e4956946bf45e4642dbccfc5cdf905  ./app.py
11d16abbf62106298deb3650289fced7  ./config.py
cdef21a27850329cf3f94207048fc7fe  ./db.py
a320600c13b6d8ededf1ae1860ec0f2c  ./routes/invoices.py
c88f0acf6fc59f97f01753d1561f7a34  ./routes/lessons.py
b8c8ed51198d9abc129710817e0d406a  ./routes/students.py
188ba2fc4fcd2691c11d075a959dad31  ./services/email_service.py
285abdd3de84e468e36b5d5cb713e285  ./services/invoice_service.py
10df20567b362e6db7a5decb5a3ff17c  ./services/pdf_service.py
e0d73c0f1bd6251e636b16025839011c  ./static/style.css
5dcff581ef0542c7615e9550cac42ba8  ./templates/base.html
5c25bb528b32e850c1bd205df1913729  ./templates/index.html
06d7024cf7f1aa7a3737df47974b0dba  ./templates/invoice_list.html
c75fd73da2757edd6d2e34acb07ca616  ./templates/invoices.html
43d9dd24087a68ff3b7c7b20d4424a48  ./templates/lessons.html
b0ea22ed9950348a97429e7f08e50b78  ./templates/students.html
91ba22fabfc93ed3c2a34f2bba6289e4  ./utils.py
```
</details>

```sh
# 4. Is the container clock on NZ time? If it prints UTC, bug B11 is live.
docker exec music-invoice date

# 5. Database structure and row counts (prints no personal data).
docker exec music-invoice python -c "import sqlite3,os; c=sqlite3.connect(os.environ.get('DB_PATH','/data/music_school.db')); print(*[r[0] for r in c.execute('select sql from sqlite_master where sql is not null')], sep='\n\n'); print({t: c.execute(f'select count(*) from {t}').fetchone()[0] for t in ('students','lessons','invoices')})"
```

**Back up before changing anything.** Copy the whole `data` folder (database and PDFs) and the `secrets` folder somewhere off the server, ideally with the container stopped. The database is the only record of the invoices, and NZ requires business records to be kept for 7 years.

**Also check the Gmail setup.** In Google Cloud Console, go to APIs & Services, then OAuth consent screen. If *Publishing status* is **Testing**, Google expires the refresh token after 7 days and sending fails until you re-authorise. Switching it to **In production** stops that. For your own account you can click through the "unverified app" warning.

---

## 3. Invoicing this week? Work around the bugs like this

Term 3 ended on Friday 25 September, and Term 4 starts on Monday 12 October. Until the fixes land:

| Do this | Because |
|---|---|
| Click **Create** in the menu to start fresh for each student. Don't switch student or dates on a page you have already previewed. | Otherwise the previous student's lessons are kept (B5). |
| Add extra items **last**, just before *Generate PDF*. | Pressing *Preview* again wipes them (B6). |
| Always fill in *Weeks Repeating* (type 1 for a single lesson). | Leaving it blank gives a server error (B3). |
| When editing a lesson time, keep the exact format `2026-07-20 15:30`. | Any other format crashes that student's invoice preview (B4). |
| Set the filter to *Status = Draft* **before** *Select all*, then *Send Selected*. | Otherwise invoices already sent or paid are emailed again, with no confirmation (B9). |
| Don't delete a student who has invoices. | Their invoices disappear from the list (B8). |
| If a **⋯** menu is cut off, widen the filter so that invoice isn't in the last two rows. | The menu gets clipped (B2). |
| Don't rely on *Mark sent* for the top-most draft invoice. | It does nothing, and there's no UI workaround (B1, a small fix). |

---

## 4. Confirmed bugs

B1–B13, B17 and parts of B19 were reproduced or measured against a running copy of the app. B14 and B16 come from reading the code (and, for B14, the Google library's source). B15 needs real Gmail to reproduce. B18, B20 and B21 are gaps or risks rather than defects. **Severity:** 🔴 wrong result or lost data · 🟠 broken feature or crash · 🟡 annoyance, risk or robustness.

| # | | What happens | Where / why | Fix |
|---|---|---|---|---|
| B1 | 🟠 | **Mark sent** on the top-most draft invoice does nothing; it works on the other rows. | `invoice_list.html:193` is a `<form>` inside the bulk-send `<form>` (`:66`). Browsers drop the first nested form tag, so that button submits the bulk-send form instead. | Take the row actions out of the bulk form (e.g. `formaction` on the button). |
| B2 | 🟠 | The **⋯** actions menu is cut off for invoices in the last rows of the table; with one or two invoices listed, it's unusable. | `.table { overflow: hidden }` (`style.css:55`) and the `.table-responsive` wrapper (`invoice_list.html:84`) both clip it. | `data-bs-popper-config='{"strategy":"fixed"}'` on the toggle (tested: fixes it). |
| B3 | 🟠 | Adding a lesson with *Weeks Repeating* blank gives "Internal Server Error". | `lessons.py:18` runs `int("")`. | Default to 1. |
| B4 | 🟠 | Editing a lesson time into any other format (e.g. `2026-07-20T15:30`) makes that student's invoice preview crash. | The edit box is free text (`lessons.html:112`), is saved as typed (`lessons.py:94-108`), and is parsed strictly (`invoices.py:62`). | Date-time picker, normalise on save, clean up existing rows. |
| B5 | 🔴 | *Create*: after a preview, changing the student or dates and pressing *Preview* keeps the previous student's lessons, and *Generate PDF* bills the new student for them. | `invoices.py:33-50` reuses the posted rows whenever `lesson_count > 0`. | Reload from the DB when the student or dates change. |
| B6 | 🟠 | Extra items disappear from the form when *Preview* is pressed again, and the total drops. | `invoices.html:63-76` always renders five empty rows. | Re-fill them from `extras`. |
| B7 | 🟡 | The Lessons filter leaves out lessons on the *end* date. | `lessons.py:59-61` compares `'2026-07-20 15:00' <= '2026-07-20'` as text. | Compare `date(lesson_time)`, as the invoice query already does. |
| B8 | 🔴 | Deleting a student removes their invoices from the invoice list (the rows stay orphaned in the DB) and deletes all their lessons. | `students.py:78-86`, `db.py:28` (`ON DELETE CASCADE`), `invoices.py:195` (inner join). | Archive students instead; block deletion when invoices exist. |
| B9 | 🔴 | *Send Selected Invoices* has no confirmation, and *Select all* includes sent and paid invoices, so one click can re-email every family. | `invoice_list.html:72-81`, `invoices.py:252-305`. | "Send 27 invoices ($8,450)?" confirmation; skip paid invoices; make re-sending an explicit action. |
| B10 | 🟡 | Times mix UTC and NZ time, and the invoice number is recomputed in three places from different clocks. An invoice created on NZ New Year's morning gets a PDF named `INV-2027-…` but is listed and emailed as `INV-2026-…`, so it shows "PDF file is missing" and can't be emailed. | UTC: `db.py:41`, `invoices.py:128`. Local: `invoices.py:290`, `:352`, `pdf_service.py:54`. Recomputed: `invoice_list.html:100`, `invoices.py:400`, `utils.py:4-6`. | Store the invoice number and PDF filename when the invoice is created; use one time convention. |
| B11 | 🟠 | In the compose files, `TZ=${TZ}` and the healthcheck's `${PORT}` are filled in from the **Unraid shell**, not from `.env.prod`. Unless the shell sets them, the container gets `TZ=""` (UTC), so PDFs made before midday (1 pm in summer) show yesterday's *Date Issued*. The healthcheck also calls port 80, so Docker marks the container "unhealthy". | `docker-compose.prod.yml:11-12, 26` (dev file too). Checked with `docker compose config`. | Drop the `environment:` override; use `$${PORT}` or `8000`. |
| B12 | 🟠 | Database setup and migrations never run in Docker. On a fresh database every page errors (`no such table`), and new columns added in future will never reach the live DB. | `init_db()` only runs under `python app.py` (`app.py:43-45`), but the container starts gunicorn (`start.sh`). | Run versioned migrations when the container starts. |
| B13 | 🟡 | `scripts/reset_dev_db.py` builds a database the app can't use: it has no `lessons` table, and `invoices` is missing its dates, total and `created_at`. Even running the app's own `init_db()` afterwards leaves the invoice list broken (`no such column: invoices.start_date`). | `reset_dev_db.py:15-36` | Reuse `init_db()` and seed sample data. |
| B14 | 🟠 | Gmail re-authorisation runs *inside a web request*. If the token is missing or revoked, the app opens a listener on port 8090 and waits (gunicorn kills it after 60 s). Google also redirects the browser to `http://0.0.0.0:8090/`, which can't reach the container. | `email_service.py:26-39`. | Separate "Connect Gmail" step, or SMTP with a Google app password. |
| B15 | 🟡 | *(Not reproduced; needs real Gmail.)* A bulk send runs in one web request. With enough invoices it can pass gunicorn's 60 s timeout (`start.sh:7`), leaving the batch half-sent with an error page. A new Gmail client is also built for every email. | `invoices.py:271-305`, `email_service.py:93`. | Send one invoice per request, with a progress bar. |
| B16 | 🟡 | The email asks payers to use the student's name as the reference; the PDF asks for "name + INV-2026-0042". NZ bank reference fields hold 12 characters, and `INV-2026-0042` has 13. Inconsistent references make payments harder to match. | `invoice_service.py:30`, `pdf_service.py:96`. | One short reference everywhere, e.g. `INV26-0042`. |
| B17 | 🟡 | The Lessons page lists every lesson ever stored, each with two hidden dialogs containing the whole student list. With two years × 30 students that's **16.5 MB of HTML, 4,800 dialogs and 72,000 `<option>` tags** (measured), which will be very slow, especially on a tablet. | `lessons.py:39-65`, `lessons.html:84-153`. | Default to the current term; use one shared edit dialog. |
| B18 | 🟠 | Missing features rather than bugs: you can't undo *Mark paid*, record a part-payment, or void a wrong invoice (it stays a draft and gets caught by *Select all*), and you can't change an invoice once it's generated. | | Covered in Phases 1 and 2. |
| B19 | 🟡 | Smaller robustness issues: text in `<angle brackets>` silently disappears from PDFs (ReportLab markup, `pdf_service.py:58`); long extra-item descriptions don't wrap (`:76`); non-numeric amounts cause server errors (`invoices.py:132,144`); nothing checks that start date ≤ end date; *Preview* with no lessons shows nothing instead of a message; double-clicking *Generate PDF* can create a duplicate invoice; the "(blank)" school filter can't be chosen (`students.html:17-19`). | | Phase 1. |
| B20 | 🟡 | Security is acceptable on a trusted home network, but needs fixing before remote access or card payments. There's no login and no CSRF protection, so any web page open on a device on the LAN could submit the app's forms. The `SECRET_KEY` falls back to a default value. | All routes; `config.py:11`. | Phase 2. |
| B21 | 🟡 | The deployment is ambiguous. The prod compose file builds locally and mounts the source folder over the image (`docker-compose.prod.yml:15`), while GitHub Actions publishes an image that nothing uses, and the UI shows no version. This is why it's unclear what is live. | | One deployment path; version in the footer. |

Minor tidy-ups: the PDF doesn't show the bill-to parent or the business name as text (`BUSINESS_NAME` in `config.py` is unused, and the name is hard-coded in `base.html`). `requirements.txt` is saved as UTF-16: pip copes, but GitHub's dependency tools don't. The Docker image installs `build-essential` and `libpq-dev`, which nothing needs.

---

## 5. Structural issues (root causes)

1. **Invoices don't remember their contents.** Only the student, period and total are saved; the lessons and extras live only inside the PDF. That blocks editing, re-issuing, credits and regenerating a PDF. It also means the app can't tell which lessons are billed, so nothing stops a lesson being billed twice if two invoice periods overlap. **Fix:** an `invoice_lines` table, and lessons that link to the invoice that billed them.
2. **The app has no idea of terms, attendance or a regular timetable.** Lessons are just timestamps. "Term" is approximated by calendar quarters (`utils.py:9-17`; the filter says "Term 1 (Jan–Mar)"). The real 2026 terms are: T1 to 2 Apr, T2 20 Apr–3 Jul, T3 20 Jul–25 Sep, T4 12 Oct–18 Dec. **Fix:** a `terms` table seeded with the [Ministry of Education dates](https://www.education.govt.nz/school/school-terms-and-holiday-dates), a status on each lesson, and each student's regular slot and rate.
3. **Schema changes have no route to production** (B12). **Fix:** numbered migrations, run at start-up and tracked with `PRAGMA user_version`.
4. **Money is stored as floating point, timestamps use mixed zones, and identifiers are derived rather than stored** (B10). **Fix:** integer cents, one timestamp convention, stored invoice numbers.
5. **Slow work happens inside web requests** (B14, B15).
6. **There are no tests.** Every bug above is cheap to pin down with one. **Fix:** pytest with Flask's test client, plus a few browser checks (Playwright) for the button-level bugs, run by CI before the image is published.
7. **There's no single deployment path and no visible version** (B21).

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
- 0.1 Run the [§2](#2-step-zero-what-is-running-on-unraid) checks. If the live code differs from this repo, commit it to a branch first.
- 0.2 Back up `data/` and `secrets/`. Set up a nightly automatic backup (e.g. the Unraid *User Scripts* plugin, keeping 30 days, copied off the server).
- 0.3 Check the container clock and the Gmail consent screen status.

### Phase 1: Stabilise (M): fixes only, no new behaviour
- 1.1 **Test harness:** pytest, Flask test client and a sample-data seed; fix `reset_dev_db.py` (B13). Every fix below comes with a test.
- 1.2 **Deployment:**
  - Run migrations at start-up (B12).
  - Fix the compose TZ and healthcheck settings (B11).
  - Show the version (git commit) in the footer and at `/version`.
  - Pick one deployment path (B21). Recommended: the GHCR image, tagged per commit, with no source folder mounted over it.
  - Save `requirements.txt` as UTF-8, slim down the image, and have CI run the tests before publishing.
- 1.3 **Buttons:** B1, B2.
- 1.4 **Lessons:** B3; B4 (and clean up existing times); B7; open the Lessons page on the current term by default (B17).
- 1.5 **Create invoice:** B5, B6; stop double-submits; show "no lessons found" when there are none.
- 1.6 **Safe sending:** confirmation, skip paid invoices, explicit re-send (B9); one email per request with progress (B15); Gmail authorisation outside web requests (B14).
- 1.7 **Keep history:** archive students instead of deleting them, and keep their invoices visible (B8).
- 1.8 **Stable invoice numbers:** store the invoice number and PDF filename, with consistent timestamps (B10). Optionally switch to a short number like `INV26-0042` and one payment reference everywhere (B16); this needs your OK (Q6).
- 1.9 **Undo:** undo *Mark paid*; void an invoice (part of B18).

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

1. **Unraid check** ([§2](#2-step-zero-what-is-running-on-unraid)): is the live code the same as this repo, or different?
2. **Siblings:** do any families have more than one student? Should they get one invoice per family per term, or one per student?
3. **Billing rules:** do you invoice in advance (start of term, credit missed lessons afterwards) or in arrears (end of term, from the register)? Which absences are charged (e.g. short notice)? How are makeup lessons handled?
4. **Rates:** is there one rate per student? Do rates change at the start of the year?
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
- **Not tested:** real Gmail sending, and the live Unraid deployment, which isn't reachable from here.
