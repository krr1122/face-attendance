"""YuNet + SFace；图片仅在内存处理，数据库只保存加密后的特征。"""
import base64
import binascii
import json
import threading
from pathlib import Path
import cv2
import numpy as np
from cryptography.fernet import Fernet

class FaceError(ValueError):
    pass

class FaceEngine:
    def __init__(self, model_dir, encryption_key):
        self.model_dir = Path(model_dir)
        self.cipher = Fernet(encryption_key)
        self.lock = threading.Lock()
        self.detector = None
        self.recognizer = None

    @property
    def ready(self):
        return all((self.model_dir / name).is_file() for name in ("yunet.onnx", "sface.onnx"))

    def extract(self, data_url):
        if not self.ready:
            raise FaceError("缺少识别模型，请先运行 download_models.py")
        if not isinstance(data_url, str) or len(data_url) > 2_800_000:
            raise FaceError("图片无效或超过 2 MB")
        if not data_url.startswith(("data:image/jpeg;base64,", "data:image/png;base64,")):
            raise FaceError("请提交摄像头采集的 JPEG 或 PNG 图片")
        try:
            raw = base64.b64decode(data_url.split(",", 1)[1], validate=True)
        except (binascii.Error, ValueError):
            raise FaceError("图片编码无效") from None
        if not raw or len(raw) > 2_000_000:
            raise FaceError("图片无效或超过 2 MB")
        # 编码图片先检查像素数，避免压缩图片展开占用过多内存。
        from PIL import Image
        import io
        try:
            with Image.open(io.BytesIO(raw)) as probe:
                width, height = probe.size
                if width < 160 or height < 160 or width * height > 4_000_000:
                    raise FaceError("图片尺寸应在 160 像素至 400 万像素之间")
        except FaceError:
            raise
        except Exception:
            raise FaceError("无法解码图片") from None
        image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise FaceError("无法解码图片")
        height, width = image.shape[:2]
        if max(width, height) > 1280:
            image = cv2.resize(image, (int(width * 1280 / max(width, height)), int(height * 1280 / max(width, height))))
        with self.lock:
            if self.detector is None:
                self.detector = cv2.FaceDetectorYN.create(str(self.model_dir / "yunet.onnx"), "", (320, 320), 0.85, 0.3, 5000)
                self.recognizer = cv2.FaceRecognizerSF.create(str(self.model_dir / "sface.onnx"), "")
            self.detector.setInputSize((image.shape[1], image.shape[0]))
            _, faces = self.detector.detect(image)
            if faces is None or len(faces) == 0:
                raise FaceError("未检测到人脸，请正对摄像头并保证光线充足")
            if len(faces) != 1:
                raise FaceError("画面中有多张人脸，请单人打卡")
            x, y, w, h = faces[0][:4].astype(int)
            if min(w, h) < 80:
                raise FaceError("人脸太小，请靠近摄像头")
            crop = image[max(0, y):max(0, y) + h, max(0, x):max(0, x) + w]
            if crop.size == 0:
                raise FaceError("请将完整人脸放入画面")
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            if not 35 < gray.mean() < 235:
                raise FaceError("光线过暗或过亮，请调整照明")
            if cv2.Laplacian(gray, cv2.CV_64F).var() < 25:
                raise FaceError("画面模糊，请保持稳定后重试")
            aligned = self.recognizer.alignCrop(image, faces[0])
            feature = self.recognizer.feature(aligned).flatten().astype(np.float32)
            return feature / max(float(np.linalg.norm(feature)), 1e-8)

    @staticmethod
    def score(query, features):
        return max(float(np.dot(query, vector)) for vector in features)

    def encrypt(self, features):
        return self.cipher.encrypt(json.dumps([v.tolist() for v in features]).encode())

    def decrypt(self, payload):
        return [np.asarray(v, dtype=np.float32) for v in json.loads(self.cipher.decrypt(payload))]
