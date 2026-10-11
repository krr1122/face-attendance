import base64
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
import numpy as np
from cryptography.fernet import Fernet
from sqlalchemy import select
from werkzeug.security import generate_password_hash
from app import create_app
from db import Attendance, FaceTemplate, User
from faces import FaceEngine, FaceError

class TestFace:
    ready = True
    def __init__(self):
        self.codec = FaceEngine('models', Fernet.generate_key())
    def extract(self, image):
        if image == 'wrong':
            return np.array([0, 1], np.float32)
        if image != 'good':
            raise FaceError('图片无效')
        return np.array([1, 0], np.float32)
    def encrypt(self, values): return self.codec.encrypt(values)
    def decrypt(self, value): return self.codec.decrypt(value)
    score = staticmethod(FaceEngine.score)

class AttendanceTests(unittest.TestCase):
    def setUp(self):
        data_directory = Path(__file__).resolve().parents[1] / 'data'
        data_directory.mkdir(exist_ok=True)
        self.directory = Path(tempfile.mkdtemp(prefix='unit-', dir=data_directory))
        self.face = TestFace()
        self.stamp = datetime(2026, 10, 10, 9, 0)
        self.app = create_app({'TESTING':True, 'SECRET_KEY':'test-only', 'DATABASE_URL':f'sqlite:///{self.directory.as_posix()}/test.db', 'FACE_ENGINE':self.face, 'NOW':lambda:self.stamp})
        self.addCleanup(self.app.extensions['db_engine'].dispose)
        self.factory = self.app.extensions['db_factory']
        with self.factory.begin() as db:
            for index, (account, role) in enumerate([('admin','admin'),('alice','employee'),('bob','employee')], 1):
                user = User(id=index, username=account, employee_no=f'E{index}', name=account, department='研发部', role=role, password_hash=generate_password_hash('TestPass2026!'))
                db.add(user)
                db.flush()
                db.add(FaceTemplate(user_id=index, encrypted_features=self.face.encrypt([np.array([1,0], np.float32)]), sample_count=1, enrolled_at=self.stamp))
        self.client = self.app.test_client()
        self.token = self.client.get('/api/status').json['csrf']

    def write(self, path, body, method='post'):
        return getattr(self.client, method)(path, json=body, headers={'X-CSRF-Token':self.token})
    def login(self, account='alice'):
        result = self.write('/api/login', {'username':account,'password':'TestPass2026!'})
        self.assertEqual(result.status_code, 200)
        self.token = result.json['csrf']
    def punch(self, kind='in', image='good', **other):
        return self.write('/api/attendance/punch', dict(kind=kind,image=image,**other))

    def test_requires_login(self): self.assertEqual(self.client.get('/api/users').status_code,401)
    def test_csrf_required(self): self.assertEqual(self.client.post('/api/login',json={}).status_code,403)
    def test_employee_cannot_manage_users(self):
        self.login()
        self.assertEqual(self.client.get('/api/users').status_code,403)
        self.assertEqual(self.write('/api/users',{}).status_code,403)
        self.assertEqual(self.write('/api/users/3',{},'patch').status_code,403)
        self.assertEqual(self.write('/api/users/3/face',{}).status_code,403)
        self.assertEqual(self.write('/api/settings',{},'put').status_code,403)
    def test_wrong_password(self): self.assertEqual(self.write('/api/login',{'username':'alice','password':'wrong'}).status_code,401)
    def test_punch_and_duplicate(self):
        self.login()
        self.assertEqual(self.punch().status_code,200)
        self.assertEqual(self.punch().status_code,409)
    def test_out_requires_in(self):
        self.login()
        self.assertEqual(self.punch('out').status_code,409)
    def test_full_workday(self):
        self.login()
        self.punch()
        self.stamp = datetime(2026,10,10,18,0)
        result = self.punch('out')
        self.assertEqual(result.json['record']['out_status'],'normal')
        self.assertEqual(result.json['record']['worked_minutes'],540)
        self.assertEqual(self.punch('out').status_code,409)
    def test_late_and_early(self):
        self.login()
        self.stamp = datetime(2026,10,10,9,5,1)
        self.assertEqual(self.punch().json['record']['in_status'],'late')
        self.stamp = datetime(2026,10,10,17,59,59)
        self.assertEqual(self.punch('out').json['record']['out_status'],'early')
    def test_grace_boundary(self):
        self.login()
        self.stamp = datetime(2026,10,10,9,5,0)
        self.assertEqual(self.punch().json['record']['in_status'],'normal')
    def test_rejects_wrong_face(self):
        self.login()
        self.assertEqual(self.punch(image='wrong').status_code,422)
        self.assertEqual(self.client.get('/api/attendance').json['total'],0)
    def test_does_not_trust_client_identity(self):
        self.login()
        result = self.punch(user_id=3,role='admin',timestamp='2020-01-01')
        self.assertEqual(result.json['record']['user_id'],2)
        self.assertEqual(result.json['record']['date'],'2026-10-10')
    def test_record_scope_and_csv_scope(self):
        self.login('bob')
        self.punch()
        self.login('alice')
        self.punch()
        result = self.client.get('/api/attendance?user_id=3').json
        self.assertEqual(result['total'],1)
        self.assertEqual(result['records'][0]['user_id'],2)
        self.assertNotIn('bob',self.client.get('/api/attendance/export').data.decode('utf-8-sig'))
        self.login('admin')
        self.assertEqual(self.client.get('/api/attendance').json['total'],2)
    def test_disable_invalidates_session(self):
        self.login('alice')
        other = self.app.test_client()
        csrf = other.get('/api/status').json['csrf']
        result = other.post('/api/login',json={'username':'admin','password':'TestPass2026!'},headers={'X-CSRF-Token':csrf})
        other.patch('/api/users/2',json={'active':False},headers={'X-CSRF-Token':result.json['csrf']})
        self.assertEqual(self.client.get('/api/me').status_code,401)
    def test_admin_cannot_disable_self(self):
        self.login('admin')
        self.assertEqual(self.write('/api/users/1',{'active':False},'patch').status_code,409)
    def test_settings_validated_and_snapshotted(self):
        self.login('alice')
        self.punch()
        self.login('admin')
        valid={'shift_start':'10:00','shift_end':'19:00','grace_minutes':10,'face_threshold':0.5,'organization':'测试企业'}
        self.assertEqual(self.write('/api/settings',valid,'put').status_code,200)
        self.assertEqual(self.write('/api/settings',dict(valid,shift_end='08:00'),'put').status_code,400)
        self.assertEqual(self.write('/api/settings',dict(valid,face_threshold=0.1),'put').status_code,400)
        self.login('alice')
        self.stamp = datetime(2026,10,10,18,0)
        self.assertEqual(self.punch('out').json['record']['out_status'],'normal')
    def test_duplicate_account(self):
        self.login('admin')
        result=self.write('/api/users',{'username':'alice','employee_no':'E9','name':'新员工','department':'测试部','password':'TestPass2026!','role':'employee'})
        self.assertEqual(result.status_code,409)
    def test_enrollment_requires_consent(self):
        self.login('admin')
        self.assertEqual(self.write('/api/users/2/face',{'images':['good']*3}).status_code,400)
    def test_enrollment_rejects_mixed_identity(self):
        self.login('admin')
        self.assertEqual(self.write('/api/users/2/face',{'images':['good','wrong','good'],'consent':True}).status_code,422)
    def test_face_ciphertext_is_not_plain_vector(self):
        with self.factory() as db:
            value=db.get(FaceTemplate,2).encrypted_features
            self.assertNotIn(b'[1.0',value)
            self.assertEqual(self.face.decrypt(value)[0].tolist(),[1,0])
    def test_invalid_date(self):
        self.login()
        self.assertEqual(self.client.get('/api/attendance?start=oops').status_code,400)
    def test_invalid_image(self):
        engine=FaceEngine(Path(__file__).resolve().parents[1]/'models',Fernet.generate_key())
        for value in ['bad','data:image/jpeg;base64,!!!!','data:image/png;base64,'+base64.b64encode(b'fake').decode()]:
            with self.assertRaises(FaceError): engine.extract(value)
    def test_real_models_reject_no_face(self):
        import cv2
        engine=FaceEngine(Path(__file__).resolve().parents[1]/'models',Fernet.generate_key())
        if not engine.ready: self.skipTest('模型未下载')
        _, image=cv2.imencode('.jpg',np.full((480,640,3),120,np.uint8))
        with self.assertRaisesRegex(FaceError,'未检测到人脸'):
            engine.extract('data:image/jpeg;base64,'+base64.b64encode(image).decode())

if __name__ == '__main__': unittest.main(verbosity=2)
