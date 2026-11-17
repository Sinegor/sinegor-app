"""Approved final storage cutover: only proxy, one scheduler selector, five verified originals."""
import ast, copy, hashlib, json, os, secrets, ssl, stat, subprocess, sys, tempfile, time, traceback
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen
from zoneinfo import ZoneInfo

ROOT=Path('/home/sinegoradmin/apps/sinegor-app')
PRIVATE=ROOT.parent/'sinegor-app-private'
OLD=PRIVATE/'https/production.https.yaml'
NEW=ROOT/'infra/compose/production.https.yaml'
JOBS=Path('/etc/sinegor/jobs.env')
REPORTS=ROOT/'docs/reports'
DIAG=ROOT.parent/'sinegor-app-artifacts/diagnostics'
ENV={'PATH':'/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin','COMPOSE_ANSI':'never'}
NAMES={name:'sinegor-lab-prod-'+name+'-1' for name in ('api','postgres','cms','web','proxy')}
EXPECTED_TARGETS={
 'infra/compose/production.https.yaml':'88b22ad8655d6f17ddeded9f2426d7cfe4efa3a77b236d44e46d8e05e0180532',
 'infra/compose/production.bootstrap.yaml':'1665164f524a0244b9c70f8379cc787253970b1f92a0fa263f7251ac007951da',
 'infra/proxy/nginx.https.conf':'3e136c3fa071360d57168700f817e3ef1486f3569906337ead19a123a888e53a',
 'infra/proxy/nginx.bootstrap.conf':'5ed98fac01e0d070afcc9eecc5285d1c02ed12838f7acccd3fb4413f53852144',
 'scripts/deployment/deploy-tls.py':'1ef924b0a781c69a7e03aeee6dfde30274659d09d52b3bb4df7126009626249e'}
HOOK=Path('/usr/local/sbin/sinegor-lab-prod-deploy-tls')
LAUNCHER=Path('/usr/local/lib/sinegor/run_jobs.py')
OLD_LINE=('SINEGOR_COMPOSE_OVERRIDE='+str(OLD)).encode()
NEW_LINE=('SINEGOR_COMPOSE_OVERRIDE='+str(NEW)).encode()
EVIDENCE={'task':'production-storage-final','date':'2026-11-17','phases':[],
          'application_source_modified':False,'git_mutations':False,'migrations_run':False,
          'certbot_renewal_run':False,'docker_restart':False,'vps_reboot':False}
class Failure(Exception):pass

def require(value,code):
 if not value:raise Failure(code)

def sha(data):return hashlib.sha256(data).hexdigest()

def run(args,label,timeout=45,env=None):
 p=subprocess.run(args,cwd=ROOT,env=env or ENV,capture_output=True,text=True,timeout=timeout)
 require(p.returncode==0,label)
 return p.stdout

def phase(name):
 EVIDENCE['phases'].append(name)
 print(json.dumps({'event':'layout_final_phase','phase':name}),flush=True)

def prefix(override):
 return ['/usr/bin/docker','compose','-p','sinegor-lab-prod','--env-file',str(PRIVATE/'compose.env'),
         '-f',str(ROOT/'infra/compose/production.yaml'),'-f',str(override)]

def config(override):
 return json.loads(run([*prefix(override),'config','--format','json'],'ComposeConfigInvalid'))

def atomic(path,data,mode,uid,gid):
 fd,name=tempfile.mkstemp(prefix='.layout-final-',dir=path.parent)
 try:
  with os.fdopen(fd,'wb') as stream:
   stream.write(data);stream.flush();os.fsync(stream.fileno())
  os.chmod(name,mode);os.chown(name,uid,gid);os.replace(name,path)
 finally:
  if os.path.exists(name):os.unlink(name)

def metadata(path):
 st=path.lstat()
 return (st.st_dev,st.st_ino,st.st_mode,st.st_uid,st.st_gid,st.st_size,st.st_mtime_ns,st.st_nlink)

