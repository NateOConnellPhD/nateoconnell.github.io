"""Install the approved, disposable CFB numerical environment on Apple Silicon.

Run from Terminal if the agent sandbox blocks runtime downloads. Installs only
under .codex-tmp/cfb-refit and leaves existing directories untouched. No fits,
credentials, system installations, publishing, or paid services are involved.
"""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import posixpath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile


PROJECT = Path(__file__).resolve().parents[2]
ROOT = PROJECT / ".codex-tmp" / "cfb-refit"
LIMIT = 1_500_000_000
# Stop growing processes early, leaving room for a wheel's temporary extraction.
WORK_LIMIT = 1_200_000_000
RELEASE_URL = "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest"
ASSET_PATTERN = re.compile(r"cpython-3\.12\.\d+\+[^/]+-aarch64-apple-darwin-install_only_stripped\.tar\.gz\Z")


def used_bytes():
    total = 0
    for parent, _, names in os.walk(ROOT, followlinks=False):
        for name in names:
            try:
                info = os.lstat(Path(parent) / name)
            except FileNotFoundError:  # pip can move/remove a temporary file mid-scan.
                continue
            if stat.S_ISREG(info.st_mode):
                total += info.st_size
    return total


def request(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={
        "User-Agent": "MarginOfMerit-environment-setup", "Accept": "application/vnd.github+json",
    }), timeout=60)


def choose_asset(release):
    matches = [a for a in release["assets"] if ASSET_PATTERN.fullmatch(a["name"])]
    if len(matches) != 1:
        raise ValueError("Expected one Python 3.12 Apple Silicon runtime in the release")
    asset = matches[0]
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", asset.get("digest") or ""):
        raise ValueError("Runtime download has no SHA-256 digest; refusing an unverified download")
    if not 0 < asset["size"] <= 100_000_000:
        raise ValueError("Unexpected runtime archive size")
    if not asset["browser_download_url"].startswith("https://github.com/astral-sh/python-build-standalone/releases/download/"):
        raise ValueError("Unexpected runtime download source")
    return asset


def validate_members(members):
    """Validate paths and links before extracting the checksum-verified archive."""
    def inside(name):
        path = PurePosixPath(posixpath.normpath(name))
        return not path.is_absolute() and path.parts and path.parts[0] == "python" and ".." not in path.parts

    for member in members:
        if not inside(member.name) or not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
            raise ValueError("Unsafe runtime archive entry: " + member.name)
        if member.issym() or member.islnk():
            target = posixpath.join(posixpath.dirname(member.name), member.linkname) if member.issym() else member.linkname
            if not inside(target):
                raise ValueError("Runtime archive link leaves its directory: " + member.name)
    # Do not allow a later entry to write through a symlink introduced earlier.
    links = {posixpath.normpath(m.name) for m in members if m.issym() or m.islnk()}
    for member in members:
        if any(str(parent) in links for parent in PurePosixPath(member.name).parents):
            raise ValueError("Runtime archive writes through a link: " + member.name)


