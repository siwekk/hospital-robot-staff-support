from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path

BASES = {
    "mimic_iv_demo": "https://physionet.org/files/mimic-iv-demo/2.2/",
    "mimic_iv_ed_demo": "https://physionet.org/files/mimic-iv-ed-demo/2.2/",
    "freiburg_logistics": "https://zenodo.org/records/19085901/files/",
}

FILES = {
    "mimic_iv_demo": [
        "LICENSE.txt",
        "README.txt",
        "SHA256SUMS.txt",
        "hosp/admissions.csv.gz",
        "hosp/transfers.csv.gz",
        "hosp/labevents.csv.gz",
        "hosp/prescriptions.csv.gz",
        "icu/icustays.csv.gz",
    ],
    "mimic_iv_ed_demo": [
        "LICENSE.txt",
        "SHA256SUMS.txt",
        "ed/edstays.csv.gz",
        "ed/triage.csv.gz",
        "ed/pyxis.csv.gz",
        "ed/vitalsign.csv.gz",
    ],
    "freiburg_logistics": ["Network.graphml", "Orders.csv", "README.md"],
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    raw_root = Path("data/raw")
    for project, files in FILES.items():
        for relative in files:
            target = raw_root / project / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                url = BASES[project] + relative
                if project == "freiburg_logistics":
                    url += "?download=1"
                print(f"Downloading {url}")
                urllib.request.urlretrieve(url, target)
            print(f"{target}: {target.stat().st_size} bytes, sha256={sha256(target)}")


if __name__ == "__main__":
    main()
