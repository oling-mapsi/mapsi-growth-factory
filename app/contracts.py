from pathlib import Path


CONTRACTS_DIR = Path(__file__).resolve().parent.parent / "contracts" / "mapsi"
CONTRACT_VERSION_FILE = CONTRACTS_DIR / "contract-version.txt"


def read_contract_metadata() -> dict[str, str]:
    if not CONTRACT_VERSION_FILE.exists():
        return {"source_sha": "missing", "contract_version": "missing", "source_ref": "missing"}
    lines = CONTRACT_VERSION_FILE.read_text(encoding="utf-8").splitlines()
    metadata: dict[str, str] = {}
    for line in lines:
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        metadata[key.strip()] = value.strip()
    return metadata
