#!/usr/bin/env python3
import csv, json, random, re, time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'output_pb'
OUT.mkdir(exist_ok=True)
raw = ''.join((ROOT / f'inns_1000.part{i}').read_text(encoding='utf-8') for i in range(1,5))
INNS = [x.strip() for x in raw.splitlines() if re.fullmatch(r'\d{10}', x.strip())]
assert len(INNS) == 1000 and len(set(INNS)) == 1000

URL='https://pb.nalog.ru/search-proc.json'
S=requests.Session()
S.headers.update({
  'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36',
  'X-Requested-With':'XMLHttpRequest',
  'Referer':'https://pb.nalog.ru/search.html',
  'Origin':'https://pb.nalog.ru',
  'Accept':'application/json, text/javascript, */*; q=0.01',
})

def classify(code):
    m=re.match(r'^(\d{2})', (code or '').strip())
    if not m: return 'НЕ ОПРЕДЕЛЕНО','REVIEW'
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

def one(inn):
    data={'page':'1','pageSize':'10','pbCaptchaToken':'','token':'','mode':'search-ul','queryAll':'','queryUl':inn,
      'okvedUl':'','statusUl':'','regionUl':'','isMspUl':'','mspUl1':'1','mspUl2':'2','mspUl3':'3',
      'queryIp':'','okvedIp':'','statusIp':'','regionIp':'','isMspIp':'','mspIp1':'1','mspIp2':'2','mspIp3':'3',
      'queryUpr':'','uprType1':'1','uprType0':'1','queryRdl':'','dateRdl':'','queryAddr':'','regionAddr':'',
      'queryOgr':'','ogrFl':'1','ogrUl':'1','npTypeDoc':'1','ogrnUlDoc':'','ogrnIpDoc':'','nameUlDoc':'','nameIpDoc':'',
      'formUlDoc':'','formIpDoc':'','ifnsDoc':'','dateFromDoc':'','dateToDoc':''}
    r=S.post(URL,data=data,timeout=30)
    if r.status_code in (403,429): return {'status':f'HTTP_{r.status_code}'}
    j=r.json()
    if j.get('captchaRequired') or j.get('pbRateLimit'): return {'status':'CAPTCHA_OR_RATE_LIMIT'}
    result=j
    reqid=j.get('id')
    if reqid:
        result=None
        for _ in range(12):
            time.sleep(0.4)
            rr=S.post(URL,data={'id':reqid,'method':'get-response'},timeout=30)
            if rr.status_code in (403,429): return {'status':f'HTTP_{rr.status_code}'}
            try: x=rr.json()
            except Exception: continue
            if x is not None:
                result=x; break
        if result is None:return {'status':'POLL_TIMEOUT'}
    if isinstance(result,dict) and (result.get('captchaRequired') or result.get('pbRateLimit')):
        return {'status':'CAPTCHA_OR_RATE_LIMIT'}
    ul=(result or {}).get('ul') if isinstance(result,dict) else None
    rows=(ul or {}).get('data',[]) if isinstance(ul,dict) else []
    exact=next((x for x in rows if str(x.get('inn',''))==inn), rows[0] if rows else None)
    if not exact:return {'status':'NOT_FOUND'}
    okved=str(exact.get('okved2main') or exact.get('okved') or '')
    bt,eligible=classify(okved)
    return {'status':'OK','name':exact.get('namec') or exact.get('namep') or exact.get('name') or '',
      'ogrn':exact.get('ogrn') or '', 'okved':okved, 'business_type':bt,'eligible':eligible,
      'status_text':exact.get('sulst_name_ex') or exact.get('status') or ''}

fields=['ИНН','Наименование','ОГРН','Основной ОКВЭД','Тип деятельности','Соответствует policy','Статус ЮЛ','PB статус']
rows=[]; blocked=0
for idx,inn in enumerate(INNS,1):
    try: res=one(inn)
    except Exception as e: res={'status':'ERROR:'+type(e).__name__}
    rows.append({'ИНН':inn,'Наименование':res.get('name',''),'ОГРН':res.get('ogrn',''),'Основной ОКВЭД':res.get('okved',''),
      'Тип деятельности':res.get('business_type',''),'Соответствует policy':res.get('eligible',''),
      'Статус ЮЛ':res.get('status_text',''),'PB статус':res.get('status','')})
    if res.get('status') in ('CAPTCHA_OR_RATE_LIMIT','HTTP_429','HTTP_403'): blocked+=1
    else: blocked=0
    if idx%25==0 or idx==len(INNS):
        with (OUT/'pb_first1000.csv').open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields,delimiter=';');w.writeheader();w.writerows(rows)
        ok=sum(r['PB статус']=='OK' for r in rows)
        print(f'{idx}/1000 OK={ok} last={res.get("status")}',flush=True)
    if blocked>=10:
        print('Stopping after 10 consecutive CAPTCHA/rate-limit responses',flush=True);break
    time.sleep(random.uniform(0.12,0.28))

summary={'attempted':len(rows),'ok':sum(r['PB статус']=='OK' for r in rows),
 'with_okved':sum(bool(r['Основной ОКВЭД']) for r in rows),
 'statuses':{s:sum(r['PB статус']==s for r in rows) for s in sorted(set(r['PB статус'] for r in rows))}}
(OUT/'summary_pb.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False),flush=True)
