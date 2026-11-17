"""Rename only already-classified category C materials; no historical code execution."""
import ctypes, errno, hashlib, json, os, re, stat, sys, traceback
from pathlib import Path

ROOT=Path('/home/sinegoradmin/apps/sinegor-app')
PRIVATE=ROOT.parent/'sinegor-app-private'
ARTIFACTS=ROOT.parent/'sinegor-app-artifacts'
ARCHIVE=ARTIFACTS/'archive'
OLD_III7=PRIVATE/'iii7'
NEW_III7=ARCHIVE/'III-7'
EXPECTED=json.loads("[{\"relative\":\"iii5-reboot-baseline-2026-11-15.json\",\"kind\":\"file\",\"sha256\":\"dea42efcc2051981d13485cabd8a8de50497c6126b49e5ab1440212e465841cd\"},{\"relative\":\"iii7\",\"kind\":\"directory\",\"sha256\":null},{\"relative\":\"iii6-ip-r-74cc255b61332b32cbcd72002fd5eae6/connection.json\",\"kind\":\"file\",\"sha256\":null},{\"relative\":\"iii7/deploy-20261116\",\"kind\":\"directory\",\"sha256\":null},{\"relative\":\"iii7/restart-acceptance-20261116\",\"kind\":\"directory\",\"sha256\":null},{\"relative\":\"iii7/rollback-iii7-20261116-1-144931\",\"kind\":\"directory\",\"sha256\":null},{\"relative\":\"iii7/root-preflight.py\",\"kind\":\"file\",\"sha256\":\"1396b0c9b2a934379b47020b1d642febebdb0720612f6a8f2104b11f278b9a3b\"},{\"relative\":\"iii7/rollback-iii7-20261116-1-144931/compose.env\",\"kind\":\"file\",\"sha256\":null},{\"relative\":\"iii7/rollback-iii7-20261116-1-144931/files\",\"kind\":\"directory\",\"sha256\":null},{\"relative\":\"iii7/rollback-iii7-20261116-1-144931/manifest.json\",\"kind\":\"file\",\"sha256\":\"33702ce5e0d7ea1aef8e462cabadc57fe4f3c4338f75fdc0b382b16a0097a15b\"},{\"relative\":\"iii7/rollback-iii7-20261116-1-144931/files/apps\",\"kind\":\"directory\",\"sha256\":null},{\"relative\":\"iii7/rollback-iii7-20261116-1-144931/files/infra\",\"kind\":\"directory\",\"sha256\":null},{\"relative\":\"iii7/rollback-iii7-20261116-1-144931/files/apps/api\",\"kind\":\"directory\",\"sha256\":null},{\"relative\":\"iii7/rollback-iii7-20261116-1-144931/files/apps/api/src\",\"kind\":\"directory\",\"sha256\":null},{\"relative\":\"iii7/rollback-iii7-20261116-1-144931/files/apps/api/src/sinegor\",\"kind\":\"directory\",\"sha256\":null},{\"relative\":\"iii7/rollback-iii7-20261116-1-144931/files/apps/api/src/sinegor/jobs\",\"kind\":\"directory\",\"sha256\":null},{\"relative\":\"iii7/rollback-iii7-20261116-1-144931/files/apps/api/src/sinegor/modules\",\"kind\":\"directory\",\"sha256\":null},{\"relative\":\"iii7/rollback-iii7-20261116-1-144931/files/apps/api/src/sinegor/modules/agreements\",\"kind\":\"directory\",\"sha256\":null},{\"relative\":\"iii7/rollback-iii7-20261116-1-144931/files/apps/api/src/sinegor/modules/agreements/service.py\",\"kind\":\"file\",\"sha256\":\"ffa293159084a1faa42b313216ced6dfea0f7dbe84fc67420a1669a22bedf208\"},{\"relative\":\"iii7/rollback-iii7-20261116-1-144931/files/apps/api/src/sinegor/jobs/cleanup_agreements.py\",\"kind\":\"file\",\"sha256\":\"ae2bbf9c36880717410037f60e58ab976cbc714366b198dacf5b5f3827e0a1ba\"},{\"relative\":\"iii7/rollback-iii7-20261116-1-144931/files/apps/api/src/sinegor/jobs/cleanup_business.py\",\"kind\":\"file\",\"sha256\":\"5d068b16c6449669d09b65131731169fb88dffd7eedf8088dc4658779e31d965\"},{\"relative\":\"iii7/rollback-iii7-20261116-1-144931/files/apps/api/src/sinegor/jobs/process_destructions.py\",\"kind\":\"file\",\"sha256\":\"1ea30413d105ddccb3389964cd089171247c831c4df5ac67f382a572bdd18595\"},{\"relative\":\"iii7/rollback-iii7-20261116-1-144931/files/apps/api/src/sinegor/jobs/process_notifications.py\",\"kind\":\"file\",\"sha256\":\"37777a06f6893f1434d64add93fab021fc3684b1704f042fe1f5103a30d9afd1\"},{\"relative\":\"iii7/rollback-iii7-20261116-1-144931/files/apps/api/src/sinegor/jobs/process_orders.py\",\"kind\":\"file\",\"sha256\":\"84815103efe33ecbd3183a215134bd3cb5681792932c814c8b893b5320c4c938\"},{\"relative\":\"iii7/rollback-iii7-20261116-1-144931/files/apps/api/src/sinegor/jobs/purge_analytics.py\",\"kind\":\"file\",\"sha256\":\"2ceed30de55d8a124faba2c69dc4b18dd27df55209e343daf15675257a40bb1f\"},{\"relative\":\"iii7/rollback-iii7-20261116-1-144931/files/apps/api/src/sinegor/jobs/purge_auth.py\",\"kind\":\"file\",\"sha256\":\"fd9c5107afbf28d4c2789586e1a223878ccc9dd1b2b7f05c9ae0a745b0e4aee0\"},{\"relative\":\"iii7/rollback-iii7-20261116-1-144931/files/apps/api/src/sinegor/jobs/purge_security_events.py\",\"kind\":\"file\",\"sha256\":\"132fa9566532a239c9709c1f86b0377a92c4907fd9135b90ad0d19c4904d505a\"},{\"relative\":\"iii7/rollback-iii7-20261116-1-144931/files/infra/compose\",\"kind\":\"directory\",\"sha256\":null},{\"relative\":\"iii7/rollback-iii7-20261116-1-144931/files/infra/compose/production.env.example\",\"kind\":\"file\",\"sha256\":null},{\"relative\":\"iii7/rollback-iii7-20261116-1-144931/files/infra/compose/production.yaml\",\"kind\":\"file\",\"sha256\":\"29d8438e50dbec3b41aa37bbbffda8516d2dd250c29d5544240f9a877d2b1dfe\"},{\"relative\":\"iii7/deploy-20261116/__pycache__\",\"kind\":\"directory\",\"sha256\":null},{\"relative\":\"iii7/deploy-20261116/deploy.py\",\"kind\":\"file\",\"sha256\":\"72b20eaa2be1c69ad25ceb6f4dadcf340dc0a9fb1b09be91f737b680934478ab\"},{\"relative\":\"iii7/deploy-20261116/deployment-evidence.json\",\"kind\":\"file\",\"sha256\":\"11a4c96c2e4aa8762876008f9a04d56c640e5d08d1cdd0338cb9308e5dce3f0a\"},{\"relative\":\"iii7/deploy-20261116/manifest.json\",\"kind\":\"file\",\"sha256\":\"85106f0de21f2da35b39d7fb239a7465bb247b1ea11f27077f683f12768bb20c\"},{\"relative\":\"iii7/deploy-20261116/payload\",\"kind\":\"directory\",\"sha256\":null},{\"relative\":\"iii7/deploy-20261116/root-preflight.py\",\"kind\":\"file\",\"sha256\":\"e1446481da875db9b0a41e5a969ca070a63aeaa91d297e57d2b93e53ad8694bb\"},{\"relative\":\"iii7/deploy-20261116/payload/apps\",\"kind\":\"directory\",\"sha256\":null},{\"relative\":\"iii7/deploy-20261116/payload/infra\",\"kind\":\"directory\",\"sha256\":null},{\"relative\":\"iii7/deploy-20261116/payload/apps/api\",\"kind\":\"directory\",\"sha256\":null},{\"relative\":\"iii7/deploy-20261116/payload/apps/api/src\",\"kind\":\"directory\",\"sha256\":null},{\"relative\":\"iii7/deploy-20261116/payload/apps/api/src/sinegor\",\"kind\":\"directory\",\"sha256\":null},{\"relative\":\"iii7/deploy-20261116/payload/apps/api/src/sinegor/jobs\",\"kind\":\"directory\",\"sha256\":null},{\"relative\":\"iii7/deploy-20261116/payload/apps/api/src/sinegor/modules\",\"kind\":\"directory\",\"sha256\":null},{\"relative\":\"iii7/deploy-20261116/payload/apps/api/src/sinegor/modules/agreements\",\"kind\":\"directory\",\"sha256\":null},{\"relative\":\"iii7/deploy-20261116/payload/apps/api/src/sinegor/modules/agreements/service.py\",\"kind\":\"file\",\"sha256\":\"79df17fe875b25633cc1d606513e9d388818b2128e9dc09084cf8e7790518826\"},{\"relative\":\"iii7/deploy-20261116/payload/apps/api/src/sinegor/jobs/check_status.py\",\"kind\":\"file\",\"sha256\":\"fca13cde65089277d9046e2e482f515d214dddd89586432893c97c259dccd610\"},{\"relative\":\"iii7/deploy-20261116/payload/apps/api/src/sinegor/jobs/cleanup_agreements.py\",\"kind\":\"file\",\"sha256\":\"8f13e80213cdc116d8abd07695cdabc794ecb9c9ae540119d9a55844d6559db5\"},{\"relative\":\"iii7/deploy-20261116/payload/apps/api/src/sinegor/jobs/cleanup_business.py\",\"kind\":\"file\",\"sha256\":\"974e202c33627898c63d6ebcde298c3608b4b256e787ae308034ff7f090ea109\"},{\"relative\":\"iii7/deploy-20261116/payload/apps/api/src/sinegor/jobs/process_destructions.py\",\"kind\":\"file\",\"sha256\":\"0648544fa5ba3ec7316a855ac39c7690309d36fcbab77c3eb5c790320278edef\"},{\"relative\":\"iii7/deploy-20261116/payload/apps/api/src/sinegor/jobs/process_notifications.py\",\"kind\":\"file\",\"sha256\":\"61cbeea9167a731acdc2f2e0dd9b5cd88a6d399be25bc475ccb4e0dbde177d7f\"},{\"relative\":\"iii7/deploy-20261116/payload/apps/api/src/sinegor/jobs/process_orders.py\",\"kind\":\"file\",\"sha256\":\"ac770b8643f9202866ee87ec64e41359fddc140c6aadaa508f8e68c8ffc0e7e0\"},{\"relative\":\"iii7/deploy-20261116/payload/apps/api/src/sinegor/jobs/purge_analytics.py\",\"kind\":\"file\",\"sha256\":\"1d33565ae63828b8a481636a5fe805c7574bdd4d139c3b6b39789202f1d67c5a\"},{\"relative\":\"iii7/deploy-20261116/payload/apps/api/src/sinegor/jobs/purge_auth.py\",\"kind\":\"file\",\"sha256\":\"b4ddefad444303b6e6c0eb46f3d479e47ea3fe2af20e72823b6ccf4948fed7b0\"},{\"relative\":\"iii7/deploy-20261116/payload/apps/api/src/sinegor/jobs/purge_security_events.py\",\"kind\":\"file\",\"sha256\":\"2fdbaf65f5a1bbbfc3cfa622ce8bc6ad93454bd8ad92cffcf063b77d365160fe\"},{\"relative\":\"iii7/deploy-20261116/payload/apps/api/src/sinegor/jobs/runtime.py\",\"kind\":\"file\",\"sha256\":\"b3a22b0435fb2d0d1a02039acb0d26912b510f517d4721ad24163782b919c304\"},{\"relative\":\"iii7/deploy-20261116/payload/infra/compose\",\"kind\":\"directory\",\"sha256\":null},{\"relative\":\"iii7/deploy-20261116/payload/infra/scheduler\",\"kind\":\"directory\",\"sha256\":null},{\"relative\":\"iii7/deploy-20261116/payload/infra/compose/production.env.example\",\"kind\":\"file\",\"sha256\":null},{\"relative\":\"iii7/deploy-20261116/payload/infra/compose/production.yaml\",\"kind\":\"file\",\"sha256\":\"53d5550c40be429fa1c72376340b1157ed9ea49dbf562f30c87193fc0cf1bc6e\"},{\"relative\":\"iii7/deploy-20261116/payload/infra/scheduler/jobs.env.example\",\"kind\":\"file\",\"sha256\":null},{\"relative\":\"iii7/deploy-20261116/payload/infra/scheduler/run_jobs.py\",\"kind\":\"file\",\"sha256\":\"7045513d6cded66b95bb6c4a3556aff8f5132997ec32a0fbcd089cffd148dfc7\"},{\"relative\":\"iii7/deploy-20261116/payload/infra/scheduler/sinegor-job-cleanup_agreements.timer\",\"kind\":\"file\",\"sha256\":\"9796e463b4ae3b626bf47d7eb04bf6c94febe0a329ce286aeeb7a6031848e3a7\"},{\"relative\":\"iii7/deploy-20261116/payload/infra/scheduler/sinegor-job-cleanup_business.timer\",\"kind\":\"file\",\"sha256\":\"a435c58d5d29e3f4873161aa06d324af2c54ad2ce76476b5d6e07e762e4df9a0\"},{\"relative\":\"iii7/deploy-20261116/payload/infra/scheduler/sinegor-job-minute.timer\",\"kind\":\"file\",\"sha256\":\"910d02860069ab6bda9212b9396e232d309fcc347cc483f534646eb4d92c9ef0\"},{\"relative\":\"iii7/deploy-20261116/payload/infra/scheduler/sinegor-job-purge_analytics.timer\",\"kind\":\"file\",\"sha256\":\"76856112517f9199052f03b49fe4868c329746823afba2d760271e993f255dec\"},{\"relative\":\"iii7/deploy-20261116/payload/infra/scheduler/sinegor-job-purge_auth.timer\",\"kind\":\"file\",\"sha256\":\"6643fb299a6e03ff09c76e17b271af24660ec16d3ecf9ed5d292eb76543814df\"},{\"relative\":\"iii7/deploy-20261116/payload/infra/scheduler/sinegor-job-purge_security_events.timer\",\"kind\":\"file\",\"sha256\":\"89e34ddaa421ccc66f9bdddcccf603e02fe610df93f50ae65df618bbf3e281e1\"},{\"relative\":\"iii7/deploy-20261116/payload/infra/scheduler/sinegor-job@.service\",\"kind\":\"file\",\"sha256\":\"ab185b81bcfa67806c2eec32f6ac63ee08d8d2539ae2147ba957cafcdce39d49\"},{\"relative\":\"iii7/deploy-20261116/payload/infra/scheduler/sinegor-jobs-watchdog.service\",\"kind\":\"file\",\"sha256\":\"b4471aa4c681156df785c526c5f2b607bc1983fcc3e7be29a15000ea7fa80509\"},{\"relative\":\"iii7/deploy-20261116/payload/infra/scheduler/sinegor-jobs-watchdog.timer\",\"kind\":\"file\",\"sha256\":\"7398413b0e2d285775951e89a4f662ca9d4064ca343ddaabde6e6a69213e339e\"},{\"relative\":\"iii7/deploy-20261116/__pycache__/deploy.cpython-313.pyc\",\"kind\":\"file\",\"sha256\":null},{\"relative\":\"iii7/deploy-20261116/__pycache__/root-preflight.cpython-313.pyc\",\"kind\":\"file\",\"sha256\":null},{\"relative\":\"iii7/restart-acceptance-20261116/acceptance.service\",\"kind\":\"file\",\"sha256\":\"f83d78ab0dcc2c27e7922be6ae09f37601111bd67293691258393b848b8cb0f8\"},{\"relative\":\"iii7/restart-acceptance-20261116/deploy.py\",\"kind\":\"file\",\"sha256\":\"310cc1bc19496576e837d67ac568c74898765ccb51db18ee8ec6d78bf5287608\"},{\"relative\":\"iii7/restart-acceptance-20261116/manifest.json\",\"kind\":\"file\",\"sha256\":\"6d5af933a84939218769f2bc0fe91e570eabe258601f14895ebd8a7529ddf3ba\"},{\"relative\":\"iii7/restart-acceptance-20261116/restart-evidence.json\",\"kind\":\"file\",\"sha256\":\"6e5cb6a56e23df86090ee67838ceea96cd282f924fe2c1cf1d08b393a89c7043\"},{\"relative\":\"iii6-ip-r-8a078cd57a33bf8635398c30d6c249d6/connection.json\",\"kind\":\"file\",\"sha256\":null},{\"relative\":\"iii6-ip-r-8a078cd57a33bf8635398c30d6c249d6/result.json\",\"kind\":\"file\",\"sha256\":\"8b8399eee28dd88b20989d0102d93955aa2f5577c3878c7737d045f250b391f6\"},{\"relative\":\"iii6-c3-28a33d70c17d4101018bb67fb1648f86/browser-result.json\",\"kind\":\"file\",\"sha256\":\"21fe71a1ee07bdf0b40b8f6ae3808310011100761e5109c881e96f17c38993ff\"},{\"relative\":\"https/cms-client-ca.pem\",\"kind\":\"file\",\"sha256\":null}]")
REPORT_TEXT="# SINEGOR LAB — перенос категории C\n\nДата: 17.11.2026, Europe/Moscow.\n\nПо существующей классификации перенесены **54 файла и 26 каталогов** из private в `/home/sinegoradmin/apps/sinegor-app-artifacts/archive/`:\n\n- `III-5/` — reboot baseline, 1 файл.\n- `III-6/` — browser result, connection/results IP и историческая публичная CA-копия, 5 файлов.\n- `III-7/` — весь прежний комплект iii7, 48 файлов: deploy/payload/manifests/evidence, restart acceptance и root-owned rollback.\n\nВыполнены 7 переименований на том же разделе, без копирования и удаления материалов. Сохранены inode, содержимое, владельцы, права и mtime. Хранилище закрыто правами 0700. Материалы C вне private (включая III-4) не затрагивались.\n\nАктуальный rollback: `archive/III-7/rollback-iii7-20261116-1-144931`. Конкретные файлы с абсолютными историческими ссылками перечислены в evidence. Исходные manifests, evidence, установщик и тест reboot сохранены побайтно. При восстановлении прежний архивный префикс заменяется по `infra/scheduler/RECOVERY.md`. Рабочие Compose/env/systemd/Certbot пути не менялись.\n\nВ AGENTS.md закреплено хранение исторических материалов следующих этапов в artifacts/archive по каталогам этапов. В infra/README.md добавлена ссылка на актуальную инструкцию восстановления.\n\nПроверены все 80 объектов по готовому перечню: полнота, одинаковые inode/содержимое/метаданные, отсутствие прежних source paths и разрешение recovery paths. Проверены исходный bundle и checksum rollback manifest. Нового аудита, адаптации исторических тестов, изменений приложения, production-конфигураций и Git не выполнялось. Комплексные production-проверки в ходе переноса не запускались.\n\nПрепятствий для переноса не осталось. Конфигурации B размещены в репозитории без переключения production; применение новых рабочих путей требует отдельного согласования.\n"
MOVES=[
 ('iii5-reboot-baseline-2026-11-15.json','III-5/iii5-reboot-baseline-2026-11-15.json'),
 ('iii6-ip-r-74cc255b61332b32cbcd72002fd5eae6/connection.json','III-6/iii6-ip-r-74cc255b61332b32cbcd72002fd5eae6/connection.json'),
 ('iii6-ip-r-8a078cd57a33bf8635398c30d6c249d6/connection.json','III-6/iii6-ip-r-8a078cd57a33bf8635398c30d6c249d6/connection.json'),
 ('iii6-ip-r-8a078cd57a33bf8635398c30d6c249d6/result.json','III-6/iii6-ip-r-8a078cd57a33bf8635398c30d6c249d6/result.json'),
 ('iii6-c3-28a33d70c17d4101018bb67fb1648f86/browser-result.json','III-6/iii6-c3-28a33d70c17d4101018bb67fb1648f86/browser-result.json'),
 ('https/cms-client-ca.pem','III-6/https/cms-client-ca.pem'),
 ('iii7','III-7')]
