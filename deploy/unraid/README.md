# Running the app on Unraid

Everything lives in `/mnt/user/appdata/music-invoice`:

| Item | What it is |
|---|---|
| `docker-compose.prod.yml` | How the container runs (a copy of the one in this folder). |
| `.env.prod` | Settings: business details, bank account, email switches. Private. |
| `data/` | The database (`music_school.db`) and the invoice PDFs (`invoices_pdfs/`). |
| `secrets/` | Gmail credentials (`credentials.json`, `token.json`). Private. |
| `scripts/` | `backup.sh`, `update.sh` and `tidy-server.sh` from this folder. |

The app itself comes from the GitHub image `ghcr.io/lappynz/music_invoicing_app`. A new image is published
(after the tests pass) whenever something is merged into `main`. The server only changes when you run
`update.sh`, unless you've set up automatic container updates (e.g. Watchtower).

The version the server is running is shown at the bottom right of every page, and at `http://<server>:8085/version`.

## One-time setup

Run these in the Unraid terminal (the `>_` icon at the top right of the web UI).

1. **Get the scripts:**

   ```sh
   mkdir -p /mnt/user/appdata/music-invoice/scripts
   cd /mnt/user/appdata/music-invoice/scripts
   for f in backup.sh update.sh tidy-server.sh docker-compose.prod.yml README.md; do
     curl -fsSLO "https://raw.githubusercontent.com/LappyNZ/Music_Invoicing_App/main/deploy/unraid/$f"
   done
   ```

2. **Take a first backup:** `bash /mnt/user/appdata/music-invoice/scripts/backup.sh`
   It should end with `Backup OK: /mnt/user/backups/music-invoice/daily/...`.

3. **Tidy the folder.** First see what it would do, then do it:

   ```sh
   bash /mnt/user/appdata/music-invoice/scripts/tidy-server.sh
   bash /mnt/user/appdata/music-invoice/scripts/tidy-server.sh --apply
   ```

   This moves the leftovers from the old setup into `old-YYYYMMDD/` (nothing is deleted) and installs the
   updated `docker-compose.prod.yml`. The running app isn't affected. Delete the `old-...` folder once
   everything has worked for a few weeks.

4. **Back up every night:** install the **User Scripts** plugin (Apps tab) if you don't have it. Then go to
   Settings, User Scripts, and click *Add New Script*. Call it `music-invoice-backup`, click its cog, then
   *Edit Script*, and make it:

   ```sh
   #!/bin/bash
   bash /mnt/user/appdata/music-invoice/scripts/backup.sh
   ```

   Set its schedule to *Scheduled Daily*. If a backup ever fails you'll get an Unraid notification.
   To get those by email or on your phone, set it up under Settings, Notification Settings.

## Updating to a new version

```sh
bash /mnt/user/appdata/music-invoice/scripts/update.sh
```

It backs up first, downloads the newest image, restarts the app with it, waits until it reports healthy,
and prints the version it's running. After merging changes on GitHub, wait for the green tick on the
repository's Actions tab (a few minutes) before updating. Otherwise there's nothing new to download yet.

## Rolling back to an earlier version

Every published version also has a tag named after its commit, e.g. `sha-32d6a47`. The tags are listed on
the package page at https://github.com/LappyNZ/Music_Invoicing_App/pkgs/container/music_invoicing_app.

1. In `docker-compose.prod.yml`, change `music_invoicing_app:latest` to the tag you want,
   e.g. `music_invoicing_app:sha-32d6a47`.
2. Run:

   ```sh
   cd /mnt/user/appdata/music-invoice
   docker compose -f docker-compose.prod.yml up -d
   ```

3. To go back to the newest version, change the tag back to `latest` and run `update.sh`.

Older versions run fine on a database that a newer version has upgraded. A few things behave the old way
while rolled back:

- Versions before September 2026 don't know about **void** invoices and show them as Draft, so don't
  bulk-send while rolled back to one of those.
- Invoices with the short kind of number, like `INV26-0128`, have their PDF saved under that name. Older
  versions look for the old kind of name, so they say "PDF file is missing" and can't email those invoices.
  Nothing is lost: it works again after updating.
- Older versions don't know about **archived** students. They're offered for new lessons and invoices
  again, and Delete is the old one that hides a student's invoices. Don't delete students while rolled back.

## Connecting Gmail again

