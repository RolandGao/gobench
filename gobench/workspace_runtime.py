"""Host-side limits, clocks and disk checkpoints for Codex learning experiments.

Nothing in this module is mounted into the agent's filesystem. The launcher
supervises a systemd service, whose cgroup contains bubblewrap and every
agent descendant. Writable agent data lives on a fixed-size ext4 image.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import math
import os
import select
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path


PROTOCOL_VERSION = "codex-preparation-v2"
SDK_VERSION = "0.147.0"


class WorkspaceError(RuntimeError):
    pass


class WorkspaceTimeExpired(WorkspaceError):
    """The agent's cumulative active wall clock has expired."""


class WorkspaceResourceExceeded(WorkspaceError):
    """The kernel terminated the agent for exceeding its hardware allocation."""


@dataclass(frozen=True)
class WorkspaceSettings:
    training_seconds: float = 3600
    evaluation_seconds: float = 1800
    cpu_cores: float = 1
    memory_mib: int = 4096
    storage_mib: int = 2048
    max_tasks: int = 256

    def __post_init__(self):
        for name in ("training_seconds", "evaluation_seconds", "cpu_cores"):
            value = getattr(self, name)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or value < 0
                    or name != "training_seconds" and value == 0):
                raise WorkspaceError(f"invalid workspace {name}: {value!r}")
        if self.cpu_cores != 1:
            raise WorkspaceError("workspace cpu_cores must be 1 physical core")
        for name, minimum in (("memory_mib", 64), ("storage_mib", 64), ("max_tasks", 16)):
            value = getattr(self, name)
            if type(value) is not int or value < minimum:
                raise WorkspaceError(f"workspace {name} must be an integer >= {minimum}")

    def manifest(self):
        return {"protocol": PROTOCOL_VERSION, **asdict(self), "swap_mib": 0,
                "cpu_allocation": "exclusive_physical_core_all_siblings",
                "gpu": False, "clock": "cumulative_active_wall_time",
                "sdk_version": SDK_VERSION}


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            os.chmod(temporary, 0o600)
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("expected an object")
        return value
    except (OSError, ValueError) as exc:
        raise WorkspaceError(f"invalid workspace state {path}: {exc}") from exc