def inspect():
 rows=json.loads(run(['/usr/bin/docker','inspect',*NAMES.values()],'ContainerInspectFailed'))
 out={}
 for row in rows:
  name=row['Name'].lstrip('/');require(name in NAMES.values(),'UnexpectedContainer')
  require(row['State']['Running'] and row['State'].get('Health',{}).get('Status')=='healthy','ContainerNotHealthy')
  out[name]={'id':row['Id'],'image':row['Image'],'ports':row['HostConfig']['PortBindings'],
   'user':row['Config'].get('User'),'read_only':row['HostConfig'].get('ReadonlyRootfs'),
   'security_opt':row['HostConfig'].get('SecurityOpt'),'cap_drop':row['HostConfig'].get('CapDrop'),
   'cmd':row['Config'].get('Cmd'),'labels':{k:v for k,v in row['Config'].get('Labels',{}).items() if k in
    ('com.docker.compose.project.config_files','com.docker.compose.project.working_dir')},
   'mounts':sorted([{'source':m['Source'],'target':m['Destination'],'type':m['Type'],
    'name':m.get('Name'),'rw':m['RW']} for m in row['Mounts']],key=lambda x:x['target']),
   'networks':{k:v.get('IPAddress') for k,v in row['NetworkSettings']['Networks'].items()}}
 require(len(out)==5,'FiveContainersRequired')
 for name,value in out.items():
  if name!=NAMES['proxy']:require(not value['ports'],'InternalPortPublished')
 return out

def public_status(url):
 try:
  with urlopen(url,timeout=20,context=ssl.create_default_context()) as response:return response.status
 except HTTPError as exc:return exc.code

def save(path,value):
 data=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()
 atomic(path,data,0o600,1000,1000)

