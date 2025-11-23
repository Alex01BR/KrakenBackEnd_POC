"""
Scheduler service - runs as a separate process/container.
This script reads devices from the database and registers per-device APScheduler jobs.
"""
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import time
import logging
import threading

import models
import crud
from database import get_db, create_tables
import notifications
import os
import json

# Global check frequency (days). Can be set with env var CHECK_FREQUENCY_DAYS, supports decimals (e.g. 0.0035).
CHECK_FREQUENCY_DAYS = float(os.environ.get('CHECK_FREQUENCY_DAYS', '0.002'))

# Logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("kraken_scheduler")

# Per-device locks to avoid parallel execution of the same device job within this process
device_locks = {}
device_locks_lock = threading.Lock()

def get_device_lock(device_id: int):
    with device_locks_lock:
        if device_id not in device_locks:
            device_locks[device_id] = threading.Lock()
        return device_locks[device_id]

def create_device_job_function(device_id: int, alert_days: float, user_name: str = None, scheduler: BackgroundScheduler = None):
    device_lock = get_device_lock(device_id)

    def job(alert_days_param=None):
        # Allow an optional alert_days passed via job kwargs; fall back to captured value
        # Here: alert_days is the notification window (in days). The check frequency
        # is controlled by module-level CHECK_FREQUENCY_DAYS (supports decimal values).
        _alert_window = float(alert_days_param) if alert_days_param is not None else float(alert_days)
        if not device_lock.acquire(blocking=False):
            logger.debug(f"⚠️ [JOB DEVICE {device_id}] Job already running, skipping this run")
            return
        try:
            logger.info(f"⏰ [JOB DEVICE {device_id}] Running check (check_frequency_days={CHECK_FREQUENCY_DAYS}, alert_window_days={_alert_window})")
            db = next(get_db())
            try:
                device = db.query(models.Device).filter(models.Device.id == device_id).first()
                if not device:
                    logger.warning(f"⚠️ [JOB DEVICE {device_id}] Device not found")
                    return
                # Check if the device's check frequency changed in the DB; if so, reschedule this job immediately
                device_db_alert = device.alert_days if device.alert_days else 7
                try:
                    if abs(float(device_db_alert) - float(_alert_window)) > 1e-9:
                        logger.info(f"  🔁 Detected alert window change for device {device_id}: {_alert_window} -> {device_db_alert}; updating job metadata")
                        if scheduler is not None:
                            job_id = f"device_{device_id}"
                            existing = scheduler.get_job(job_id)
                            old_next = existing.next_run_time if existing is not None else None
                            new_display = f"{device_db_alert} day(s)"
                            try:
                                # remove and re-add with SAME trigger (1 day) but updated kwargs, preserving next_run_time
                                if existing is not None:
                                    scheduler.remove_job(job_id)
                                new_job_func = create_device_job_function(device_id, device_db_alert, device.user_name, scheduler)
                                if old_next:
                                    scheduler.add_job(new_job_func, 'interval', id=job_id, max_instances=1, replace_existing=True, next_run_time=old_next, kwargs={'alert_days_param': device_db_alert}, days=CHECK_FREQUENCY_DAYS)
                                else:
                                    scheduler.add_job(new_job_func, 'interval', id=job_id, max_instances=1, replace_existing=True, kwargs={'alert_days_param': device_db_alert}, days=CHECK_FREQUENCY_DAYS)
                                logger.info(f"  🔁 Updated job metadata for device {device_id} - notify_window={new_display} (preserved next_run={old_next})")
                            except Exception:
                                logger.exception(f"Failed to update job metadata for device {device_id} from job run")

                        # update local _alert_window so the running job uses the new value
                        _alert_window = device_db_alert
                except Exception:
                    logger.exception(f"Error checking/updating alert window for device {device_id}")

                # Diagnostic logs: show notification window used for this run (comes from device)
                from datetime import datetime, timedelta as _td
                now = datetime.utcnow()
                notify_window = float(_alert_window)
                cutoff = now + _td(days=notify_window)
                logger.info(f"  [DIAG] now={now.isoformat()} cutoff={cutoff.isoformat()} (notify_window_days={notify_window})")

                # Notify items expiring within device-defined notify window
                pairs = crud.get_devices_with_expiring_items(db, within_days=notify_window)
                # Log what pairs returned for debugging
                try:
                    found = 0
                    for d, items in pairs:
                        if d.id == device_id:
                            found = len(items)
                            logger.info(f"  [DIAG] Device {device_id} - found {found} expiring item(s): {[i.expiration_date.isoformat() if i.expiration_date else None for i in items]}")
                    if found == 0:
                        # also log that we examine pairs len
                        logger.info(f"  [DIAG] Device {device_id} - no expiring items found in pairs (total devices with items returned: {len(pairs)})")
                except Exception:
                    logger.exception("Error while logging diagnostic pairs for device")
                device_pairs = [(d, items) for d, items in pairs if d.id == device_id]

                if device_pairs:
                    for _, items in device_pairs:
                        logger.info(f"  📦 Found {len(items)} upcoming expiring items for device {device.user_name or device.id}")
                        title = "⚠️ Itens próximos do vencimento"
                        item_names = ", ".join([it.name for it in items[:3]])
                        if len(items) > 3:
                            body = f"{item_names} e mais {len(items) - 3}. Confira seus itens!"
                        else:
                            body = f"{item_names}. Verifique a validade!"

                        logger.info(f"📤 Sending push to {device.push_token[:20]}...")
                        result = notifications.send_expo_push(device.push_token, title, body, {})
                        if result.get('ok'):
                            logger.info(f"✅ Notification sent for device {device_id}")
                        else:
                            logger.error(f"❌ Failed to send notification: {result}")
                else:
                    logger.debug(f"ℹ️ [JOB DEVICE {device_id}] No upcoming expirations")
            except Exception as e:
                logger.exception(f"Error processing device {device_id}: {e}")
            finally:
                db.close()
        finally:
            device_lock.release()

    return job


