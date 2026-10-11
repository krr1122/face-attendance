(() => {
'use strict';
const $ = id => document.getElementById(id);
const state = {csrf:'', user:null, config:{}, status:{}, page:'dashboard', stream:null, cameraTarget:null, today:null, faceEnrolled:false, busy:false, people:[], editId:null, enrollId:null, recordPage:1, recordTotal:0, offset:0};
const labels = {normal:'正常',late:'迟到',early:'早退'};
const names = {dashboard:'考勤工作台',records:'考勤记录',employees:'员工与人脸',settings:'系统设置'};
const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const icon = name => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const setText = (id,value) => { $(id).textContent = value; };
let toastTimer;
let cameraGeneration = 0;
function toast(message,error=false) { clearTimeout(toastTimer); setText('toast',message); $('toast').classList.toggle('error',error); $('toast').hidden=false; toastTimer=setTimeout(()=>{$('toast').hidden=true;},5000); }
async function api(path,options={}) {
 const headers = {'X-CSRF-Token':state.csrf,...options.headers};
 if(options.body!==undefined) headers['Content-Type']='application/json';
 const response = await fetch(`/api${path}`,{...options,headers,credentials:'same-origin',body:options.body===undefined?undefined:JSON.stringify(options.body)});
 let data; try { data=await response.json(); } catch { throw new Error('服务器响应异常，请稍后重试'); }
 if(!response.ok) {
  if(response.status===401 && state.user) { stopCamera(); state.user=null; $('app').hidden=true; $('auth').hidden=false; await boot(); }
  throw new Error(data.error||'操作未完成');
 }
 if(data.csrf) state.csrf=data.csrf;
 return data;
}
function syncClock(value) { if(value) state.offset=new Date(`${value}+08:00`).getTime()-Date.now(); updateClock(); }
function bjDate() { return new Date(Date.now()+state.offset); }
function todayISO() { return new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai'}).format(bjDate()); }
function updateClock() {
 const now=bjDate();
 setText('live-time',new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(now));
 setText('top-date',new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'long',day:'numeric',weekday:'long'}).format(now));
 const hour=Number(new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Shanghai',hour:'2-digit',hour12:false}).format(now));
 setText('greeting',hour<12?'上午好':hour<18?'下午好':'晚上好');
}
setInterval(updateClock,1000);
async function boot() {
 try {
  state.status=await api('/status'); syncClock(state.status.server_time);
  $('demo-logins').hidden=!state.status.demo;
  const setup=state.status.needs_setup;
  $('setup-form').hidden=!setup; $('login-form').hidden=setup;
  setText('auth-title',setup?'建立你的考勤工作空间':'开始今天的工作');
  setText('auth-subtitle',setup?'数据库已就绪。请创建首个管理员账号。':'登录你的账号，查看考勤与打卡状态。');
  $('connection-note').hidden=state.status.db_ready;
  setText('connection-note','数据库尚未就绪。请填写 .env，再执行 python app.py init-db 并重启服务。');
  $('login-submit').disabled=!state.status.db_ready;
  if(state.status.db_ready && !setup) {
   try { const data=await api('/me'); await enterApp(data); } catch(error) { if(error.message!=='请先登录') toast(error.message,true); }
  }
 } catch(error) { $('connection-note').hidden=false; setText('connection-note',error.message); }
}
async function login(account,password) { const result=await api('/login',{method:'POST',body:{username:account,password}}); state.user=result.user; await enterApp(await api('/me')); }
$('login-form').addEventListener('submit',async event=>{
 event.preventDefault(); setText('login-error',''); const button=$('login-submit');button.disabled=true;
 const data=Object.fromEntries(new FormData(event.target));
 try { await login(data.username,data.password); event.target.reset(); } catch(error) { setText('login-error',error.message); } finally {button.disabled=false;}
});
$('setup-form').addEventListener('submit',async event=>{
 event.preventDefault(); const button=event.target.querySelector('button[type="submit"],button.primary');button.disabled=true;setText('setup-error','');
 try { const result=await api('/setup',{method:'POST',body:Object.fromEntries(new FormData(event.target))});event.target.reset();toast(result.message);await boot(); } catch(error) {setText('setup-error',error.message);}finally{button.disabled=false;}
});
for(const [id,account] of [['demo-admin','admin'],['demo-employee','employee']]) $(id).addEventListener('click',async()=>{try{await login(account,'DemoAttend2026!');}catch(error){toast(error.message,true);}});
async function enterApp(data) {
 state.user=data.user;state.config=data.settings; $('auth').hidden=true;$('app').hidden=false;
 document.querySelectorAll('.admin-only').forEach(element=>{element.hidden=state.user.role!=='admin';});
 for(const id of ['side-avatar','top-avatar','today-avatar']) setText(id,state.user.name.slice(0,1));
 for(const id of ['side-name','greeting-name','today-name']) setText(id,state.user.name);
 setText('side-role',state.user.role==='admin'?'管理员':'员工');setText('today-department',state.user.department);
 setText('storage-label',state.status.demo?'本地演示数据库':'MySQL 已连接');$('demo-banner').hidden=!state.status.demo;
 setText('stat-total-label',state.user.role==='admin'?'在职员工':'我的考勤范围');setText('stat-total-note',state.user.role==='admin'?'今天的考勤范围':'仅统计本人记录');
 setText('today-records-title',state.user.role==='admin'?'今日打卡动态':'我的今日记录');
 setText('greeting-description',state.user.role==='admin'?'看见团队的每一次到岗，也记录自己的工作日。':'新的一天，从从容到岗开始。');
 setText('records-description',state.user.role==='admin'?'查询全员出勤，按日期筛选并导出记录。':'查询本人的出勤，按日期筛选并导出记录。');
 const day=todayISO();const filter=$('record-filter');filter.elements.start.value=day.slice(0,8)+'01';filter.elements.end.value=day;
 await navigate('dashboard');
}
function bindLogout(id) { $(id).addEventListener('click',async()=>{try{await api('/logout',{method:'POST'});stopCamera();state.user=null;$('app').hidden=true;$('auth').hidden=false;await boot();}catch(error){toast(error.message,true);}}); }
bindLogout('logout'); bindLogout('mobile-logout');
function badge(status) { return status?`<span class="badge ${status==='normal'?'success':'warning'}">${escape(labels[status]||status)}</span>`:'<span class="badge neutral">待打卡</span>'; }
function duration(minutes) { return minutes==null?'待完成班次':`${Math.floor(minutes/60)} 小时 ${minutes%60} 分`; }
function attendanceTable(records) {
 if(!records.length) return `<div class="empty-state">${icon('record')}<p>暂时还没有考勤记录</p><small>完成打卡后，记录会显示在这里。</small></div>`;
 return `<table><thead><tr><th>员工</th><th>日期 / 部门</th><th>上班打卡</th><th>下班打卡</th><th>考勤状态</th><th>在岗时长</th></tr></thead><tbody>${records.map(row=>`<tr><td><div class="table-person"><span class="avatar">${escape(row.name.slice(0,1))}</span><div><strong>${escape(row.name)}</strong><small>${escape(row.employee_no)}</small></div></div></td><td><strong>${escape(row.date)}</strong><br><span class="muted">${escape(row.department)}</span></td><td>${escape(row.check_in||'--:--')}</td><td>${escape(row.check_out||'--:--')}</td><td>${badge(row.in_status)} ${row.out_status?badge(row.out_status):''}</td><td>${row.worked_minutes==null?'—':escape(duration(row.worked_minutes))}</td></tr>`).join('')}</tbody></table>`;
}
async function loadDashboard() {
 const data=await api('/dashboard');state.today=data.today;state.config=data.settings;state.faceEnrolled=data.face_enrolled;syncClock(data.server_time);
 for(const [id,value] of [['stat-total',data.stats.total],['stat-in',data.stats.checked_in],['stat-out',data.stats.checked_out],['stat-late',data.stats.late]]) setText(id,value);
 setText('stat-in-note',state.user.role==='admin'?`${data.stats.total-data.stats.checked_in} 人待上班打卡`:'以本人今日打卡结果为准');
 const row=data.today;
 setText('today-in',row?.check_in||'--:--');setText('today-out',row?.check_out||'--:--');
 setText('in-status-label',labels[row?.in_status]||'待打卡');setText('out-status-label',labels[row?.out_status]||'待打卡');
 $('in-timeline').classList.toggle('done',!!row?.check_in);$('out-timeline').classList.toggle('done',!!row?.check_out);
 setText('shift-start-note',`计划上班 ${row?.shift_start||data.settings.shift_start} · 宽限 ${row?.grace_minutes ?? data.settings.grace_minutes} 分钟`);
 setText('shift-end-note',`计划下班 ${row?.shift_end||data.settings.shift_end}`);setText('worked-time',duration(row?.worked_minutes));
 const faceStatus=$('face-status');faceStatus.className=`badge ${data.face_enrolled?'success':'neutral'}`;faceStatus.textContent=data.face_enrolled?'人脸已录入':'未录入人脸';
 if(!data.face_enrolled) setText('camera-message','请联系管理员完成本人人脸录入');
 else if(!data.models_ready) setText('camera-message','识别模型尚未就绪');
 else setText('camera-message','采集画面仅用于本次核验');
 $('today-table').innerHTML=attendanceTable(data.records.slice(0,8));updatePunchButtons();
}
function updatePunchButtons() {
 const ready=!!state.stream&&state.cameraTarget==='camera-video'&&state.faceEnrolled&&!state.busy&&state.status.models_ready;
 $('punch-in').disabled=!ready||!!state.today?.check_in;
 $('punch-out').disabled=!ready||!state.today?.check_in||!!state.today?.check_out;
 $('start-camera').disabled=state.busy;
}
async function navigate(page) {
 if(!state.user) return;
 if(['employees','settings'].includes(page)&&state.user.role!=='admin') {toast('此页面需要管理员权限',true);return;}
 if(page!=='dashboard') stopCamera();
 state.page=page;
 document.querySelectorAll('.page').forEach(element=>{element.hidden=element.id!==`${page}-page`;});
 document.querySelectorAll('.nav-item').forEach(element=>{element.classList.toggle('active',element.dataset.page===page);});setText('page-label',names[page]);
 try {if(page==='dashboard') await loadDashboard();else if(page==='records') await loadRecords();else if(page==='employees') await loadEmployees();else await loadSettings();}catch(error){toast(error.message,true);}
}
document.querySelectorAll('.nav-item').forEach(button=>button.addEventListener('click',()=>navigate(button.dataset.page)));
$('view-records').addEventListener('click',()=>navigate('records'));
async function startCamera(target='camera-video') {
 stopCamera();
 const generation = cameraGeneration;
 if(!navigator.mediaDevices?.getUserMedia) throw new Error('此浏览器无法使用摄像头。请用 localhost 或 HTTPS 打开，并检查浏览器设置。');
 try {
  const stream=await navigator.mediaDevices.getUserMedia({video:{width:{ideal:640},height:{ideal:480},facingMode:'user'},audio:false});
  if(generation!==cameraGeneration || !state.user || (target==='enroll-video' && !$('face-dialog').open) || (target==='camera-video' && state.page!=='dashboard')) {stream.getTracks().forEach(track=>track.stop());return;}
  state.stream=stream;state.cameraTarget=target;const video=$(target);video.srcObject=stream;video.hidden=false;
  await video.play();
  if(video.readyState<2) await new Promise((resolve,reject)=>{const timeout=setTimeout(()=>reject(new Error('摄像头画面加载超时')),8000);video.addEventListener('loadeddata',()=>{clearTimeout(timeout);resolve();},{once:true});});
  if(target==='camera-video') { $('camera-placeholder').hidden=true;$('start-camera').hidden=true;$('stop-camera').hidden=false;$('camera-badge').className='badge success';$('camera-badge').innerHTML='<i class="status-dot"></i>摄像头已开启'; }
  updatePunchButtons();
 } catch(error) {
  stopCamera();
  const messages={NotAllowedError:'摄像头权限被拒绝，请在浏览器设置中允许摄像头访问',NotFoundError:'未找到摄像头，请连接摄像头后重试',NotReadableError:'摄像头正被其他程序占用，请关闭占用程序'};
  throw new Error(messages[error.name]||error.message||'摄像头启动失败');
 }
}
function stopCamera() {
 cameraGeneration++;
 if(state.stream) state.stream.getTracks().forEach(track=>track.stop());
 state.stream=null;state.cameraTarget=null;
 for(const id of ['camera-video','enroll-video']) $(id).srcObject=null;
 $('camera-video').hidden=true;$('camera-placeholder').hidden=false;$('start-camera').hidden=false;$('stop-camera').hidden=true;
 $('camera-badge').className='badge neutral';$('camera-badge').innerHTML='<i class="status-dot"></i>摄像头未开启';updatePunchButtons();
}
$('start-camera').addEventListener('click',async()=>{try{await startCamera();}catch(error){toast(error.message,true);}});
$('stop-camera').addEventListener('click',stopCamera);
window.addEventListener('pagehide',stopCamera);
document.addEventListener('visibilitychange',()=>{if(document.hidden)stopCamera();});
function capture(target) {
 const video=$(target);if(!state.stream||video.readyState<2||!video.videoWidth) throw new Error('摄像头尚未就绪，请重新开启');
 const scale=Math.min(1,960/Math.max(video.videoWidth,video.videoHeight));const canvas=document.createElement('canvas');canvas.width=Math.round(video.videoWidth*scale);canvas.height=Math.round(video.videoHeight*scale);
 canvas.getContext('2d').drawImage(video,0,0,canvas.width,canvas.height);return canvas.toDataURL('image/jpeg',.90);
}
async function punch(kind) {
 if(state.busy) return;state.busy=true;updatePunchButtons();const button=$(kind==='in'?'punch-in':'punch-out');const original=button.innerHTML;button.textContent='正在核验…';
 try {const data=await api('/attendance/punch',{method:'POST',body:{kind,image:capture('camera-video')}});toast(`${data.message} · ${kind==='in'?data.record.check_in:data.record.check_out}`);await loadDashboard();}
 catch(error){toast(error.message,true);}finally{state.busy=false;button.innerHTML=original;updatePunchButtons();}
}
$('punch-in').addEventListener('click',()=>punch('in'));$('punch-out').addEventListener('click',()=>punch('out'));
function filterQuery() {const values=Object.fromEntries(new FormData($('record-filter')));return new URLSearchParams({...values,page:state.recordPage}).toString();}
async function loadRecords() {const data=await api(`/attendance?${filterQuery()}`);state.recordTotal=data.total;$('records-table').innerHTML=attendanceTable(data.records);setText('records-count',`共 ${data.total} 条记录 · 每页 25 条`);setText('record-page-num',data.page);$('prev-page').disabled=data.page<=1;$('next-page').disabled=data.page*25>=data.total;}
$('record-filter').addEventListener('submit',async event=>{event.preventDefault();state.recordPage=1;try{await loadRecords();}catch(error){toast(error.message,true);}});
$('prev-page').addEventListener('click',async()=>{state.recordPage=Math.max(1,state.recordPage-1);try{await loadRecords();}catch(error){toast(error.message,true);}});
$('next-page').addEventListener('click',async()=>{state.recordPage++;try{await loadRecords();}catch(error){toast(error.message,true);}});
$('export-records').addEventListener('click',async()=>{
 try {const response=await fetch(`/api/attendance/export?${filterQuery()}`,{credentials:'same-origin'});if(!response.ok){const data=await response.json();throw new Error(data.error||'导出失败');}const blob=await response.blob();const url=URL.createObjectURL(blob);const anchor=document.createElement('a');anchor.href=url;anchor.download=`考勤记录-${todayISO()}.csv`;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('考勤记录已导出');}catch(error){toast(error.message,true);}
});
async function loadEmployees() {const data=await api('/users');state.people=data.users;renderEmployees();}
function renderEmployees() {
 const search=$('employee-search').value.trim().toLowerCase();const people=state.people.filter(user=>[user.name,user.employee_no,user.department,user.username].some(value=>value.toLowerCase().includes(search)));
 setText('employee-count',`共 ${state.people.length} 位成员 · ${state.people.filter(u=>u.face_enrolled).length} 份人脸档案`);
 if(!people.length){$('employees-table').innerHTML='<div class="empty-state"><p>没有匹配的员工</p></div>';return;}
 $('employees-table').innerHTML=`<table><thead><tr><th>员工 / 工号</th><th>账号 / 部门</th><th>角色</th><th>人脸档案</th><th>账号状态</th><th>操作</th></tr></thead><tbody>${people.map(user=>`<tr><td><div class="table-person"><span class="avatar">${escape(user.name.slice(0,1))}</span><div><strong>${escape(user.name)}</strong><small>${escape(user.employee_no)}</small></div></div></td><td><strong>${escape(user.username)}</strong><br><span class="muted">${escape(user.department)}</span></td><td><span class="badge ${user.role==='admin'?'success':'neutral'}">${user.role==='admin'?'管理员':'员工'}</span></td><td><span class="badge ${user.face_enrolled?'success':'neutral'}">${user.face_enrolled?'已录入':'未录入'}</span></td><td><span class="badge ${user.active?'success':'danger'}">${user.active?'在职':'已停用'}</span></td><td><div class="table-actions"><button data-action="edit" data-user="${user.id}">编辑</button><button data-action="enroll" data-user="${user.id}" ${!user.active?'disabled':''}>${user.face_enrolled?'重新录入':'录入人脸'}</button>${user.id!==state.user.id?`<button class="disable-btn" data-action="toggle" data-user="${user.id}">${user.active?'停用':'启用'}</button>`:''}</div></td></tr>`).join('')}</tbody></table>`;
}
$('employee-search').addEventListener('input',renderEmployees);
function editEmployee(user=null) {
 state.editId=user?.id||null;const form=$('employee-form');form.reset();setText('employee-error','');setText('employee-dialog-title',user?'编辑员工':'添加员工');
 for(const name of ['name','employee_no','username','department','role']) form.elements[name].value=user?.[name]||(name==='role'?'employee':'');
 form.elements.username.disabled=!!user;form.elements.password.required=!user;form.elements.password.placeholder=user?'留空则保持原密码':'至少 10 个字符';
 const label=$('employee-password-label');label.firstChild.textContent=user?'重置密码（可选）':'初始密码';$('employee-dialog').showModal();
}
$('add-employee').addEventListener('click',()=>editEmployee());
$('employee-form').addEventListener('submit',async event=>{
 event.preventDefault();const form=event.target;const button=form.querySelector('button.primary');button.disabled=true;setText('employee-error','');
 const body=Object.fromEntries(new FormData(form));if(!body.password) delete body.password;
 try {await api(state.editId?`/users/${state.editId}`:'/users',{method:state.editId?'PATCH':'POST',body});$('employee-dialog').close();toast('员工资料已保存');await loadEmployees();}catch(error){setText('employee-error',error.message);}finally{button.disabled=false;}
});
$('employees-table').addEventListener('click',async event=>{
 const button=event.target.closest('button[data-action]');if(!button) return;const user=state.people.find(person=>person.id===Number(button.dataset.user));if(!user)return;
 if(button.dataset.action==='edit'){editEmployee(user);return;}
 if(button.dataset.action==='enroll') {
  $('capture-face').disabled=true;state.enrollId=user.id;setText('enroll-title',`为 ${user.name} 录入人脸`);setText('enroll-error','');$('enroll-consent').checked=false;$('face-dialog').showModal();
  try{await startCamera('enroll-video');$('capture-face').disabled=!state.stream;}catch(error){setText('enroll-error',error.message);}return;
 }
 button.disabled=true;
 try{await api(`/users/${user.id}`,{method:'PATCH',body:{active:!user.active}});toast(user.active?'账号已停用，已有会话同步失效':'账号已启用');await loadEmployees();}catch(error){toast(error.message,true);button.disabled=false;}
});
$('capture-face').addEventListener('click',async()=>{
 if(!$('enroll-consent').checked){setText('enroll-error','请先取得员工同意并勾选确认');return;}
 const button=$('capture-face');button.disabled=true;setText('enroll-error','');state.busy=true;
 try {
  const images=[];for(let index=0;index<3;index++){button.textContent=`正在采集 ${index+1} / 3…`;images.push(capture('enroll-video'));if(index<2)await new Promise(resolve=>setTimeout(resolve,650));}
  button.textContent='正在提取人脸特征…';const data=await api(`/users/${state.enrollId}/face`,{method:'POST',body:{images,consent:true}});$('face-dialog').close();toast(data.message);await loadEmployees();
 }catch(error){setText('enroll-error',error.message);}finally{button.disabled=false;button.textContent='采集并录入 3 张';state.busy=false;}
});
document.querySelectorAll('.close-dialog').forEach(button=>button.addEventListener('click',()=>button.closest('dialog').close()));
$('face-dialog').addEventListener('close',stopCamera);
async function loadSettings(){const data=await api('/settings');state.config=data.settings;const form=$('settings-form');for(const [name,value] of Object.entries(data.settings)){if(form.elements[name])form.elements[name].value=value;}}
$('settings-form').addEventListener('submit',async event=>{event.preventDefault();const button=event.target.querySelector('button');button.disabled=true;try{const data=await api('/settings',{method:'PUT',body:Object.fromEntries(new FormData(event.target))});state.config=data.settings;toast(data.message);}catch(error){toast(error.message,true);}finally{button.disabled=false;}});
boot();
})();
