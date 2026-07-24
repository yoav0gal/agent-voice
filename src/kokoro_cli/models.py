from __future__ import annotations

import fcntl
import hashlib
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

RELEASE_BASE = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
)

MODEL_ASSETS = {
    "int8": (
        "kokoro-v1.0.int8.onnx",
        92_361_271,
        "6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb",
    ),
    "fp16": (
        "kokoro-v1.0.fp16.onnx",
        177_464_787,
        "c1610a859f3bdea01107e73e50100685af38fff88f5cd8e5c56df109ec880204",
    ),
    "full": (
        "kokoro-v1.0.onnx",
        325_532_387,
        "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5",
    ),
}
VOICES_ASSET = (
    "voices-v1.0.bin",
    28_214_398,
    "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
)


def project_root() -> Path:
    """Return the writable Kokoro data root.

    The repository wrapper sets KOKORO_HOME to this checkout. An installed CLI
    uses the platform's user data directory unless KOKORO_HOME overrides it.
    """
    configured = os.environ.get("KOKORO_HOME")
    if configured:
        return Path(configured).expanduser().resolve()

    checkout = Path(__file__).resolve().parents[2]
    if (checkout / "pyproject.toml").is_file() and (checkout / "kokoro").is_file():
        return checkout

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "kokoro"
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = (
        Path(xdg_data_home).expanduser()
        if xdg_data_home
        else Path.home() / ".local" / "share"
    )
    return (base / "kokoro").resolve()


def recording_dir() -> Path:
    configured = os.environ.get("KOKORO_RECORDING_DIR")
    return (
        Path(configured).expanduser().resolve()
        if configured
        else project_root() / "recordings"
    )


def model_dir() -> Path:
    configured = os.environ.get("KOKORO_MODEL_DIR")
    return (
        Path(configured).expanduser().resolve()
        if configured
        else project_root() / "models"
    )


def model_paths(variant: str = "int8") -> tuple[Path, Path]:
    if variant not in MODEL_ASSETS:
        choices = ", ".join(MODEL_ASSETS)
        raise ValueError(f"Unknown model variant '{variant}'. Choose one of: {choices}")
    directory = model_dir()
    return directory / MODEL_ASSETS[variant][0], directory / VOICES_ASSET[0]


def models_ready(variant: str = "int8") -> bool:
    model, voices = model_paths(variant)
    return _valid_asset(model, MODEL_ASSETS[variant]) and _valid_asset(
        voices, VOICES_ASSET
    )


def download_models(variant: str = "int8", force: bool = False) -> tuple[Path, Path]:
    model, voices = model_paths(variant)
    model.parent.mkdir(parents=True, exist_ok=True)
    _download_asset(MODEL_ASSETS[variant], model, force)
    _download_asset(VOICES_ASSET, voices, force)
    return model, voices


def _valid_asset(path: Path, asset: tuple[str, int, str]) -> bool:
    _, expected_size, expected_sha256 = asset
    return (
        path.is_file()
        and path.stat().st_size == expected_size
        and _sha256(path) == expected_sha256
    )


def _download_asset(
    asset: tuple[str, int, str], destination: Path, force: bool
) -> None:
    name, expected_size, expected_sha256 = asset
    lock_path = destination.with_suffix(destination.suffix + ".lock")
    with lock_path.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not force and _valid_asset(destination, asset):
            print(f"✓ {name} already downloaded and verified", file=sys.stderr)
            return

        handle, partial_name = tempfile.mkstemp(
            prefix=f".{name}.", suffix=".part", dir=destination.parent
        )
        os.close(handle)
        partial = Path(partial_name)
        url = f"{RELEASE_BASE}/{name}"
        print(
            f"↓ Downloading {name} ({expected_size / 1_000_000:.1f} MB)",
            file=sys.stderr,
        )

        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "kokoro-cli/0.1"}
            )
            with (
                urllib.request.urlopen(request, timeout=30) as response,
                partial.open("wb") as output,
            ):
                downloaded = 0
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    downloaded += len(chunk)
                    print(
                        f"\r  {downloaded / expected_size:6.1%}",
                        end="",
                        file=sys.stderr,
                        flush=True,
                    )
            print(file=sys.stderr)
            actual_size = partial.stat().st_size
            if actual_size != expected_size:
                raise RuntimeError(
                    f"Download size mismatch for {name}: got {actual_size}, expected {expected_size}"
                )
            actual_sha256 = _sha256(partial)
            if actual_sha256 != expected_sha256:
                raise RuntimeError(
                    f"Checksum mismatch for {name}: got {actual_sha256}, expected {expected_sha256}"
                )
            partial.replace(destination)
        finally:
            partial.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
