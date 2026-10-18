import os
import platform
import shutil
import subprocess
from pathlib import Path


def discover_apps():
    apps = {}
    system = platform.system()

    if system == "Linux":
        roots = [
            Path.home() / ".local/share/applications",
            Path("/usr/local/share/applications"),
            Path("/usr/share/applications"),
            Path("/var/lib/flatpak/exports/share/applications"),
            Path.home() / ".local/share/flatpak/exports/share/applications",
        ]

        for root in roots:
            if not root.exists():
                continue

            for file in root.rglob("*.desktop"):
                try:
                    data = {}
                    in_entry = False
                    for line in file.read_text(errors="ignore").splitlines():
                        if line.strip() == "[Desktop Entry]":
                            in_entry = True
                            continue
                        if line.startswith("[") and line.endswith("]"):
                            in_entry = False
                            continue
                        if in_entry and "=" in line and not line.startswith("#"):
                            key, value = line.split("=", 1)
                            data[key] = value

                    if (
                        data.get("Type") != "Application"
                        or data.get("Hidden") == "true"
                        or data.get("NoDisplay") == "true"
                    ):
                        continue

                    name = data.get("Name", "").strip()
                    if name and data.get("Exec"):
                        apps.setdefault(name.casefold(), {
                            "name": name,
                            "desktop_file": str(file),
                            "platform": "Linux",
                        })
                except OSError:
                    continue

    elif system == "Windows":
        roots = [
            Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
            / "Microsoft/Windows/Start Menu/Programs",
            Path(os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming")))
            / "Microsoft/Windows/Start Menu/Programs",
        ]

        for root in roots:
            if root.exists():
                for file in root.rglob("*.lnk"):
                    apps.setdefault(file.stem.casefold(), {
                        "name": file.stem,
                        "shortcut": str(file),
                        "platform": "Windows",
                    })

    elif system == "Darwin":
        for root in [Path("/Applications"), Path.home() / "Applications"]:
            if root.exists():
                for file in root.glob("*.app"):
                    apps.setdefault(file.stem.casefold(), {
                        "name": file.stem,
                        "app_path": str(file),
                        "platform": "macOS",
                    })

    return sorted(apps.values(), key=lambda app: app["name"].casefold())


def launch_app(query: str):
    query = query.strip().casefold()
    if not query or len(query) > 160:
        raise ValueError("Enter a valid application name.")

    apps = discover_apps()
    exact = [app for app in apps if app["name"].casefold() == query]
    matches = exact or [
        app for app in apps if query in app["name"].casefold()
    ]

    if not matches:
        raise LookupError(f"No installed GUI app matched '{query}'.")

    if len(matches) > 1:
        return {
            "launched": False,
            "ambiguous": True,
            "matches": [app["name"] for app in matches[:10]],
        }

    app = matches[0]
    system = platform.system()

    if system == "Windows":
        os.startfile(app["shortcut"])
    elif system == "Darwin":
        subprocess.Popen(["open", app["app_path"]], start_new_session=True)
    elif system == "Linux":
        desktop_file = Path(app["desktop_file"])
        launcher = shutil.which("gtk-launch")
        desktop_id = desktop_file.name.removesuffix(".desktop")

        if launcher:
            subprocess.Popen(
                [launcher, desktop_id],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        else:
            import shlex
            data = {}
            for line in desktop_file.read_text(errors="ignore").splitlines():
                if "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    data[key] = value

            argv = shlex.split(data.get("Exec", ""))
            argv = [arg for arg in argv if not arg.startswith("%")]
            if not argv:
                raise RuntimeError("Application launcher command is empty.")
            subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
    else:
        raise RuntimeError(f"Unsupported operating system: {system}")

    return {
        "launched": True,
        "app": app["name"],
        "platform": system,
    }
