
import json
import logging
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "monitor_targets.json"
STATE_DIR = Path.home() / ".local" / "state" / "vantex"
STATE_DIR.mkdir(parents=True, exist_ok=True)
STATUS_PATH = STATE_DIR / "status.json"

logging.basicConfig(
    filename=STATE_DIR / "monitor.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

CPU_LIMIT = 90
RAM_LIMIT = 90
DISK_LIMIT = 90

last_alert = {}
active_issues = set()
failure_counts = {}
recovery_counts = {}


def notify(title: str, message: str) -> None:
    logging.warning("%s: %s", title, message)

    if shutil.which("notify-send"):
        try:
            subprocess.run(
                ["notify-send", "--urgency=critical", title, message],
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            logging.exception("Desktop notification failed")


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        config = json.load(file)

    settings = config.get("settings", {})
    settings.setdefault("check_interval_seconds", 15)
    settings.setdefault("failure_threshold", 2)
    settings.setdefault("recovery_threshold", 1)
    settings.setdefault("alert_cooldown_seconds", 300)
    settings.setdefault("request_timeout_seconds", 8)

    if settings["check_interval_seconds"] < 1:
        raise ValueError("Check interval must be at least 1 second")
    if settings["failure_threshold"] < 1:
        raise ValueError("Failure threshold must be at least 1")
    if settings["recovery_threshold"] < 1:
        raise ValueError("Recovery threshold must be at least 1")

    return config


def update_health(
    key: str,
    healthy: bool,
    description: str,
    config: dict,
) -> None:
    settings = config["settings"]
    failure_limit = settings["failure_threshold"]
    recovery_limit = settings["recovery_threshold"]
    cooldown = settings["alert_cooldown_seconds"]
    now = time.monotonic()

    if healthy:
        failure_counts[key] = 0
        recovery_counts[key] = recovery_counts.get(key, 0) + 1

        if key in active_issues and recovery_counts[key] >= recovery_limit:
            active_issues.remove(key)
            recovery_counts[key] = 0
            logging.info("RECOVERED: %s", description)
            notify("VANTEX: Service recovered", description)
        return

    recovery_counts[key] = 0
    failure_counts[key] = failure_counts.get(key, 0) + 1

    if failure_counts[key] < failure_limit:
        logging.warning(
            "Failure %s/%s: %s",
            failure_counts[key],
            failure_limit,
            description,
        )
        return

    is_new_issue = key not in active_issues
    active_issues.add(key)

    if is_new_issue or now - last_alert.get(key, -float("inf")) >= cooldown:
        notify("VANTEX Emergency Alert", description)
        last_alert[key] = now


def check_website(site: dict, config: dict) -> None:
    name = site.get("name", "Unnamed website")
    url = site.get("url", "")
    key = f"website:{name}"

    if not site.get("enabled", True):
        return

    if not url.startswith(("http://", "https://")):
        update_health(key, False, f"{name}: invalid HTTP(S) URL", config)
        return

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "VANTEX-Monitor/1.0"},
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=config["settings"]["request_timeout_seconds"],
        ) as response:
            status = response.status

        expected = site.get("expected_status", [200])
        healthy = status in expected
        detail = f"{name}: HTTP {status} at {url}"

    except urllib.error.HTTPError as error:
        healthy = error.code in site.get("expected_status", [200])
        detail = f"{name}: HTTP {error.code} at {url}"

    except (urllib.error.URLError, TimeoutError, OSError) as error:
        healthy = False
        detail = f"{name}: unreachable ({error})"

    update_health(key, healthy, detail, config)


def process_matches(app: dict) -> bool:
    expected_name = app.get("process_name", "").casefold()
    expected_cmdline = app.get("cmdline_contains", "").casefold()

    if not expected_name and not expected_cmdline:
        return False

    for process in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (process.info.get("name") or "").casefold()
            command = " ".join(process.info.get("cmdline") or []).casefold()

            if expected_name and name == expected_name:
                return True
            if expected_cmdline and expected_cmdline in command:
                return True

        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    return False


def check_application(app: dict, config: dict) -> None:
    if not app.get("enabled", True):
        return

    name = app.get("name", "Unnamed application")
    key = f"application:{name}"

    try:
        running = process_matches(app)
    except Exception:
        logging.exception("Could not check application: %s", name)
        return

    detail = (
        f"{name}: expected process is running"
        if running
        else f"{name}: expected process was not found"
    )
    update_health(key, running, detail, config)


def check_system(config: dict) -> None:
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    cpu = psutil.cpu_percent(interval=1)

    for name, value, limit in (
        ("CPU", cpu, CPU_LIMIT),
        ("RAM", memory.percent, RAM_LIMIT),
        ("Disk", disk.percent, DISK_LIMIT),
    ):
        update_health(
            f"system:{name}",
            value < limit,
            f"{name} usage is {value:.1f}% (threshold: {limit}%)",
            config,
        )

    logging.info(
        "CPU=%.1f%% RAM=%.1f%% DISK=%.1f%%",
        cpu,
        memory.percent,
        disk.percent,
    )


def write_status(config: dict) -> None:
    """Publish a read-only snapshot of configured monitor targets."""
    snapshot = {
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "monitor": "running",
        "system": {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "ram_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage("/").percent,
        },
        "websites": [],
        "applications": [],
        "active_incidents": sorted(active_issues),
    }

    for site in config.get("websites", []):
        if not site.get("enabled", True):
            continue

        key = f"website:{site.get('name', 'Unnamed website')}"
        snapshot["websites"].append({
            "name": site.get("name", "Unnamed website"),
            "url": site.get("url", ""),
            "status": "down" if key in active_issues else (
                "up" if failure_counts.get(key, 0) == 0 else "checking"
            ),
        })

    for app in config.get("applications", []):
        if not app.get("enabled", True):
            continue

        key = f"application:{app.get('name', 'Unnamed application')}"
        snapshot["applications"].append({
            "name": app.get("name", "Unnamed application"),
            "status": "down" if key in active_issues else (
                "running" if failure_counts.get(key, 0) == 0 else "checking"
            ),
        })

    temporary = STATUS_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(snapshot, indent=2),
        encoding="utf-8",
    )
    temporary.replace(STATUS_PATH)



def monitor() -> None:
    logging.info("VANTEX Emergency Engine started")

    while True:
        started = time.monotonic()

        try:
            config = load_config()
            check_system(config)

            for site in config.get("websites", []):
                try:
                    check_website(site, config)
                except Exception:
                    logging.exception(
                        "Website check failed unexpectedly: %s",
                        site.get("name", "unknown"),
                    )

            for app in config.get("applications", []):
                try:
                    check_application(app, config)
                except Exception:
                    logging.exception(
                        "Application check failed unexpectedly: %s",
                        app.get("name", "unknown"),
                    )

            # Publish the latest monitoring snapshot for the dashboard.
            write_status(config)

        except Exception:
            logging.exception("Emergency monitoring cycle failed")

        interval = 15
        try:
            interval = load_config()["settings"]["check_interval_seconds"]
        except Exception:
            logging.exception("Could not read monitoring interval")

        elapsed = time.monotonic() - started
        time.sleep(max(1, interval - elapsed))


if __name__ == "__main__":
    try:
        monitor()
    except KeyboardInterrupt:
        logging.info("VANTEX Emergency Engine stopped")