LIBC=ctypes.CDLL(None,use_errno=True)
LIBC.renameat2.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
LIBC.renameat2.restype=ctypes.c_int

def rename_no_replace(source,dest):
 if LIBC.renameat2(-100,os.fsencode(source),-100,os.fsencode(dest),1):
  raise OSError(ctypes.get_errno(),'GuardedRenameFailed',str(source))

def fingerprint(path):
 st=path.lstat()
 if not (stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode)):
  raise ValueError('UnexpectedSourceType')
 v={'device':st.st_dev,'inode':st.st_ino,'mode':st.st_mode,'uid':st.st_uid,'gid':st.st_gid,
    'size':st.st_size,'mtime_ns':st.st_mtime_ns,'nlink':st.st_nlink}
 if stat.S_ISREG(st.st_mode):v['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
 return v

def destination(relative):
 if relative=='iii7':return NEW_III7
 if relative.startswith('iii7/'):return NEW_III7/relative.removeprefix('iii7/')
 return ARCHIVE/dict(MOVES)[relative]

def ensure_directory(path):
 if path.exists() or path.is_symlink():
  st=path.lstat()
  if not stat.S_ISDIR(st.st_mode) or stat.S_IMODE(st.st_mode)!=0o700 or st.st_uid!=1000 or st.st_gid!=1000:
   raise PermissionError('UnsafeArchiveDirectory')
  return
 if not path.parent.exists():ensure_directory(path.parent)
 path.mkdir(mode=0o700);os.chown(path,1000,1000)

def write_report(path,data):
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o644)
 with os.fdopen(fd,'wb') as stream:
  stream.write(data);stream.flush();os.fsync(stream.fileno())
 os.chown(path,1000,1000)

