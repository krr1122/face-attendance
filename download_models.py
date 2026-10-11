"""下载 OpenCV 官方模型，并用 Git LFS SHA-256 校验。"""
import hashlib
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODELS = {
    "yunet.onnx": "models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "sface.onnx": "models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
}

def download():
    (ROOT / "models").mkdir(exist_ok=True)
    for name, path in MODELS.items():
        pointer_url = f"https://raw.githubusercontent.com/opencv/opencv_zoo/main/{path}"
        with urllib.request.urlopen(pointer_url, timeout=60) as response:
            pointer = response.read().decode()
        match = re.search(r"oid sha256:([a-f0-9]{64})", pointer)
        if not match:
            raise RuntimeError("官方模型校验信息不可用")
        expected = match.group(1)
        target = ROOT / "models" / name
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == expected:
            print(f"{name}: 已存在且校验通过", flush=True)
            continue
        print(f"下载 {name} ...", flush=True)
        url = f"https://media.githubusercontent.com/media/opencv/opencv_zoo/main/{path}"
        with urllib.request.urlopen(url, timeout=120) as response:
            payload = response.read()
        if hashlib.sha256(payload).hexdigest() != expected:
            raise RuntimeError(f"{name}: SHA-256 校验失败，未写入")
        target.write_bytes(payload)
        print(f"{name}: {len(payload):,} 字节，SHA-256 校验通过", flush=True)

if __name__ == "__main__":
    download()
