import json
import os
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding

# Inventory sources, both the raw inventory.php payload. WFHelper writes it as
# plain JSON; AlecaFrame wraps it in AES. Whichever was written last wins.
WFHELPER_PATH = os.path.join(os.environ.get("APPDATA", ""), "WFHelper",
                             "api-helper", "inventory.json")
ALECA_PATH = os.path.join(os.environ.get("LOCALAPPDATA", ""), "AlecaFrame",
                          "lastData.dat")
SOURCES = {"WFHelper": WFHELPER_PATH, "AlecaFrame": ALECA_PATH}


def process_data(file_path):
    key = b"LEO-ALEC\tEO-ALEC"
    iv = bytes([49, 50, 70, 71, 66, 51, 54, 45, 76, 69, 51, 45, 113, 61, 57, 0])

    with open(file_path, "rb") as f:
        encrypted_data = f.read()

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    padded_data = decryptor.update(encrypted_data) + decryptor.finalize()

    unpadder = padding.PKCS7(128).unpadder()
    data_bytes = unpadder.update(padded_data) + unpadder.finalize()

    data = json.loads(data_bytes.decode("utf-8"))
    if isinstance(data, dict) and "InventoryJson" in data:
        data = json.loads(data["InventoryJson"])

    return json.dumps(data, indent=2)


def find_inventory():
    """(source, path) of the freshest inventory file, or (None, WFHelper path)."""
    found = [(os.path.getmtime(p), name, p) for name, p in SOURCES.items()
             if os.path.exists(p)]
    if not found:
        return None, WFHELPER_PATH
    _, name, path = max(found)
    return name, path


def load_inventory(path=None):
    """Inventory dict from the given file, or the freshest known source."""
    path = path or find_inventory()[1]
    if path.lower().endswith(".json"):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return json.loads(process_data(path))


if __name__ == "__main__":
    print(json.dumps(load_inventory(), indent=2))
