"""Fetch pinned official tooling and checksum-verified public benchmark data."""
import argparse
import hashlib
import subprocess
import tarfile
import urllib.request
from pathlib import Path

OFFICIAL_COMMIT = "f0a317dfa13e7797baae61711cef27a9805bedcc"
ASSETS = {
    "dev": "28a3ef8f14d020aad6da7e99a43e2b6b06b9f25691c5c245edb5c559cf579e99",
    "dev-large": "9c828cefe481df9ede15089caccc6fb725909ce671ca499c7a2230556956de51",
    "test": "48583d869800c4fbf8860278b4e6ffcbaa78247c07a7abea95621923642aec8e",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=ASSETS, default="dev")
    args = parser.parse_args()
    if not Path("official/.git").exists():
        subprocess.run(["git", "clone", "https://github.com/RxAI-dev/memory-challenge.git", "official"], check=True)
        subprocess.run(["git", "-C", "official", "checkout", "--detach", OFFICIAL_COMMIT], check=True)
    revision = subprocess.check_output(["git", "-C", "official", "rev-parse", "HEAD"], text=True).strip()
    if revision != OFFICIAL_COMMIT:
        raise SystemExit("Official checkout differs from pinned commit; use a fresh checkout.")
    Path("data").mkdir(exist_ok=True)
    archive = Path("data") / f"{args.split}.tar.gz"
    if not archive.exists():
        urllib.request.urlretrieve(
            f"https://github.com/RxAI-dev/memory-challenge/releases/download/data-v1/{archive.name}", archive)
    digest = hashlib.file_digest(archive.open("rb"), "sha256").hexdigest()
    if digest != ASSETS[args.split]:
        raise SystemExit(f"Checksum mismatch: remove {archive} and download again")
    if not (Path("data") / args.split / "histories.jsonl").exists():
        with tarfile.open(archive) as tar:
            tar.extractall("data", filter="data")
    print(f"{args.split}: verified {digest}; official: {revision}")


if __name__ == "__main__":
    main()