def main():
 if os.geteuid()!=0 or sys.argv[1:]!=['--apply-category-c']:
  raise PermissionError('ExplicitRootApplyRequired')
 os.umask(0o077)
 reports=ROOT/'docs/reports'
 result_path=reports/'production-layout-category-c-result-2026-11-17.md'
 evidence_path=reports/'production-layout-category-c-evidence-2026-11-17.json'
 for p in (result_path,evidence_path):
  if p.exists() or p.is_symlink():raise FileExistsError('ReportAlreadyExists')
 if len(EXPECTED)!=80 or sum(x['kind']=='file' for x in EXPECTED)!=54:
  raise ValueError('ClassificationScopeMismatch')
 required={x['relative'] for x in EXPECTED if x['relative']=='iii7' or x['relative'].startswith('iii7/')}
 actual={'iii7'}
 for directory,dirs,files in os.walk(OLD_III7,followlinks=False):
  for name in dirs+files:actual.add(str((Path(directory)/name).relative_to(PRIVATE)))
 if actual!=required:raise ValueError('III7MoveScopeChanged')
 snapshots={}
 for row in EXPECTED:
  value=fingerprint(PRIVATE/row['relative'])
  if (row['kind']=='file')!=('sha256' in value):raise ValueError('ClassifiedTypeChanged')
  if row['sha256'] and value.get('sha256')!=row['sha256']:raise ValueError('ClassifiedHistoricalFileChanged')
  if value['device']!=ARTIFACTS.parent.stat().st_dev:raise OSError(errno.EXDEV,'SameFilesystemRequired')
  snapshots[row['relative']]=value
 for relative,target in MOVES:
  p=ARCHIVE/target
  if p.exists() or p.is_symlink():raise FileExistsError('ArchiveTargetAlreadyExists')
 observer=Path('/etc/systemd/system/sinegor-iii7-restart-acceptance.service')
 if observer.exists() or observer.is_symlink():raise RuntimeError('OwnerApprovalRequiredObserverStillInstalled')
 runtime_paths=[Path('/usr/local/lib/sinegor/run_jobs.py'),Path('/etc/sinegor/jobs.env'),
                Path('/etc/systemd/system/sinegor-job@.service'),Path('/etc/systemd/system/sinegor-jobs-watchdog.service')]
 for p in runtime_paths:
  if str(OLD_III7).encode() in p.read_bytes():raise RuntimeError('OwnerApprovalRequiredRuntimeArchiveReference')
 references=[]
 pattern=re.compile(re.escape(str(OLD_III7))+r'/[A-Za-z0-9_./-]+')
 for row in EXPECTED:
  relative=row['relative'];p=PRIVATE/relative
  if row['kind']!='file' or not relative.startswith('iii7/') or p.suffix not in ('.json','.py','.service'):continue
  for old in sorted(set(pattern.findall(p.read_text()))):
   new=NEW_III7/Path(old).relative_to(OLD_III7)
   references.append({'file':str(destination(relative)),'historical_path':old,
                      'current_path':str(new),'target_existed_before':Path(old).exists()})
 ensure_directory(ARTIFACTS);ensure_directory(ARCHIVE)
 journal=[]
 try:
  for relative,target in MOVES:
   source,dest=PRIVATE/relative,ARCHIVE/target
   ensure_directory(dest.parent)
   for row in EXPECTED:
    if row['relative']==relative or row['relative'].startswith(relative+'/'):
     if fingerprint(PRIVATE/row['relative'])!=snapshots[row['relative']]:raise RuntimeError('SourceChangedBeforeRename')
   rename_no_replace(source,dest);journal.append((source,dest))
  for row in EXPECTED:
   relative=row['relative']
   if (PRIVATE/relative).exists() or (PRIVATE/relative).is_symlink():raise RuntimeError('OriginalStillPresent')
   if fingerprint(destination(relative))!=snapshots[relative]:raise RuntimeError('MovedObjectIdentityChanged')
  for ref in references:
   if ref['target_existed_before'] and not Path(ref['current_path']).exists():raise RuntimeError('RecoveryPathMissing')
  release=NEW_III7/'deploy-20261116';manifest=json.loads((release/'manifest.json').read_text())
  for name,h in manifest['bundle_hashes'].items():
   relative=Path(name)
   if relative.is_absolute() or '..' in relative.parts:raise ValueError('UnsafeHistoricalBundlePath')
   if hashlib.sha256((release/relative).read_bytes()).hexdigest()!=h:raise RuntimeError('HistoricalBundleChecksumMismatch')
  resume=manifest['resume_from'];resolved=NEW_III7/Path(resume['backup']).relative_to(OLD_III7)
  if resolved!=NEW_III7/'rollback-iii7-20261116-1-144931':raise RuntimeError('RecoveryManifestPathMismatch')
  if hashlib.sha256((resolved/'manifest.json').read_bytes()).hexdigest()!=resume['manifest_sha256']:
   raise RuntimeError('RecoveryManifestChecksumMismatch')
 except Exception:
  failures=[]
  for source,dest in reversed(journal):
   try:rename_no_replace(dest,source)
   except OSError:failures.append(str(source))
  print(json.dumps({'move_failed':True,'moves_reversed':len(journal)-len(failures),'paths_needing_attention':failures}))
  raise
 evidence={'task':'category-C-only','date':'2026-11-17','timezone':'Europe/Moscow',
  'classification_source':'production-layout-classification-2026-11-16.json',
  'moved_files':54,'moved_classified_directories':26,'rename_operations':len(journal),'archive_root':str(ARCHIVE),
  'moves':[{'from':str(a),'to':str(b)} for a,b in journal],
  'checks':{'same_filesystem':True,'same_inodes_and_contents':True,'ownership_modes_mtime_preserved':True,
            'source_paths_absent':True,'historical_bundle_checksums_valid':True,'rollback_manifest_checksum_valid':True,
            'existing_recovery_targets_resolve_at_new_paths':True},
  'iii7_absolute_path_references':references,'historical_test_scripts_modified':False,
  'historical_manifest_bytes_modified':False,'additional_archive_copies_created':False,
  'external_category_c_modified':False,'production_files_modified':False,'services_restarted':False,
  'new_audit_performed':False,'production_comprehensive_checks_performed':False,'git_mutations':False,
  'recovery_instructions':str(ROOT/'infra/scheduler/RECOVERY.md')}
 write_report(evidence_path,(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n').encode())
 write_report(result_path,REPORT_TEXT.encode())
 print(json.dumps({'category_c_move_completed':True,'files':54,'classified_directories':26,'rename_operations':7,
                   'archive_root':str(ARCHIVE),'checks_passed':True,'production_touched':False,'report':str(result_path)},ensure_ascii=False))

if __name__=='__main__':
 try:main()
 except Exception as exc:
  frame=traceback.extract_tb(exc.__traceback__)[-1]
  print(json.dumps({'category_c_failed':True,'error_type':type(exc).__name__,
   'safe_reason':str(exc) if isinstance(exc,(ValueError,RuntimeError,PermissionError,FileExistsError)) else None,
   'errno':getattr(exc,'errno',None),'line':frame.lineno}))
  raise SystemExit(1) from None
