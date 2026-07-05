# RoleRadar Scheduled Job Ingestion Documentation

This document explains how to configure and run the RoleRadar automatic scheduled job ingestion pipeline. 

The scheduler runs the `scheduled_ingest.sh` wrapper, which invokes `roleradar ingest` against your target queries and maps them to canonical role families (such as `data_engineer`, `ai_ml_engineer`, `software_engineer`, etc.).

---

## Ingestion Modes & Scheduling Options

You can automate this script using either **Systemd User Timers (Recommended)** or **Cron**.

### Option A: Systemd User Timer (Recommended)

Systemd is the recommended choice for local environments (e.g., your laptop or desktop). By setting `Persistent=true` in systemd, if the computer is turned off at the scheduled trigger time (06:00 AM), systemd will detect the missed run and trigger the ingestion **immediately upon the next boot**.

To generate and install the systemd unit files, simply run the setup script:

```bash
cd /home/harry/Documents/Github-Projects/personal-projects/RoleRadar
./setup_systemd.sh
```

This will automatically create:
* `~/.config/systemd/user/roleradar-ingest.service` (defines what commands to run)
* `~/.config/systemd/user/roleradar-ingest.timer` (defines when to run it)

#### Managing Systemd Services

* **Check Timer Status / Next Run:**
  ```bash
  systemctl --user status roleradar-ingest.timer
  ```
* **View Scheduled Timers:**
  ```bash
  systemctl --user list-timers --all
  ```
* **Trigger Run Manually (Right Now):**
  ```bash
  systemctl --user start roleradar-ingest
  ```
* **Check Service Output/Status:**
  ```bash
  systemctl --user status roleradar-ingest
  ```

---

### Option B: Cron Job Setup

If you prefer using traditional `cron` (which only runs if your system is powered on at the exact schedule timestamp):

1. Open your user crontab editor:
   ```bash
   crontab -e
   ```

2. Add the following entry to trigger daily at 06:00 AM:
   ```cron
   0 6 * * * /home/harry/Documents/Github-Projects/personal-projects/RoleRadar/scheduled_ingest.sh >> /home/harry/Documents/Github-Projects/personal-projects/RoleRadar/scheduled_ingest.log 2>&1
   ```

3. Save and close. The cron service will automatically pick it up.

---

## Ingestion Settings & Tuning

The `scheduled_ingest.sh` script is customizable using environment variables. If you want to change default settings without modifying the script, you can export these variables or define them in your `.env` configuration file:

| Variable | Default Value | Description |
|----------|---------------|-------------|
| `ROLERADAR_PYTHON` | `~/venvs/roleradar/bin/python` | Path to the virtual environment python interpreter. |
| `ROLERADAR_RESULTS_PER_PAGE` | `20` | Results requested per API query page. |
| `ROLERADAR_MAX_PAGES` | Dynamic (see below) | Maximum pages to ingest per query. |
| `ROLERADAR_LOCATION` | `Singapore` | Target location filter for ingestion. |

### Dual-Mode Ingestion (Weekly Deep Sync)

To preserve network bandwidth and avoid rate limits, the script automatically toggles fetch depth:
* **Weekdays (Mon–Sat):** Shallow runs (`MAX_PAGES=1`) to discover new postings and record active observations.
* **Sundays:** Deep runs (`MAX_PAGES=5`) to scan deeper pages and backfill any missing items.

You can override this behavior by manually setting `ROLERADAR_MAX_PAGES` (e.g. `ROLERADAR_MAX_PAGES=3`).

---

## Log Monitoring & Troubleshooting

* **Ingestion Output:** 
  All scheduled runs append logs containing timestamps and result summaries to:
  `/home/harry/Documents/Github-Projects/personal-projects/RoleRadar/scheduled_ingest.log`

  Follow logs in real-time:
  ```bash
  tail -f /home/harry/Documents/Github-Projects/personal-projects/RoleRadar/scheduled_ingest.log
  ```

* **Flock Concurrency Lock:**
  If a schedule is running, any concurrent run (manual or scheduled) will exit immediately with:
  `RoleRadar ingestion is already running. Exiting.`
  This prevents database lock conflicts on the SQLite database (`data/roleradar.sqlite3`).

* **Transient Failures & Backoff:**
  API calls to `careers_gov` are built with automatic exponential retries (up to 3 attempts). If your system is waking from sleep and the network is slow to connect, it will wait and retry rather than failing immediately.

* **Desktop Notifications:**
  On Linux systems with `notify-send` available, a successful or failed execution will display a system notification bubble on your desktop.