def checked(args, **kwargs):
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True,
                            timeout=kwargs.pop("timeout", 60), **kwargs)
    if result.returncode:
        raise WorkspaceError(f"{args[0]} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while data := stream.read(8 * 1024 * 1024):
            digest.update(data)
    return digest.hexdigest()


def copy_image(source, destination):
    """An independent inode, including when the filesystem supports reflinks."""
    source, destination = Path(source), Path(destination)
    if source.is_symlink() or not source.is_file() or os.path.lexists(destination):
        raise WorkspaceError("unsafe workspace image copy")
    checked(["cp", "--reflink=auto", "--sparse=always", "--", source, destination], timeout=300)
    os.chmod(destination, 0o600)


def physical_cores(root=Path("/sys/devices/system/cpu")):
    """Group online CPUs by socket/core, independent of this process's affinity."""
    groups = {}
    for cpu in sorted(parse_cpu_list((root / "online").read_text())):
        topology = root / f"cpu{cpu}" / "topology"
        key = tuple(int((topology / name).read_text())
                    for name in ("physical_package_id", "core_id"))
        groups.setdefault(key, []).append(cpu)
    cores = sorted((tuple(cpus) for cpus in groups.values()), key=lambda cpus: cpus[0])
    if len(cores) <= 1:
        raise WorkspaceError("only 1 core: Codex requires a separate physical core for the OS")
    return cores


def parse_cpu_list(value):
    cpus = set()
    for part in value.strip().split(","):
        if part:
            bounds = list(map(int, part.split("-")))
            cpus.update(range(bounds[0], bounds[-1] + 1))
    return cpus


class CoreLease:
    """A root helper holds a host-wide flock and a cpuset partition until EOF.

    The helper also watches the arena PID, so a killed arena cannot strand a
    running sandbox on a core that another evaluation is about to acquire.
    """

    def __init__(self):
        physical_cores()  # Fail before spawning or waiting on a one-core host.
        self.process = subprocess.Popen(
            ["sudo", "-n", sys.executable, str(Path(__file__).resolve()),
             "reserve-core", "--parent", str(os.getpid())],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        )
        try:
            response = json.loads(self.process.stdout.readline())
            if "error" in response:
                raise WorkspaceError(response["error"])
            self.cpus = tuple(response["cpus"])
            self.slice = response["slice"]
        except Exception as exc:
            self.process.stdin.close()
            self.process.wait(timeout=30)
            error = self.process.stderr.read().strip()
            self.process.stdout.close()
            self.process.stderr.close()
            raise WorkspaceError(f"cannot reserve a physical CPU core: {error or exc}") from exc

    def close(self):
        if self.process is not None:
            process, self.process = self.process, None
            process.stdin.close()
            try:
                process.wait(timeout=60)
                if process.returncode:
                    raise WorkspaceError(f"CPU core cleanup failed: {process.stderr.read().strip()}")
            finally:
                process.stdout.close()
                process.stderr.close()


def _reserve_core(parent):
    """Privileged entry point. Only this helper creates/releases core partitions."""
    cores = physical_cores()
    lock_root = Path("/run/gobench-cores")
    lock_root.mkdir(mode=0o700, exist_ok=True)
    parent_fd = os.pidfd_open(parent)
    lock = None
    unit = None
    try:
        # The lowest numbered physical core (including all its SMT siblings)
        # always stays in the host partition. Each remaining core is independent.
        while lock is None:
            if select.select([sys.stdin, parent_fd], [], [], 0)[0]:
                return 0
            for cpus in cores[1:]:
                candidate = (lock_root / f"core-{cpus[0]}.lock").open("a+b")
                try:
                    fcntl.flock(candidate, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    candidate.close()
                    continue
                lock = candidate
                break
            if lock is None:
                time.sleep(0.1)
        unit = f"gobenchcore{cpus[0]}.slice"
        # Clean up even if a previous helper was itself killed with SIGKILL.
        checked(["systemctl", "stop", unit])
        checked(["systemctl", "start", unit])
        checked(["systemctl", "set-property", "--runtime", unit,
                 "AllowedCPUs=" + ",".join(map(str, cpus))])
        cgroup = Path("/sys/fs/cgroup") / unit
        (cgroup / "cpuset.cpus.partition").write_text("root")
        if ((cgroup / "cpuset.cpus.partition").read_text().strip() != "root"
                or parse_cpu_list((cgroup / "cpuset.cpus.effective").read_text()) != set(cpus)
                or set(cpus) & parse_cpu_list(Path("/sys/fs/cgroup/cpuset.cpus.effective").read_text())):
            raise WorkspaceError("exclusive physical CPU partition was not enforced")
        print(json.dumps({"cpus": cpus, "slice": unit}), flush=True)
        select.select([sys.stdin, parent_fd], [], [])
        return 0
    finally:
        try:
            if unit is not None:
                checked(["systemctl", "stop", unit])
                checked(["systemctl", "revert", unit])
        finally:
            if lock is not None:
                lock.close()
            os.close(parent_fd)


class WorkspaceVolume:
    """A bounded persistent filesystem; host mounting requires sudo -n mount."""

    def __init__(self, directory, size_mib):
        self.directory = Path(directory)
        self.image = self.directory / "disk.img"
        self.mountpoint = self.directory / "fs"
        self.size_mib = size_mib
        self.mounted = False

    def create(self, source=None):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.image.is_symlink() or self.mountpoint.is_symlink():
            raise WorkspaceError("unsafe workspace volume path")
        if self.image.exists():
            if self.image.stat().st_size != self.size_mib * 1024 * 1024:
                raise WorkspaceError("workspace image size differs from recorded resource limit")
            return
        temporary = self.directory / f".disk-{uuid.uuid4().hex}.img"
        try:
            if source is not None:
                if Path(source).stat().st_size != self.size_mib * 1024 * 1024:
                    raise WorkspaceError("checkpoint image has a different disk limit")
                copy_image(source, temporary)
            else:
                with temporary.open("xb") as stream:
                    os.chmod(temporary, 0o600)
                    stream.truncate(self.size_mib * 1024 * 1024)
                checked(["mkfs.ext4", "-q", "-F", "-m", "0", "-E",
                         "lazy_itable_init=0,lazy_journal_init=0", temporary])
                checked(["fallocate", "--dig-holes", temporary], timeout=300)
            temporary.replace(self.image)
        finally:
            temporary.unlink(missing_ok=True)

    def mount(self):
        self.mountpoint.mkdir(mode=0o700, exist_ok=True)
        # A crashed arena can leave a mounted image. Its service must have been
        # stopped by ProcessScope.recover before mounting/reusing this volume.
        if not os.path.ismount(self.mountpoint):
            checked(["sudo", "-n", "mount", "-o", "loop,nodev,nosuid,discard", self.image, self.mountpoint])
        self.mounted = True
        checked(["sudo", "-n", "chown", f"{os.getuid()}:{os.getgid()}", self.mountpoint])
        for name in ("workspace", "runtime", "tmp"):
            path = self.mountpoint / name
            if path.is_symlink():
                raise WorkspaceError(f"unsafe workspace volume directory: {name}")
            path.mkdir(exist_ok=True, mode=0o700)

    def close(self):
        if self.mounted or os.path.ismount(self.mountpoint):
            try:
                checked(["sudo", "-n", "fstrim", self.mountpoint], timeout=300)
            finally:
                checked(["sudo", "-n", "umount", self.mountpoint])
                self.mounted = False
            checked(["fallocate", "--dig-holes", self.image], timeout=300)


class AgentClock:
    """Durable chess clock, shared by all moves, tools and model calls.

    A heartbeat reserves the next short interval before allowing computation.
    Recovery keeps that reservation, so a crash never refunds unlogged time.
    Clean pauses settle it to actual elapsed time. Downtime is not charged.
    """

    INTERVAL = 0.1
    RESERVATION = 1.0

    def __init__(self, path, seconds, *, display_path=None, monotonic=time.monotonic):
        self.path = Path(path)
        self.display_path = Path(display_path) if display_path else None
        self.limit = float(seconds)
        self._now = monotonic
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._worker = None
        self._started = None
        self.failure = None
        self.expired = False
        self.spent = 0.0
        if self.path.exists():
            state = read_json(self.path)
            spent = state.get("spent_seconds")
            if (state.get("limit_seconds") != self.limit
                    or isinstance(spent, bool) or not isinstance(spent, (int, float))
                    or not math.isfinite(spent) or not 0 <= spent <= self.limit):
                raise WorkspaceError("invalid or incompatible workspace clock")
            self.spent = float(spent)
        self._persist()

    @property
    def remaining(self):
        with self._lock:
            elapsed = 0 if self._started is None else self._now() - self._started
            return max(0.0, self.limit - self.spent - elapsed)

    def _persist(self, *, active=False):
        remaining = self.remaining
        reserved = min(remaining, self.RESERVATION) if active else 0
        value = {"limit_seconds": self.limit,
                 "spent_seconds": min(self.limit, self.limit - remaining + reserved),
                 "active": active}
        atomic_json(self.path, value)
        if self.display_path:
            atomic_json(self.display_path, {
                "remaining_seconds": remaining, "active": active,
                "deadline_unix_seconds": time.time() + remaining if active else None,
            })

    def start(self, expire):
        with self._lock:
            if self._started is not None:
                raise WorkspaceError("workspace clock is already running")
            if self.remaining <= 0:
                self.expired = True
                raise WorkspaceTimeExpired("agent time allowance exhausted")
            self._started = self._now()
            self.expired = False
            self.failure = None
            self._stop.clear()
            self._persist(active=True)

        def watch():
            while not self._stop.wait(self.INTERVAL):
                try:
                    with self._lock:
                        self._persist(active=True)
                        if self.remaining > 0:
                            continue
                        self.expired = True
                    expire()
                    # Keep enforcing until pause joins us. A runtime launch
                    # racing the first kill must not escape an expired clock.
                    continue
                except Exception as exc:
                    self.failure = exc
                    expire()
                    return

        self._worker = threading.Thread(target=watch, name="arena-agent-clock", daemon=True)
        self._worker.start()

    def pause(self):
        self._stop.set()
        if self._worker is not None:
            self._worker.join(timeout=10)
            self._worker = None
        with self._lock:
            if self._started is not None:
                self.spent = min(self.limit, self.spent + self._now() - self._started)
                self._started = None
            self._persist()
        if self.failure is not None:
            raise WorkspaceError(f"cannot maintain the agent clock: {self.failure}")


class ProcessScope:
    """systemd service with hard limits and a host-side parent watchdog."""

    def __init__(self, directory, settings, *, core=None):
        self.directory = Path(directory)
        self.settings = settings
        self._owns_core = core is None
        self.core = CoreLease() if core is None else core
        self.unit = f"gobench-agent-{uuid.uuid4().hex}.service"
        self.cgroup = None
        self.frozen = False
        self.dead = False
        self.stats = {}

    @staticmethod
    def recover(directory):
        path = Path(directory) / "service.json"
        if path.exists():
            unit = read_json(path).get("unit", "")
            if not (unit.startswith("gobench-agent-") and unit.endswith(".service")
                    and all(c.isalnum() or c in "-." for c in unit)):
                raise WorkspaceError("invalid saved agent service")
            control = ["sudo", "-n", "systemctl"]
            subprocess.run([*control, "kill", "--signal=KILL", unit],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            subprocess.run([*control, "stop", unit],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)

    def command(self, command):
        self.directory.mkdir(parents=True, exist_ok=True)
        atomic_json(self.directory / "service.json", {"unit": self.unit, "cpus": self.core.cpus})
        settings = self.settings
        launcher = ["sudo", "-n", "systemd-run", f"--slice={self.core.slice}",
                    f"--uid={os.getuid()}", f"--gid={os.getgid()}",
                    "--property=CPUWeight=100",
                    "--property=AllowedCPUs=" + ",".join(map(str, self.core.cpus))]
        service = [*launcher, "--quiet", "--pipe", "--wait",
                   f"--unit={self.unit}", "--service-type=exec",
                   "--property=CPUQuota=",
                   f"--property=MemoryMax={settings.memory_mib}M",
                   "--property=MemorySwapMax=0", "--property=OOMPolicy=kill",
                   f"--property=TasksMax={settings.max_tasks}", "--property=KillMode=control-group",
                   "--property=TimeoutStopSec=2s", *map(str, command)]
        return (sys.executable, str(Path(__file__).resolve()), "supervise",
                "--unit", self.unit, "--parent", str(os.getpid()), "--", *service)

    @property
    def control(self):
        return ["sudo", "-n", "systemctl"]

    def _write_control(self, name, value):
        checked(["sudo", "-n", "tee", self.cgroup / name], input=value)

    def attach(self):
        path = checked([*self.control, "show", "-p", "ControlGroup", "--value", self.unit])
        if not path.startswith("/") or ".." in Path(path).parts:
            raise WorkspaceError("agent resource service did not start")
        self.cgroup = Path("/sys/fs/cgroup") / path.lstrip("/")
        # Verify actual controller values, rather than trusting accepted flags.
        quota, _period = (self.cgroup / "cpu.max").read_text().split()
        partition = Path("/sys/fs/cgroup") / self.core.slice
        if (self.cgroup.parent != partition
                or (partition / "cpuset.cpus.partition").read_text().strip() != "root"
                or parse_cpu_list((self.cgroup / "cpuset.cpus.effective").read_text()) != set(self.core.cpus)
                or quota != "max"):
            raise WorkspaceError("agent exclusive physical core was not enforced")
        for name, expected in (("memory.max", self.settings.memory_mib * 1024 * 1024),
                               ("memory.swap.max", 0), ("pids.max", self.settings.max_tasks)):
            if (self.cgroup / name).read_text().strip() != str(expected):
                raise WorkspaceError(f"agent resource limit was not enforced: {name}")

    def sample(self):
        if self.cgroup is not None:
            for filename in ("cpu.stat", "memory.peak", "memory.events", "pids.peak"):
                try:
                    self.stats[filename] = (self.cgroup / filename).read_text().strip()
                except FileNotFoundError:
                    pass
        return dict(self.stats)

    def failure_reason(self):
        result = subprocess.run([*self.control, "show", "-p", "Result", "--value", self.unit],
                                capture_output=True, text=True, timeout=15)
        return result.stdout.strip()

    def freeze(self):
        if self.dead:
            return
        if self.cgroup is None:
            self.attach()
        self.sample()
        self._write_control("cgroup.freeze", "1")
        deadline = time.monotonic() + 5
        while "frozen 1" not in (self.cgroup / "cgroup.events").read_text():
            if time.monotonic() > deadline:
                self.kill()
                raise WorkspaceError("could not freeze the agent between turns")
            time.sleep(0.01)
        self.frozen = True

    def thaw(self):
        if self.dead:
            raise WorkspaceError("agent runtime has stopped")
        if self.frozen:
            self._write_control("cgroup.freeze", "0")
            self.frozen = False

    def kill(self):
        self.sample()
        self.dead = True
        subprocess.run([*self.control, "kill", "--signal=KILL", self.unit],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)

    def close(self):
        try:
            self.kill()
            subprocess.run([*self.control, "stop", self.unit],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            subprocess.run([*self.control, "reset-failed", self.unit],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            atomic_json(self.directory / "resources.json", self.stats)
        finally:
            if self._owns_core:
                self.core.close()


def runtime_identity():
    """Versions and machine identity are part of a checkpoint's provenance."""
    from importlib.metadata import version

    for package in ("openai-codex", "openai-codex-cli-bin"):
        if version(package) != SDK_VERSION:
            raise WorkspaceError(f"{package} must be pinned to {SDK_VERSION}")
    versions = {}
    for binary in ("python3", "g++", "make"):
        path = shutil.which(binary, path="/usr/bin:/bin")
        if path is None:
            raise WorkspaceError(f"workspace toolchain requires {binary}; see README.md")
        versions[binary] = {"path": str(Path(path).resolve()),
                            "version": checked([path, "--version"]).splitlines()[0],
                            "sha256": file_sha256(path)}
    cpu = next((line.split(":", 1)[1].strip()
                for line in Path("/proc/cpuinfo").read_text().splitlines()
                if line.startswith("model name")), "unknown")
    return {"sdk": SDK_VERSION, "toolchain": versions, "cpu_model": cpu,
            "architecture": os.uname().machine, "kernel": os.uname().release}


def _supervise(unit, parent, command):
    """Keep the service's lifetime tied to the SDK host, even after SIGKILL."""
    stop = threading.Event()
    control = ["sudo", "-n", "systemctl"]
    child = subprocess.Popen(command)

    def terminate(*_):
        stop.set()

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, terminate)
    try:
        while child.poll() is None and not stop.wait(0.1):
            if os.getppid() != parent:
                break
        if child.poll() is not None:
            return child.returncode
    finally:
        if child.poll() is None:
            subprocess.run([*control, "kill", "--signal=KILL", unit],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            subprocess.run([*control, "stop", unit],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        with contextlib.suppress(subprocess.TimeoutExpired):
            child.wait(timeout=5)
    return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("supervise", "reserve-core"))
    parser.add_argument("--unit")
    parser.add_argument("--parent", type=int, required=True)
    options, command = parser.parse_known_args()
    if command[:1] == ["--"]:
        command = command[1:]
    if options.operation == "reserve-core":
        try:
            raise SystemExit(_reserve_core(options.parent))
        except Exception as exc:
            print(json.dumps({"error": str(exc)}), flush=True)
            print(str(exc), file=sys.stderr)
            raise SystemExit(1)
    if not options.unit:
        parser.error("supervise requires --unit")
    raise SystemExit(_supervise(options.unit, options.parent, command))