def main():
 require(os.geteuid()==0 and sys.argv[1:]==['--apply-approved-final'],'ExplicitApprovedRootApplyRequired')
 os.umask(0o077)
 result=REPORTS/'production-layout-final-result-2026-11-17.md'
 evidence_path=REPORTS/'production-layout-final-evidence-2026-11-17.json'
 require(not result.exists() and not evidence_path.exists(),'ResultAlreadyExists')
 be=json.loads((REPORTS/'production-layout-category-b-evidence-2026-11-17.json').read_text())
 require(len(be['preserved_originals'])==5,'FiveOriginalsRequired')
 originals={}
 for item in be['preserved_originals']:
  path=Path(item['original_private_path']);saved=Path(item['saved_original'])
  require(path.is_relative_to(PRIVATE/'https') and not path.is_symlink(),'UnexpectedOriginalPath')
  data=path.read_bytes();require(sha(data)==item['sha256']==sha(saved.read_bytes()),'OriginalOrPreservedCopyChanged')
  st=path.stat();require(stat.S_ISREG(st.st_mode) and st.st_nlink==1,'UnsafeOriginalType')
  originals[path]={'data':data,'mode':stat.S_IMODE(st.st_mode),'uid':st.st_uid,'gid':st.st_gid,'identity':metadata(path)}
 require(set(originals)=={OLD,PRIVATE/'https/production.bootstrap.yaml',PRIVATE/'https/nginx/nginx.https.conf',
         PRIVATE/'https/nginx/nginx.bootstrap.conf',PRIVATE/'https/deploy-tls.py'},'UnexpectedCleanupScope')
 for name,h in EXPECTED_TARGETS.items():require(sha((ROOT/name).read_bytes())==h,'RepositoryConfigChanged')
 require(sha(HOOK.read_bytes())==EXPECTED_TARGETS['scripts/deployment/deploy-tls.py'],'SystemHookChanged')
 require(sha(LAUNCHER.read_bytes())=='7045513d6cded66b95bb6c4a3556aff8f5132997ec32a0fbcd089cffd148dfc7','LauncherChanged')
 ast.parse((ROOT/'scripts/deployment/deploy-tls.py').read_text())
 ce=json.loads((REPORTS/'production-layout-category-c-evidence-2026-11-17.json').read_text())
 for item in ce['moves']:
  old,new=Path(item['from']),Path(item['to'])
  require(not old.exists() and not old.is_symlink() and new.exists(),'CategoryCTransferIncomplete')
 old_config,new_config=config(OLD),config(NEW)
 normalized=copy.deepcopy(old_config)
 matches=[x for x in normalized['services']['proxy']['volumes'] if x['target']=='/etc/nginx/sinegor']
 require(len(matches)==1 and matches[0]['source']==str(PRIVATE/'https/nginx'),'UnexpectedOldNginxBind')
 matches[0]['source']=str(ROOT/'infra/proxy')
 require(normalized==new_config,'UnexpectedComposeSemanticChange')
 bootstrap=config(ROOT/'infra/compose/production.bootstrap.yaml')
 require(any(Path(v['source']).is_relative_to(ROOT/'infra/proxy') for v in bootstrap['services']['proxy']['volumes'] if v['type']=='bind'),'BootstrapNginxPathInvalid')
 for configuration in (new_config,bootstrap):
  for service in configuration['services'].values():
   for mount in service.get('volumes',[]):
    if mount['type']=='bind':require(Path(mount['source']).exists(),'ConfiguredBindSourceMissing')
 for service in ('api','cms','web'):
  require(Path(new_config['services'][service]['build']['context'])==ROOT/'apps'/service,'RelativeBuildPathInvalid')
 nginx_mount=[x for x in new_config['services']['proxy']['volumes'] if x['target']=='/etc/nginx/sinegor']
 require(len(nginx_mount)==1 and nginx_mount[0]['read_only'],'NginxBindNotReadOnly')
 before=inspect();proxy_before=before[NAMES['proxy']]
 require(any(x['source']==str(PRIVATE/'https/nginx') and x['target']=='/etc/nginx/sinegor' for x in proxy_before['mounts']),'UnexpectedRuntimeNginxSource')
 jobs_before=JOBS.read_bytes();jobs_st=JOBS.stat()
 require(jobs_st.st_uid==0 and jobs_st.st_gid==0 and stat.S_IMODE(jobs_st.st_mode)==0o600,'UnsafeJobsSelectorFile')
 require(jobs_before.count(OLD_LINE)==1 and NEW_LINE not in jobs_before,'UnexpectedSchedulerSelector')
 jobs_after=jobs_before.replace(OLD_LINE,NEW_LINE)
 protected_paths=[HOOK,Path('/var/lib/sinegor-lab-prod/deploy-guard.json'),
  Path('/var/lib/sinegor-lab-prod/tls-deploy-state.json'),Path('/var/lib/sinegor-lab-prod/tls/cert.pem'),
  Path('/var/lib/sinegor-lab-prod/tls/key.pem'),Path('/var/lib/sinegor-lab-prod/client-ca/cms-client-ca.pem'),
  Path('/etc/letsencrypt/renewal/sinegor-lab-prod.conf')]
 protected={p:sha(p.read_bytes()) for p in protected_paths}
 old_dir_meta={p:(stat.S_IMODE(p.stat().st_mode),p.stat().st_uid,p.stat().st_gid) for p in (PRIVATE/'https',PRIVATE/'https/nginx')}
 require(not DIAG.is_symlink(),'UnsafeDiagnosticsDirectory')
 if not DIAG.exists():DIAG.mkdir(mode=0o700);os.chown(DIAG,1000,1000)
 st=DIAG.stat();require(stat.S_IMODE(st.st_mode)==0o700 and st.st_uid==1000,'UnsafeDiagnosticsDirectory')
 nonce=secrets.token_hex(24);client_path=DIAG/('production-layout-final-20261117-client-'+nonce[:16]+'.json')
 require(not client_path.exists() and not client_path.is_symlink(),'ClientProofAlreadyExists')
 readme=ROOT/'infra/README.md';readme_before=readme.read_bytes()
 require(readme_before.count('## Состояние переноса категории B на 17.11.2026'.encode())==1 and readme_before.count(b'## Development')==1,'OperationalReadmeSectionsChanged')
 phase('preflight_verified')
 cutover=False;deleted=[];nginx_directory_removed=False
 try:
  atomic(JOBS,jobs_after,0o600,0,0)
  cutover=True
  run([*prefix(NEW),'up','-d','--no-deps','--no-build','--force-recreate','--wait','--wait-timeout','120','proxy'],
      'ProxyRecreateFailed',timeout=180)
  phase('proxy_recreated_using_repository_config')
  after=inspect();proxy_after=after[NAMES['proxy']]
  for name in NAMES.values():
   require(before[name]['image']==after[name]['image'],'ContainerImageChanged')
   if name!=NAMES['proxy']:require(before[name]==after[name],'OtherContainerChanged')
  for field in ('user','read_only','security_opt','cap_drop','cmd','ports'):
   require(proxy_before[field]==proxy_after[field],'ProxySecurityOrNetworkChanged')
  require(set(proxy_before['networks'])==set(proxy_after['networks']),'ProxyNetworkMembershipChanged')
  for network,address in proxy_before['networks'].items():
   if network.endswith('_application'):require(proxy_after['networks'][network]==address,'TrustedProxyAddressChanged')
  expected_mounts=copy.deepcopy(proxy_before['mounts'])
  for mount in expected_mounts:
   if mount['target']=='/etc/nginx/sinegor':mount['source']=str(ROOT/'infra/proxy')
  require(expected_mounts==proxy_after['mounts'],'UnexpectedProxyMountChange')
  run(['/usr/bin/docker','exec',NAMES['proxy'],'nginx','-t','-c','/etc/nginx/sinegor/nginx.https.conf'],'NginxSyntaxInvalid')
  statuses={}
  for name,url,expected in [
   ('fastapi','https://sinegor-lab.website/api/health/ready',200),
   ('ssr','https://sinegor-lab.website/',200),
   ('strapi','https://cms.sinegor-lab.website/_health',204),
   ('public_content','https://cms.sinegor-lab.website/api/public-content/footer',200),
   ('admin_without_client_certificate','https://cms.sinegor-lab.website/admin',403)]:
   statuses[name]=public_status(url);require(statuses[name]==expected,'PublicHTTPSCheckFailed:'+name)
  renewal=protected_paths[-1].read_text()
  require(str(HOOK) in renewal and '/var/lib/sinegor-lab-prod/acme' in renewal,'CertbotRenewalDependencyInvalid')
  require(run(['/usr/bin/systemctl','is-active','certbot.timer'],'CertbotTimerInactive').strip()=='active','CertbotTimerInactive')
  require(run(['/usr/bin/systemctl','is-enabled','certbot.timer'],'CertbotTimerDisabled').strip()=='enabled','CertbotTimerDisabled')
  run(['/usr/bin/openssl','x509','-in','/var/lib/sinegor-lab-prod/tls/cert.pem','-noout','-checkend','86400'],'TLSCertificateExpiresSoon')
  selectors={}
  for line in JOBS.read_text().splitlines():
   if not line.strip() or line.lstrip().startswith('#'):continue
   name,sep,value=line.partition('=');require(bool(sep),'InvalidSelectorSyntax')
   selectors[name.strip()]=value.strip()
  require(selectors['SINEGOR_COMPOSE_OVERRIDE']==str(NEW),'NewSchedulerSelectorMissing')
  require(selectors.get('JOBS_ACTIVATION_REVIEWED')=='yes','SchedulerActivationGateChanged')
  check_output=run(['/usr/bin/python3','-B',str(LAUNCHER),'check'],'SchedulerReadOnlyCheckFailed',timeout=60,env=ENV|selectors)
  records=[json.loads(line) for line in check_output.splitlines() if line.startswith('{')]
  host=next((x for x in records if x.get('event')=='host_jobs_check'),None)
  require(host is not None and not host.get('host_issues'),'SchedulerHostIssues')
  require(host['application']['status']=='ok','SchedulerApplicationIssues')
  watchdog=run(['/usr/bin/systemctl','is-active','sinegor-jobs-watchdog.timer'],'WatchdogTimerInactive').strip()
  require(watchdog=='active','WatchdogTimerInactive')
  print(json.dumps({'event':'layout_final_client_check','nonce':nonce,'result_path':str(client_path)}),flush=True)
  deadline=time.monotonic()+120
  while not client_path.exists():
   require(time.monotonic()<deadline,'ClientMTLSProofTimeout');time.sleep(1)
  info=client_path.lstat()
  require(stat.S_ISREG(info.st_mode) and info.st_uid==1000 and stat.S_IMODE(info.st_mode)==0o600
          and info.st_nlink==1 and info.st_size<=4096,'UnsafeClientProof')
  fd=os.open(client_path,os.O_RDONLY|os.O_NOFOLLOW)
  with os.fdopen(fd) as stream:
   current=os.fstat(stream.fileno());require((current.st_dev,current.st_ino)==(info.st_dev,info.st_ino),'ClientProofChanged')
   payload=stream.read(4097);require(len(payload)<=4096,'ClientProofTooLarge');client=json.loads(payload)
  require(client.get('nonce')==nonce and client.get('tls_verified') is True,'ClientProofInvalid')
  require(client.get('admin_html')==200 and client.get('native_admin_without_login')==401,'ClientMTLSOrNativeAuthFailed')
  phase('comprehensive_checks_passed')
  for path,item in originals.items():
   require(metadata(path)==item['identity'] and path.read_bytes()==item['data'],'OriginalChangedBeforeCleanup')
  temp_link=OLD.with_name('.production.https.yaml.final-link')
  require(not temp_link.exists() and not temp_link.is_symlink(),'CompatibilityTemporaryPathExists')
  os.symlink(str(NEW),temp_link);os.replace(temp_link,OLD)
  deleted.append(str(OLD))
  for path in originals:
   if path==OLD:continue
   require(metadata(path)==originals[path]['identity'],'OriginalChangedBeforeUnlink')
   path.unlink();deleted.append(str(path))
  nginx_dir=PRIVATE/'https/nginx'
  if not any(nginx_dir.iterdir()):nginx_dir.rmdir();nginx_directory_removed=True
  require(OLD.is_symlink() and OLD.resolve()==NEW,'CompatibilityLinkInvalid')
  for path in originals:
   if path!=OLD:require(not path.exists() and not path.is_symlink(),'OriginalStillExists')
  require(JOBS.read_bytes()==jobs_after,'SchedulerSelectorChangedDuringOperation')
  run([*prefix(NEW),'config','--quiet'],'FinalComposeConfigInvalid')
  # Preserve historical container config_files labels without recreating API/CMS/web/DB.
  for container in after.values():
   for config_file in container['labels'].get('com.docker.compose.project.config_files','').split(','):
    if config_file:require(Path(config_file).is_file(),'DanglingContainerComposeReference')
  for path,h in protected.items():require(sha(path.read_bytes())==h,'ProtectedServiceFileChanged')
  for name,h in EXPECTED_TARGETS.items():require(sha((ROOT/name).read_bytes())==h,'RepositoryConfigChangedDuringOperation')
  phase('five_originals_removed_and_dependencies_verified')
 except Exception as exc:
  failures=[]
  try:
   for directory,meta in old_dir_meta.items():
    directory.mkdir(exist_ok=True);os.chmod(directory,meta[0]);os.chown(directory,meta[1],meta[2])
   for path,item in originals.items():
    require(not path.exists() or path.is_symlink() or path.read_bytes()==item['data'],'ConcurrentOriginalEditPreventsRollback')
    atomic(path,item['data'],item['mode'],item['uid'],item['gid'])
   require(JOBS.read_bytes() in (jobs_before,jobs_after),'ConcurrentSelectorEditPreventsRollback')
   atomic(JOBS,jobs_before,0o600,0,0)
   if cutover:run([*prefix(OLD),'up','-d','--no-deps','--no-build','--force-recreate','--wait','--wait-timeout','120','proxy'],'ProxyRollbackFailed',timeout=180)
  except Exception as rollback_exc:failures.append(type(rollback_exc).__name__)
  EVIDENCE.update({'success':False,'rollback_succeeded':not failures,'rollback_errors':failures,
                   'failure_type':type(exc).__name__,'failure_code':str(exc) if isinstance(exc,Failure) else None})
  save(evidence_path,EVIDENCE)
  print(json.dumps({'event':'layout_final_failed','rollback_succeeded':not failures,'failure_code':EVIDENCE['failure_code']}),flush=True)
  raise
 application=host['application']
 EVIDENCE.update({'success':True,'observed_at':datetime.now(ZoneInfo('Europe/Moscow')).isoformat(),
  'deleted_originals':deleted,'compatibility_link':{'path':str(OLD),'target':str(NEW)},
  'empty_nginx_directory_removed':nginx_directory_removed,
  'checks':{'compose_final':True,'compose_bootstrap':True,'nginx_syntax':True,'https':statuses,
   'mtls_admin_with_certificate':client['admin_html'],'native_strapi_without_login':client['native_admin_without_login'],
   'certbot_timer_enabled_active':True,'renewal_config_preserved':True,'tls_certificate_valid_over_24h':True,
   'system_hook_unchanged':True,'scheduler_host_issues':host['host_issues'],'scheduler_status':application['status'],
   'other_four_containers_unchanged':True,'all_images_unchanged':True,'volumes_unchanged':True,
   'internal_ports_unpublished':True,'container_compose_references_resolve':True,'category_c_old_paths_absent':True},
  'containers_after':after,'scheduler_application':application,
  'client_proof':str(client_path),'new_audit_performed':False,'unrelated_files_deleted':False})
 save(evidence_path,EVIDENCE)
 readme=ROOT/'infra/README.md';require(readme.read_bytes()==readme_before,'ConcurrentReadmeEdit');text=readme_before.decode();st=readme.stat()
 start='## Состояние переноса категории B на 17.11.2026'
 end='## Development и прочие инструменты'
 require(text.count(start)==1 and text.count(end)==1,'OperationalReadmeSectionsChanged')
 before_text,rest=text.split(start,1);old_block,tail=rest.split(end,1)
 current='## Рабочие пути после реорганизации 17.11.2026\n\nProduction использует infra/compose/production.https.yaml и read-only bind infra/proxy. В /etc/sinegor/jobs.env выбран этот же override. Пять прежних исходных файлов private/https удалены после проверки сохранённых экземпляров и приёмки production.\n\nДля исторических Docker labels API/CMS/web/DB оставлена одна совместимая ссылка private/https/production.https.yaml на YAML в репозитории. Это ссылка, а не дополнительная копия конфигурации. Пересоздан только proxy; образы и остальные четыре контейнера сохранены.\n\nИсходные экземпляры B сохранены в /home/sinegoradmin/sinegor-app-deployment-originals/category-b-20261117. Архив C находится в /home/sinegoradmin/apps/sinegor-app-artifacts/archive/ по этапам. Системный /usr/local/sbin/sinegor-lab-prod-deploy-tls и Certbot/TLS state не изменялись.\n\nОткат является отдельно согласуемой операцией: восстановить четыре прежних Compose/Nginx файла из сохранённых оригиналов, вернуть прежний selector /etc/sinegor/jobs.env и пересоздать только proxy со старым override. Ссылку заменять атомарно, не записывать через неё в Git-файл. БД, volumes, Git и приложение автоматически не откатывать.\n\n'
 atomic(readme,(before_text+current+end+tail).replace('Целевая команда из корня серверного репозитория:','Штатная команда из корня серверного репозитория:').encode(),stat.S_IMODE(st.st_mode),st.st_uid,st.st_gid)
 report=('# SINEGOR LAB — завершение реорганизации production-хранилища\n\nДата: 17.11.2026, Europe/Moscow.\n\n'
 'Удалены пять проверенных исходных экземпляров из private:\n\n'+
 ''.join('- '+name+'\n' for name in deleted)+
 '\nИсходные экземпляры сохранены вне private и проверены по SHA256. Материалы C уже перенесены; их старые пути отсутствуют. Остальные private файлы не удалялись. Оставлена одна ссылка совместимости на production.https.yaml в репозитории для существующих Docker labels; прежний пустой nginx-каталог удалён, если в нём не появилось других файлов.\n\n'
 'После отдельного согласования пересоздан только proxy с конфигурацией infra/proxy, selector III-7 переведён на репозиторный override. Другие четыре контейнера, все образы, volumes и настройки безопасности сохранены.\n\n'
 'Комплексная приёмка пройдена: основной и bootstrap Compose; nginx -t; trusted HTTPS FastAPI/SSR/Strapi/Content API; mTLS admin 403 без сертификата и 200 с сертификатом; native admin 401 без входа; Certbot timer/renewal dependencies/действующий сертификат; host launcher check III-7 через новый selector; отсутствие открытых внутренних портов и нарушенных ссылок. Certbot renew и выпуск сертификатов не выполнялись. Подробное безопасное evidence — production-layout-final-evidence-2026-11-17.json.\n\n'
 'В серверном AGENTS.md закреплены четыре правила хранения: versioned source/config/scripts/technical docs — в репозитории; только необходимая приватная конфигурация — в private; временные/test/diagnostic/archive материалы — в artifacts; действующие системные файлы/state — в системных каталогах. Исключение о локальной передаче отчётов сохранено. infra/README.md отражает фактические рабочие пути.\n\n'
 'Повторной инвентаризации, удаления прочих A/C/D, изменений архитектуры, бизнес-логики, migrations, Git commit/push, restart Docker или reboot не было. Препятствий по выполненному объёму не осталось.\n')
 atomic(result,report.encode(),0o600,1000,1000)
 print(json.dumps({'event':'layout_final_completed','deleted_originals':len(deleted),'all_checks_passed':True,
                   'report':str(result)},ensure_ascii=False),flush=True)

if __name__=='__main__':
 try:main()
 except Exception as exc:
  print(json.dumps({'event':'layout_final_error','error_type':type(exc).__name__,
   'failure_code':str(exc) if isinstance(exc,Failure) else None,
   'line':traceback.extract_tb(exc.__traceback__)[-1].lineno}),flush=True)
  raise SystemExit(1) from None
