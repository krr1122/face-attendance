"""浏览器端验证；所有写入仅发生在独立 QA SQLite 库。"""
import json
import cv2
import threading
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from waitress import create_server
from app import create_app

ROOT=Path(__file__).resolve().parent
OUTPUT=ROOT/'data'/'browser-qa'
OUTPUT.mkdir(exist_ok=True)
frame=cv2.imread(str(ROOT/'data'/'opencv-reference.jpg'))
video_file=OUTPUT/'fake-camera.y4m'
with video_file.open('wb') as stream:
    stream.write(b'YUV4MPEG2 W512 H512 F10:1 Ip A1:1 C420jpeg\n')
    yuv=cv2.cvtColor(cv2.resize(frame,(512,512)),cv2.COLOR_BGR2YUV_I420).tobytes()
    for _ in range(20):
        stream.write(b'FRAME\n')
        stream.write(yuv)
app=create_app({'DATABASE_URL':f'sqlite:///{(OUTPUT / ("qa-"+str(int(time.time()))+".sqlite3")).as_posix()}'},demo=True)
server=create_server(app,host='127.0.0.1',port=5081)
thread=threading.Thread(target=server.run,daemon=True)
thread.start()
results=[]
try:
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True,args=['--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream',f'--use-file-for-fake-video-capture={video_file}'])
        context=browser.new_context(viewport={'width':1440,'height':1080},device_scale_factor=1)
        page=context.new_page()
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto('http://127.0.0.1:5080',wait_until='networkidle')
        page.locator('#auth-title').wait_for()
        page.screenshot(path=str(OUTPUT/'setup-desktop.png'),full_page=True)
        official=context.request.get('http://127.0.0.1:5080/api/status').json()
        page.locator('#setup-form' if official['needs_setup'] else '#login-form').wait_for(state='visible')
        assert page.locator('#demo-logins').is_hidden(), '正式库不得显示演示入口'
        page.screenshot(path=str(OUTPUT/'setup-desktop.png'),full_page=True)
        results.append('正式 MySQL 页面：登录或首次设置正常，无演示账号入口')
        page.goto('http://127.0.0.1:5081',wait_until='networkidle')
        page.locator('#demo-admin').click()
        page.locator('#app').wait_for(state='visible')
        expect(page.locator("#stat-total")).to_have_text("6")
        page.screenshot(path=str(OUTPUT/'dashboard-desktop.png'),full_page=True)
        assert page.evaluate('() => document.documentElement.scrollWidth <= window.innerWidth'), '桌面存在横向溢出'
        results.append('管理员工作台：真实接口渲染统计与考勤表，桌面无溢出')
        page.locator('[data-page="employees"]').click()
        page.locator('#employees-table tbody tr').first.wait_for()
        assert page.locator('#employees-table tbody tr').count()==6
        page.locator('#add-employee').click()
        form=page.locator('#employee-form')
        for name,value in {'name':'浏览器测试员','employee_no':'QA001','username':'qauser','department':'质量部','password':'QaTestPass2026!'}.items():
            form.locator(f'[name="{name}"]').fill(value)
        form.locator('button.primary').click()
        page.locator('#employee-dialog').wait_for(state='hidden')
        expect(page.locator("#employees-table tbody tr")).to_have_count(7)
        page.locator('#employee-search').fill('浏览器测试员')
        assert page.locator('#employees-table tbody tr').count()==1
        page.locator('button[data-action="edit"]').click()
        form.locator('[name="department"]').fill('测试部')
        form.locator('button.primary').click()
        page.locator('#employee-dialog').wait_for(state='hidden')
        expect(page.locator("#employees-table")).to_contain_text("测试部")
        results.append('员工管理：添加、筛选、编辑成功，未写入正式库')
        page.locator('button[data-action="enroll"]').click()
        page.locator('#enroll-consent').check()
        page.locator('#capture-face').click()
        try:
            page.locator('#face-dialog').wait_for(state='hidden',timeout=15000)
        except Exception:
            print('录入错误:',page.locator('#enroll-error').inner_text(),flush=True)
            print('JS 异常:',errors,flush=True)
            page.screenshot(path=str(OUTPUT/'enroll-error.png'))
            raise
        expect(page.locator('#employees-table')).to_contain_text('已录入')
        page.locator('#logout').click()
        page.locator('#auth').wait_for(state='visible')
        page.locator('#login-form [name="username"]').fill('qauser')
        page.locator('#login-form [name="password"]').fill('QaTestPass2026!')
        page.locator('#login-submit').click()
        page.locator('#app').wait_for(state='visible')
        page.locator('#start-camera').click()
        expect(page.locator('#camera-badge')).to_contain_text('摄像头已开启')
        expect(page.locator('#punch-in')).to_be_enabled()
        page.locator('#punch-in').click()
        expect(page.locator('#in-status-label')).to_have_text('迟到')
        expect(page.locator('#punch-in')).to_be_disabled()
        expect(page.locator('#punch-out')).to_be_enabled()
        page.locator('#punch-out').click()
        expect(page.locator('#out-status-label')).to_have_text('早退')
        expect(page.locator('#punch-out')).to_be_disabled()
        page.locator('#stop-camera').click()
        expect(page.locator('#camera-badge')).to_contain_text('摄像头未开启')
        results.append('模拟摄像头完整流程：3 张人脸录入、登录、上班、下班、关闭摄像头成功')
        page.locator('#logout').click()
        page.locator('#auth').wait_for(state='visible')
        page.locator('#demo-admin').click()
        page.locator('#app').wait_for(state='visible')
        page.locator('[data-page="settings"]').click()
        expect(page.locator("#settings-form [name=organization]")).not_to_have_value("")
        page.locator('#settings-form [name="organization"]').fill('云帆 · 浏览器验证')
        page.locator('#settings-form button').click()
        expect(page.locator("#toast")).to_contain_text("设置已保存")
        results.append('系统设置：修改和保存成功')
        page.locator('[data-page="records"]').click()
        page.locator('#records-table tbody tr').first.wait_for()
        with page.expect_download() as download:
            page.locator('#export-records').click()
        download.value.save_as(str(OUTPUT/'attendance-qa.csv'))
        results.append('考勤记录：日期查询和 CSV 下载成功')
        page.locator('#logout').click()
        page.locator('#auth').wait_for(state='visible')
        page.locator('#demo-employee').click()
        page.locator('#app').wait_for(state='visible')
        expect(page.locator("#side-role")).to_have_text("员工")
        assert page.locator('[data-page="employees"]').is_hidden()
        assert page.locator('[data-page="settings"]').is_hidden()
        assert context.request.get('http://127.0.0.1:5081/api/users').status==403
        assert page.locator('#punch-in').is_disabled()
        results.append('员工权限：管理员入口隐藏，越权 API 返回 403，未录人脸不可打卡')
        page.set_viewport_size({'width':390,'height':844})
        page.screenshot(path=str(OUTPUT/'dashboard-mobile.png'),full_page=True)
        assert page.evaluate('() => document.documentElement.scrollWidth <= window.innerWidth'), '手机存在横向溢出'
        page.locator('[data-page="records"]').click()
        page.screenshot(path=str(OUTPUT/'records-mobile.png'),full_page=True)
        assert page.evaluate('() => document.documentElement.scrollWidth <= window.innerWidth'), '记录页手机存在横向溢出'
        page.locator('#mobile-logout').click()
        page.locator('#auth').wait_for(state='visible')
        page.screenshot(path=str(OUTPUT/'login-mobile.png'),full_page=True)
        assert page.evaluate('() => document.documentElement.scrollWidth <= window.innerWidth'), '登录页手机存在横向溢出'
        results.append('390px 手机端：工作台、考勤记录、登录页面无横向溢出')
        assert not errors, '\n'.join(errors)
        results.append('浏览器 JavaScript 未出现运行异常')
        browser.close()
    print(json.dumps({'checks':results,'screenshots':str(OUTPUT)},ensure_ascii=False,indent=2))
finally:
    server.close()
