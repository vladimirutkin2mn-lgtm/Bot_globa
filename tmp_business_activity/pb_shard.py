#!/usr/bin/env python3
import csv, json, os, random, re, time
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parent
PART=int(os.environ['PB_PART'])
INNS=[x.strip() for x in (ROOT/f'inns_1000.part{PART}').read_text(encoding='utf-8').splitlines() if re.fullmatch(r'\d{10}',x.strip())]
assert len(INNS)==250, (PART,len(INNS))
OUT=ROOT/f'output_pb_part{PART}'; OUT.mkdir(exist_ok=True)
URL='https://pb.nalog.ru/search-proc.json'
S=requests.Session(); S.headers.update({'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36','X-Requested-With':'XMLHttpRequest','Referer':'https://pb.nalog.ru/search.html','Origin':'https://pb.nalog.ru','Accept':'application/json, text/javascript, */*; q=0.01'})

def classify(code):
 m=re.match(r'^(\d{2})',(code or '').strip())
 if not m:return 'НЕ ОПРЕДЕЛЕНО','REVIEW'
 x=int(m.group(1))
 if 10<=x<=33:return 'ПРОИЗВОДСТВО','YES'
 if x==46:return 'ОПТ','YES'
 if x==47:return 'РОЗНИЦА','YES'
 if 49<=x<=53 or 55<=x<=56 or 58<=x<=63 or 69<=x<=75 or 77<=x<=82 or 85<=x<=88 or 90<=x<=96:return 'УСЛУГИ','YES'
 if 1<=x<=3:return 'СЕЛЬСКОЕ ХОЗЯЙСТВО','NO'
 if 5<=x<=9:return 'ДОБЫЧА','NO'
 if 35<=x<=39:return 'ЭНЕРГЕТИКА / ЖКХ','REVIEW'
 if 41<=x<=43:return 'СТРОИТЕЛЬСТВО','REVIEW'
 if x==45:return 'АВТОТОРГОВЛЯ / РЕМОНТ','REVIEW'
 if 64<=x<=66:return 'ФИНАНСЫ / СТРАХОВАНИЕ','NO'
 if x==68:return 'НЕДВИЖИМОСТЬ','REVIEW'
 return 'ПРОЧЕЕ','REVIEW'

def search(inn):
 d={'page':'1','pageSize':'10','pbCaptchaToken':'','token':'','mode':'search-ul','queryAll':'','queryUl':inn,'okvedUl':'','statusUl':'','regionUl':'','isMspUl':'','mspUl1':'1','mspUl2':'2','mspUl3':'3','queryIp':'','okvedIp':'','statusIp':'','regionIp':'','isMspIp':'','mspIp1':'1','mspIp2':'2','mspIp3':'3','queryUpr':'','uprType1':'1','uprType0':'1','queryRdl':'','dateRdl':'','queryAddr':'','regionAddr':'','queryOgr':'','ogrFl':'1','ogrUl':'1','npTypeDoc':'1','ogrnUlDoc':'','ogrnIpDoc':'','nameUlDoc':'','nameIpDoc':'','formUlDoc':'','formIpDoc':'','ifnsDoc':'','dateFromDoc':'','dateToDoc':''}
 r=S.post(URL,data=d,timeout=25)
 if r.status_code in (403,429):return {'s':f'HTTP_{r.status_code}'}
 j=r.json()
 if j.get('captchaRequired') or j.get('pbRateLimit'):return {'s':'CAPTCHA_OR_RATE_LIMIT'}
 res=j
 if j.get('id'):
  res=None
  for _ in range(8):
   time.sleep(.35)
   rr=S.post(URL,data={'id':j['id'],'method':'get-response'},timeout=25)
   if rr.status_code in (403,429):return {'s':f'HTTP_{rr.status_code}'}
   try:x=rr.json()
   except Exception:continue
   if x is not None:res=x;break
  if res is None:return {'s':'POLL_TIMEOUT'}
 if isinstance(res,dict) and (res.get('captchaRequired') or res.get('pbRateLimit')):return {'s':'CAPTCHA_OR_RATE_LIMIT'}
 ul=(res or {}).get('ul') if isinstance(res,dict) else None; data=(ul or {}).get('data',[]) if isinstance(ul,dict) else []
 row=next((z for z in data if str(z.get('inn',''))==inn),data[0] if data else None)
 if not row:return {'s':'NOT_FOUND'}
 ok=str(row.get('okved2main') or row.get('okved') or '')
 bt,el=classify(ok)
 return {'s':'OK','name':row.get('namec') or row.get('namep') or row.get('name') or '','ogrn':row.get('ogrn') or '','okved':ok,'bt':bt,'el':el,'state':row.get('sulst_name_ex') or row.get('status') or ''}

fields=['ИНН','Наименование','ОГРН','Основной ОКВЭД','Тип деятельности','Соответствует policy','Статус ЮЛ','PB статус']
rows=[];blocked=0
for n,inn in enumerate(INNS,1):
 try:r=search(inn)
 except Exception as e:r={'s':'ERROR:'+type(e).__name__}
 rows.append({'ИНН':inn,'Наименование':r.get('name',''),'ОГРН':r.get('ogrn',''),'Основной ОКВЭД':r.get('okved',''),'Тип деятельности':r.get('bt',''),'Соответствует policy':r.get('el',''),'Статус ЮЛ':r.get('state',''),'PB статус':r.get('s','')})
 blocked=blocked+1 if r.get('s') in ('CAPTCHA_OR_RATE_LIMIT','HTTP_429','HTTP_403') else 0
 if n%25==0:print(f'part={PART} {n}/250 ok={sum(x["PB статус"]=="OK" for x in rows)} last={r.get("s")}',flush=True)
 if blocked>=8:
  print('STOP_BLOCKED',flush=True);break
 time.sleep(random.uniform(.08,.18))
with (OUT/f'pb_part{PART}.csv').open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.DictWriter(f,fieldnames=fields,delimiter=';');w.writeheader();w.writerows(rows)
summary={'part':PART,'attempted':len(rows),'ok':sum(x['PB статус']=='OK' for x in rows),'with_okved':sum(bool(x['Основной ОКВЭД']) for x in rows),'statuses':{s:sum(x['PB статус']==s for x in rows) for s in sorted(set(x['PB статус'] for x in rows))}}
(OUT/f'summary_part{PART}.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False),flush=True)