def run(command, env, log_name):
    print(log_name + "…", flush=True)
    with (ROOT / log_name).open("w") as log:
        process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT)
        started = time.monotonic()
        try:
            while process.poll() is None:
                if used_bytes() > WORK_LIMIT:
                    raise RuntimeError("Stopped before the approved disk ceiling")
                if time.monotonic() - started > 600:
                    raise RuntimeError("Setup step exceeded ten minutes")
                time.sleep(.5)
            if process.returncode:
                tail = (ROOT / log_name).read_text(errors="replace")[-6000:]
                raise RuntimeError(f"Setup step failed ({process.returncode}):\n{tail}")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def main():
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise RuntimeError("This bootstrap is for the approved Apple Silicon Mac environment")
    if ROOT.exists():
        raise RuntimeError(f"Preserving existing files: {ROOT} already exists. Ask Codex to inspect it before retrying.")
    # Fetch metadata before making any task directory.
    with request(RELEASE_URL) as response:
        raw = response.read(8_000_001)
    if len(raw) > 8_000_000:
        raise ValueError("Unexpectedly large runtime release metadata")
    release = json.loads(raw)
    asset = choose_asset(release)
    ROOT.mkdir(parents=True)
    try:
        print("Downloading verified runtime: " + asset["name"], flush=True)
        archive = ROOT / "runtime.tar.gz"
        digest = hashlib.sha256()
        count = 0
        with request(asset["browser_download_url"]) as response, archive.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                count += len(chunk)
                if count > asset["size"]:
                    raise ValueError("Runtime download exceeds its declared size")
                digest.update(chunk)
                output.write(chunk)
        if count != asset["size"] or "sha256:" + digest.hexdigest() != asset["digest"]:
            raise ValueError("Runtime download does not match its declared size and SHA-256")
        with tarfile.open(archive, "r:gz") as bundle:
            members = bundle.getmembers()
            validate_members(members)
            if used_bytes() + sum(m.size for m in members) > WORK_LIMIT:
                raise RuntimeError("Runtime would exceed the working disk budget")
            bundle.extractall(ROOT, members=members)
        archive.unlink()
        env = os.environ.copy()
        for key, leaf in (("TMPDIR", "tmp"), ("XDG_CACHE_HOME", "cache"),
                          ("MPLCONFIGDIR", "matplotlib"), ("JAX_COMPILATION_CACHE_DIR", "jax-cache")):
            path = ROOT / leaf
            path.mkdir()
            env[key] = str(path)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["JAX_PLATFORMS"] = "cpu"
        env["MPLBACKEND"] = "Agg"
        env["OPENBLAS_NUM_THREADS"] = "1"
        env["OMP_NUM_THREADS"] = "1"
        python = ROOT / "python" / "bin" / "python3"
        wheels = ROOT / "wheels"
        wheels.mkdir()
        requirements = Path(__file__).with_name("requirements.txt")
        pip = [str(python), "-B", "-m", "pip", "--isolated", "--disable-pip-version-check", "--no-cache-dir"]
        run(pip + ["download", "--only-binary=:all:", "--dest", str(wheels), "-r", str(requirements)], env, "download.log")
        expanded = 0
        for path in wheels.glob("*.whl"):
            with zipfile.ZipFile(path) as wheel:
                expanded += sum(item.file_size for item in wheel.infolist())
        if used_bytes() + expanded > WORK_LIMIT:
            raise RuntimeError("Dependency wheels would exceed the approved working disk budget")
        run(pip + ["install", "--no-compile", "--only-binary=:all:", "--no-index", "--find-links", str(wheels), "-r", str(requirements)], env, "install.log")
        run(pip + ["check"], env, "check.log")
        run([str(python), "-B", "-c", "import numpy, scipy, jax, numpyro, arviz; print('Numerical imports ready')"], env, "imports.log")
        run(pip + ["freeze", "--all"], env, "resolved-requirements.txt")
        shutil.rmtree(wheels)
        provenance = {"release": release["tag_name"], "runtime": asset["name"],
                      "runtime_sha256": digest.hexdigest(), "runtime_url": asset["browser_download_url"],
                      "requirements_sha256": hashlib.sha256(requirements.read_bytes()).hexdigest(),
                      "bytes": used_bytes(), "approved_ceiling_bytes": LIMIT}
        (ROOT / "environment.json").write_text(json.dumps(provenance, indent=2) + "\n")
        print(f"Environment ready ({used_bytes() / 1_000_000:.0f} MB). No model fits have run.\nPython: {python}")
        return 0
    except BaseException:
        # ROOT did not exist before this invocation; all of its contents are ours.
        shutil.rmtree(ROOT)
        print("Removed this setup attempt's files; no environment was installed.", file=sys.stderr)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
