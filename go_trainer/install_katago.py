"""Download a self-contained KataGo build into ./engine.

KataGo does not publish macOS binaries, so this fetches Homebrew's prebuilt
bottles (KataGo plus its shared-library dependencies) straight from Homebrew's
package registry. Homebrew itself is not needed. The bottles are unpacked into
./engine/homebrew, their library references are rewritten to point at each
other with @loader_path, and the binaries are ad-hoc re-signed.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ENGINE_DIR = APP_DIR / "engine"
PREFIX = ENGINE_DIR / "homebrew"
KATAGO_LINK = ENGINE_DIR / "katago"
FORMULA_API = "https://formulae.brew.sh/api/formula/{}.json"
# Homebrew's public registry accepts this anonymous token for downloads.
REGISTRY_HEADERS = {"Authorization": "Bearer QQ==", "User-Agent": "go-trainer"}

# Bottle tag codenames by macOS major version, newest first.
MACOS_CODENAMES = (
    (27, "golden_gate"),
    (26, "tahoe"),
    (15, "sequoia"),
    (14, "sonoma"),
    (13, "ventura"),
    (12, "monterey"),
)


class InstallError(RuntimeError):
    pass


def _fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "go-trainer"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def _bottle_tags() -> list[str]:
    """Bottle tags this Mac can run, best match first."""
    major = int(platform.mac_ver()[0].split(".")[0])
    arm = platform.machine() == "arm64"
    tags = [
        f"arm64_{name}" if arm else name
        for version, name in MACOS_CODENAMES
        if version <= major
    ]
    return tags + ["all"]


def _resolve(name: str, seen: dict[str, dict]) -> None:
    if name in seen:
        return
    formula = _fetch_json(FORMULA_API.format(name))
    seen[name] = formula
    for dependency in formula.get("dependencies", []):
        _resolve(dependency, seen)


def _download(url: str, destination: Path, sha256: str, label: str) -> None:
    request = urllib.request.Request(url, headers=REGISTRY_HEADERS)
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        last_shown = -1
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            if total:
                percent = done * 100 // total
                if percent != last_shown and percent % 5 == 0:
                    print(f"\r  {label}: {percent}% of {total / 1e6:.0f} MB", end="", flush=True)
                    last_shown = percent
    print()
    if digest.hexdigest() != sha256:
        raise InstallError(f"checksum mismatch for {label}")


def _extract(archive: Path, name: str) -> Path:
    """Unpack a bottle into PREFIX/<name>/<version>, skipping bundled networks."""
    with tarfile.open(archive) as tar:
        members = []
        for member in tar.getmembers():
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts:
                raise InstallError(f"unsafe path in {name} bottle: {member.name}")
            # KataGo's bottle ships several large networks we never use.
            if member.name.endswith((".bin.gz", ".txt.gz")):
                continue
            members.append(member)
        if hasattr(tarfile, "data_filter"):
            tar.extractall(PREFIX, members=members, filter="data")
        else:
            tar.extractall(PREFIX, members=members)
    versions = sorted((PREFIX / name).iterdir())
    if len(versions) != 1:
        raise InstallError(f"expected one unpacked version of {name}")
    return versions[0]


def _is_macho(path: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    with path.open("rb") as source:
        magic = source.read(4)
    return magic in (
        b"\xcf\xfa\xed\xfe",  # 64-bit
        b"\xce\xfa\xed\xfe",  # 32-bit
        b"\xca\xfe\xba\xbe",  # universal
    )


def _local_target(reference: str, kegs: dict[str, Path]) -> Path | None:
    """Map a Homebrew placeholder path to the matching file under PREFIX."""
    for placeholder in ("@@HOMEBREW_PREFIX@@/opt/", "@@HOMEBREW_CELLAR@@/"):
        if not reference.startswith(placeholder):
            continue
        parts = reference[len(placeholder):].split("/")
        name = parts[0]
        # Cellar paths carry a version component; opt paths do not.
        rest = parts[2:] if placeholder.endswith("CELLAR@@/") else parts[1:]
        if name not in kegs:
            raise InstallError(f"missing dependency {name} for {reference}")
        return kegs[name].joinpath(*rest)
    return None


def _relocate(kegs: dict[str, Path]) -> None:
    for keg in kegs.values():
        for path in keg.rglob("*"):
            if not _is_macho(path):
                continue
            os.chmod(path, path.stat().st_mode | 0o200)
            listing = subprocess.run(
                ["otool", "-L", str(path)], capture_output=True, text=True, check=True
            ).stdout.splitlines()[1:]
            args = []
            for line in listing:
                reference = line.strip().split(" (")[0]
                target = _local_target(reference, kegs)
                if target is None:
                    continue
                relative = os.path.relpath(target, path.parent)
                new_reference = f"@loader_path/{relative}"
                if path.suffix == ".dylib" and target.name == path.name:
                    args += ["-id", new_reference]
                else:
                    args += ["-change", reference, new_reference]
            if args:
                subprocess.run(
                    ["install_name_tool", *args, str(path)],
                    capture_output=True, text=True, check=True,
                )
            subprocess.run(
                ["codesign", "--force", "--sign", "-", str(path)],
                capture_output=True, text=True, check=True,
            )


def katago_works() -> bool:
    if not KATAGO_LINK.exists():
        return False
    try:
        result = subprocess.run(
            [str(KATAGO_LINK), "version"], capture_output=True, text=True, timeout=60
        )
    except OSError:
        return False
    return result.returncode == 0 and "KataGo v" in result.stdout


def install() -> None:
    if sys.platform != "darwin":
        raise InstallError("this installer only supports macOS")
    for tool in ("otool", "install_name_tool", "codesign"):
        if shutil.which(tool) is None:
            raise InstallError(
                f"{tool} not found; install Apple's command line tools with "
                "`xcode-select --install` and run again"
            )
    print("Resolving KataGo and its libraries...")
    formulas: dict[str, dict] = {}
    _resolve("katago", formulas)
    tags = _bottle_tags()

    if PREFIX.exists():
        shutil.rmtree(PREFIX)
    PREFIX.mkdir(parents=True)
    kegs: dict[str, Path] = {}
    with tempfile.TemporaryDirectory(dir=ENGINE_DIR) as staging:
        for name, formula in formulas.items():
            files = formula["bottle"]["stable"]["files"]
            tag = next((tag for tag in tags if tag in files), None)
            if tag is None:
                raise InstallError(f"no prebuilt {name} for this Mac ({tags[0]})")
            archive = Path(staging) / f"{name}.tar.gz"
            _download(files[tag]["url"], archive, files[tag]["sha256"], name)
            kegs[name] = _extract(archive, name)
            archive.unlink()

    print("Linking libraries...")
    _relocate(kegs)
    KATAGO_LINK.unlink(missing_ok=True)
    KATAGO_LINK.symlink_to(os.path.relpath(kegs["katago"] / "bin/katago", ENGINE_DIR))
    if not katago_works():
        raise InstallError("KataGo was installed but does not run")
    version = subprocess.run(
        [str(KATAGO_LINK), "version"], capture_output=True, text=True
    ).stdout.splitlines()[0]
    print(f"Installed {version}")


if __name__ == "__main__":
    try:
        install()
    except (InstallError, OSError, subprocess.CalledProcessError) as exc:
        sys.exit(f"KataGo install failed: {exc}")