The app sends email through Gmail, using a sign-in kept in `secrets/token.json`. If Google cancels it
(after a password change, for example, or every 7 days while the Google Cloud project is in *Testing*),
sending stops at the first invoice with "Gmail isn't connected", and nothing more is sent. To connect again:

1. In the Unraid terminal, run:

   ```sh
   docker exec -it music-invoice python -m gmail_auth
   ```

2. It prints a long Google link. Open it in a browser on any computer or phone, and sign in with the
   address the invoices are sent from. Keep the terminal open.
3. Allow access. If Google says it hasn't verified the app, choose *Advanced* and continue: it's your own app.
   The browser then shows an error such as "This site can't be reached" for a `localhost` address.
   That's expected.
4. Copy the whole address from the browser's address bar, paste it into the terminal and press Enter.
   It should say "Gmail is connected".

Then send the invoices that didn't go (set the list's Status filter to Draft to find them).

## One-off: bringing back deleted students

Deleting a student used to hide their invoices. The invoice list now shows those invoices as
"Deleted student #7". The October 2025 copies of the database that `tidy-server.sh` moved into
`old-YYYYMMDD/data/` still have those students, and a tool in the app can bring them back as archived
students, so their invoices show their names again. It only brings back a student when that copy also
has one of their invoices, so it can't attach the wrong name. Their lessons aren't brought back
(the invoices keep their totals).

```sh
bash /mnt/user/appdata/music-invoice/scripts/backup.sh      # a backup first
cd /mnt/user/appdata/music-invoice
ls old-*/data/                                               # the copy is music_school.db.BAK.2025-10-02-1836
cp old-*/data/music_school.db.BAK.2025-10-02-1836 data/restore-source.db
docker exec music-invoice python -m tools.restore_deleted_students /data/restore-source.db           # shows what it would do
docker exec music-invoice python -m tools.restore_deleted_students /data/restore-source.db --apply   # does it
rm data/restore-source.db
```

The first run lists each student it found and changes nothing. After `--apply` they're on the Students
page under *Show: Archived*.

## Where the backups are, and what's in them

`/mnt/user/backups/music-invoice/daily/` holds one `music-invoice_<date>_<time>.tar.gz` per night, kept for 30
days. The one from the 1st of each month is also copied to `monthly/` and kept for two years.

Each archive holds everything needed to rebuild the app: the database, the invoice PDFs,
`.env.prod`, `docker-compose.prod.yml` and the Gmail credentials. That's why the files are readable by
root only. Please also keep a copy **off the server** (a fire, theft or a failed array would take the
backups with it). For example, copy the newest archive to a USB drive or your PC every so often, or
set up an rclone User Script to cloud storage. IRD requires business records to be kept for 7 years.

## Restoring from a backup

If the database is damaged, or you need to undo a mistake, restore the newest good backup:

```sh
cd /mnt/user/appdata/music-invoice
ls -t /mnt/user/backups/music-invoice/daily/            # pick one; newest first
BACKUP=/mnt/user/backups/music-invoice/daily/music-invoice_2026-10-01_0440.tar.gz   # <- the one you picked

docker compose -f docker-compose.prod.yml stop
cp -a data "data.before-restore-$(date +%Y%m%d-%H%M)"   # keep what's there now, just in case
mkdir -p /tmp/restore && tar -xzf "$BACKUP" -C /tmp/restore
cp /tmp/restore/music_school.db data/music_school.db && rm -f data/music_school.db-journal
cp -a /tmp/restore/data/invoices_pdfs/. data/invoices_pdfs/
docker compose -f docker-compose.prod.yml up -d
rm -rf /tmp/restore
```

Then open the app and check the newest invoices are the ones you expect. `.env.prod` and
`secrets/` are in the archive too, if those ever need restoring. Delete the `data.before-restore-...`
folder once you're happy.

## If something goes wrong

- **The app won't start, or `update.sh` says it isn't healthy:** `docker logs music-invoice` shows why.
  Roll back (above) to get going again.
- **`update.sh` says the container wasn't started this way:** it was started from another compose file or the
  Unraid Docker tab. The script stops rather than guess; update it the way it was started.
- **A backup failed:** the notification says why, and so does the script's log in User Scripts.
- **Sending stops with "Gmail isn't connected":** see [Connecting Gmail again](#connecting-gmail-again).