def ensure_job_for_device(scheduler: BackgroundScheduler, device_id: int):
    """Ensure a job exists for a single device and is configured with current device.alert_days."""
    db = next(get_db())
    try:
        device = db.query(models.Device).filter(models.Device.id == device_id).first()
        if not device:
            logger.warning(f"Cannot ensure job for device {device_id}: not found in DB")
            return
        alert_days = device.alert_days if device.alert_days else 7
        # alert_days is notification window; check frequency is controlled by CHECK_FREQUENCY_DAYS
        trigger_kwargs = {'days': CHECK_FREQUENCY_DAYS}
        display = f"check every {CHECK_FREQUENCY_DAYS} day(s)"

        job_id = f"device_{device.id}"
        existing = scheduler.get_job(job_id)
        job_func = create_device_job_function(device.id, alert_days, device.user_name, scheduler)
        if existing:
            # compare kwargs stored
            existing_alert = None
            try:
                existing_alert = existing.kwargs.get('alert_days_param') if hasattr(existing, 'kwargs') else None
            except Exception:
                existing_alert = None

            if existing_alert is None:
                # normalize by re-adding job with same trigger and adding kwargs
                try:
                    old_next = existing.next_run_time
                    # preserve trigger interval by re-adding with same trigger if possible
                    trig = existing.trigger
                    existing_seconds = None
                    if hasattr(trig, 'interval') and trig.interval is not None:
                        existing_seconds = trig.interval.total_seconds()
                    scheduler.remove_job(job_id)
                    if existing_seconds is not None:
                        # preserve existing interval but add kwargs; convert seconds to interval
                        scheduler.add_job(job_func, 'interval', seconds=int(existing_seconds), id=job_id, max_instances=1, replace_existing=True, next_run_time=old_next, kwargs={'alert_days_param': alert_days})
                    else:
                        # default to configured CHECK_FREQUENCY_DAYS and add kwargs
                        scheduler.add_job(job_func, 'interval', id=job_id, max_instances=1, replace_existing=True, next_run_time=old_next, kwargs={'alert_days_param': alert_days}, days=CHECK_FREQUENCY_DAYS)
                    logger.info(f"  🔧 Normalized job metadata for device {device.id} - {display} (preserved next_run={old_next})")
                except Exception:
                    logger.exception(f"Failed to normalize job for device {device.id}")
            else:
                try:
                    if abs(float(existing_alert) - float(alert_days)) > 1e-9:
                        old_next = existing.next_run_time
                        scheduler.remove_job(job_id)
                        scheduler.add_job(job_func, 'interval', id=job_id, max_instances=1, replace_existing=True, next_run_time=old_next, kwargs={'alert_days_param': alert_days}, **trigger_kwargs)
                        logger.info(f"  🔁 Rescheduled device {device.id} - {display} (preserved next_run={old_next})")
                except Exception:
                    logger.exception(f"Failed to reschedule job for device {device.id}")
        else:
            # add new job
            try:
                scheduler.add_job(job_func, 'interval', id=job_id, max_instances=1, replace_existing=True, kwargs={'alert_days_param': alert_days}, **trigger_kwargs)
                logger.info(f"  ✅ Scheduled device {device.id} - {display}")
                # immediate run to pick up state
                threading.Thread(target=job_func, args=(alert_days,), daemon=True).start()
                logger.info(f"  ▶️ Triggered immediate check for device {device.id}")
            except Exception:
                logger.exception(f"Failed to schedule job for device {device.id}")
    finally:
        db.close()


