"""用 OpenCV 公共样本验证真实模型和完整录入、打卡流程，不使用正式数据库。"""
import base64
import json
import urllib.request
from datetime import datetime
from pathlib import Path
import cv2
import numpy as np
from app import create_app

ROOT=Path(__file__).resolve().parent
(ROOT/'data').mkdir(exist_ok=True)
SAMPLE=ROOT/'data'/'opencv-reference.jpg'
if not SAMPLE.exists():
    with urllib.request.urlopen('https://raw.githubusercontent.com/opencv/opencv/master/samples/data/lena.jpg',timeout=60) as response:
        SAMPLE.write_bytes(response.read())
image=cv2.imread(str(SAMPLE))
if image is None: raise RuntimeError('官方验证样本读取失败')
def encode(frame):
    ok,data=cv2.imencode('.jpg',frame)
    assert ok
    return 'data:image/jpeg;base64,'+base64.b64encode(data).decode()
images=[encode(image),encode(cv2.convertScaleAbs(image,alpha=1.03,beta=3)),encode(cv2.convertScaleAbs(image,alpha=.97,beta=2))]
clock=[datetime(2026,10,10,9,0)]
app=create_app({'TESTING':True,'SECRET_KEY':'model-test-only','DATABASE_URL':'sqlite:///:memory:','NOW':lambda:clock[0]})
face=app.extensions['face_engine']
features=[face.extract(value) for value in images]
assert features[0].shape==(128,)
score=face.score(features[0],[features[1]])
assert score>=.5
assert np.allclose(face.decrypt(face.encrypt(features))[0],features[0])
client=app.test_client()
csrf=client.get('/api/status').json['csrf']
def post(path,data): return client.post(path,json=data,headers={'X-CSRF-Token':csrf})
assert post('/api/setup',{'username':'admin','name':'模型测试管理员','password':'ModelTest2026!'}).status_code==201
login=post('/api/login',{'username':'admin','password':'ModelTest2026!'})
assert login.status_code==200
csrf=login.json['csrf']
result=post('/api/users',{'username':'employee','employee_no':'MODEL001','name':'模型测试员工','department':'测试部','password':'ModelTest2026!','role':'employee'})
assert result.status_code==201
uid=result.json['user']['id']
result=post(f'/api/users/{uid}/face',{'images':images,'consent':True})
assert result.status_code==200, result.json
login=post('/api/login',{'username':'employee','password':'ModelTest2026!'})
csrf=login.json['csrf']
result=post('/api/attendance/punch',{'kind':'in','image':images[1]})
assert result.status_code==200,result.json
assert result.json['record']['in_status']=='normal'
assert post('/api/attendance/punch',{'kind':'in','image':images[1]}).status_code==409
clock[0]=datetime(2026,10,10,18,0)
result=post('/api/attendance/punch',{'kind':'out','image':images[2]})
assert result.status_code==200,result.json
assert result.json['record']['worked_minutes']==540
print(json.dumps({'模型':'YuNet + SFace','特征维度':128,'同人不同曝光匹配分数':round(score,4),'加密往返':'通过','真实模型录入及上下班流程':'通过','重复打卡拦截':'通过','正式数据库写入':False},ensure_ascii=False,indent=2))
app.extensions['db_engine'].dispose()
