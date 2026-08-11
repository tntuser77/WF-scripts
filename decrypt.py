import json
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding


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

if __name__ == "__main__":
    print(process_data(r"C:\Users\Elijah\AppData\Local\AlecaFrame\lastData.dat"))