def listen_for_device_changes(scheduler: BackgroundScheduler):
    """Listen to Postgres NOTIFY channel 'device_changes' and reschedule affected device jobs."""
    try:
        import psycopg2
        import select
        dsn = os.environ.get('DATABASE_URL')
        if not dsn:
            logger.warning("DATABASE_URL not set; cannot listen for device_changes")
            return
        conn = psycopg2.connect(dsn)
        conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()
        cur.execute("LISTEN device_changes;")
        logger.info("Listening for Postgres NOTIFY on channel 'device_changes'...")
        while True:
            if select.select([conn], [], [], 5) == ([], [], []):
                continue
            conn.poll()
            while conn.notifies:
                notify = conn.notifies.pop(0)
                payload = notify.payload
                try:
                    data = json.loads(payload)
                    device_id = data.get('device_id')
                    logger.info(f"Received device_changes notify for device {device_id}")
                    if device_id is not None:
                        ensure_job_for_device(scheduler, int(device_id))
                except Exception:
                    logger.exception("Error handling device_changes notify")
    except Exception:
        logger.exception("Listener for device_changes stopped")

def schedule_all_devices(scheduler: BackgroundScheduler):
    db = next(get_db())
    try:
        devices = db.query(models.Device).all()
        logger.info(f"📱 Scheduling {len(devices)} devices...")
        for device in devices:
            # Debug: list current job ids in scheduler
            try:
                current_job_ids = [j.id for j in scheduler.get_jobs()]
            except Exception:
                current_job_ids = []
            logger.debug(f"  [DEBUG] current scheduler job ids: {current_job_ids}")
            alert_days = device.alert_days if device.alert_days else 7
            # alert_days is treated as notification window (days). Frequency for checks is fixed at 1 day.
            job_func = create_device_job_function(device.id, alert_days, device.user_name, scheduler)
            job_id = f"device_{device.id}"
            # Check frequency controlled by CHECK_FREQUENCY_DAYS (can be decimal)
            trigger_kwargs = {'days': CHECK_FREQUENCY_DAYS}
            display = f"check every {CHECK_FREQUENCY_DAYS} day(s)"
            desired_seconds = 24 * 3600

            existing = scheduler.get_job(job_id)
            if existing:
                # Compare existing job interval (if available) with desired interval.
                try:
                    trig = existing.trigger
                    existing_seconds = None
                    # IntervalTrigger exposes a timedelta in .interval
                    if hasattr(trig, 'interval') and trig.interval is not None:
                        existing_seconds = trig.interval.total_seconds()

                    # If we can compare intervals, reschedule only when different.
                    # Prefer comparing stored job kwargs (alert_days_param) if present
                    job_kwargs_alert = None
                    try:
                        job_kwargs_alert = existing.kwargs.get('alert_days_param') if hasattr(existing, 'kwargs') else None
                    except Exception:
                        job_kwargs_alert = None

                    if job_kwargs_alert is not None:
                        # Compare stored alert_days with the device value directly
                        try:
                            job_alert_float = float(job_kwargs_alert)
                        except Exception:
                            job_alert_float = None

                        if job_alert_float is None or abs(job_alert_float - alert_days) > 1e-9:
                            old_next = existing.next_run_time
                            scheduler.remove_job(job_id)
                            # create new job with same next_run_time to avoid postponing; trigger stays daily
                            job_func = create_device_job_function(device.id, alert_days, device.user_name, scheduler)
                            try:
                                if old_next:
                                    scheduler.add_job(job_func, 'interval', id=job_id, max_instances=1, replace_existing=True, next_run_time=old_next, kwargs={'alert_days_param': alert_days}, days=CHECK_FREQUENCY_DAYS)
                                else:
                                    scheduler.add_job(job_func, 'interval', id=job_id, max_instances=1, replace_existing=True, kwargs={'alert_days_param': alert_days}, days=CHECK_FREQUENCY_DAYS)
                                logger.info(f"  🔁 Rescheduled device {device.id} - {display} (preserved next_run={old_next})")
                                # trigger an immediate run so updated alert_days takes effect right away
                                try:
                                    threading.Thread(target=job_func, args=(alert_days,), daemon=True).start()
                                    logger.info(f"  ▶️ Triggered immediate check for device {device.id} after reschedule")
                                except Exception:
                                    logger.exception(f"Failed to trigger immediate check for device {device.id} after reschedule")
                            except Exception:
                                logger.exception(f"Failed to reschedule job for device {device.id}")
                        else:
                            logger.debug(f"  ↩️ Job for device {device.id} already up-to-date (id={job_id})")
                    else:
                        # Fallback: if we couldn't find job kwargs, try to compare trigger interval
                        if existing_seconds is not None:
                            # Allow a small tolerance (1 second) to avoid noise
                            if abs(existing_seconds - desired_seconds) > 1:
                                old_next = existing.next_run_time
                                scheduler.remove_job(job_id)
                                # create new job with same next_run_time to avoid postponing; trigger stays daily
                                job_func = create_device_job_function(device.id, alert_days, device.user_name, scheduler)
                                try:
                                    if old_next:
                                        scheduler.add_job(job_func, 'interval', id=job_id, max_instances=1, replace_existing=True, next_run_time=old_next, days=CHECK_FREQUENCY_DAYS)
                                    else:
                                        scheduler.add_job(job_func, 'interval', id=job_id, max_instances=1, replace_existing=True, days=CHECK_FREQUENCY_DAYS)
                                    logger.info(f"  🔁 Rescheduled device {device.id} - {display} (preserved next_run={old_next})")
                                    try:
                                        threading.Thread(target=job_func, daemon=True).start()
                                        logger.info(f"  ▶️ Triggered immediate check for device {device.id} after reschedule")
                                    except Exception:
                                        logger.exception(f"Failed to trigger immediate check for device {device.id} after reschedule")
                                except Exception:
                                    logger.exception(f"Failed to reschedule job for device {device.id}")
                            else:
                                logger.debug(f"  ↩️ Job for device {device.id} already up-to-date (id={job_id})")
                        else:
                            logger.debug(f"  ⚠️ Could not determine existing interval for job {job_id}; skipping")
                except Exception:
                    logger.exception(f"Error while inspecting existing job {job_id}")
                continue
            else:
                # Pass alert_days as job kwargs so we can compare it later without converting intervals
                scheduler.add_job(job_func, 'interval', id=job_id, max_instances=1, replace_existing=True, kwargs={'alert_days_param': alert_days}, **trigger_kwargs)
                logger.info(f"  ✅ Scheduled device {device.id} - {display}")
                # Run once immediately to process any items that are already within the alert window
                try:
                    threading.Thread(target=job_func, args=(alert_days,), daemon=True).start()
                    logger.info(f"  ▶️ Triggered immediate check for device {device.id}")
                except Exception:
                    logger.exception(f"Failed to trigger immediate check for device {device.id}")
    finally:
        db.close()

def main():
    logger.info("Starting scheduler service...")
    create_tables()

    scheduler = BackgroundScheduler()
    # Initialize all device jobs on startup
    schedule_all_devices(scheduler)
    # Periodically reconcile jobs with DB so changes to alert_days are picked up
    scheduler.add_job(lambda: schedule_all_devices(scheduler), 'interval', minutes=1, id='reconcile_jobs', replace_existing=True)
    # Start listener thread to react immediately when backend notifies device_changes
    listener_thread = threading.Thread(target=listen_for_device_changes, args=(scheduler,), daemon=True)
    listener_thread.start()
    scheduler.start()

    try:
        # Keep running; scheduler runs in background threads
        while True:
            time.sleep(5)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down scheduler...")
        scheduler.shutdown()

if __name__ == '__main__':
    main()
