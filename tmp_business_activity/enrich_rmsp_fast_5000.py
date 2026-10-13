#!/usr/bin/env python3
import csv, json, time, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import requests
from load_5000 import load

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'output_rmsp_fast_5000'; OUT.mkdir(exist_ok=True)
inns=load(); assert len(inns)==5000
local=threading.local()

def sess():
    s=getattr(local,'s',None)
    if s is None:
        s=requests.Session(); s.headers.update({'User-Agent':'Mozilla/5.0','Accept':'application/json','Content-Type':'application/x-www-form-urlencoded'})
        local.s=s
    return s

def lookup(inn):
    payload={'mode':'quick','query':inn,'sortField':'NAME_EX','sort':'ASC'}
    last=''
    for a in range(4):
        try:
            r=sess().post('https://rmsp.nalog.ru/search-proc.json',data=payload,timeout=25)
            last=f'HTTP {r.status_code}'
            if r.status_code==429 or r.status_code>=500:
                time.sleep(1.5*(a+1)); continue
            if r.status_code!=200:
                return {'ИНН':inn,'Статус':'ERROR_'+last}
            j=r.json(); data=j.get('data') or []
            exact=[x for x in data if str(x.get('inn','')).strip()==inn]
            if not exact:
                return {'ИНН':inn,'Статус':'NOT_FOUND','rowCount':j.get('rowCount',0)}
            x=exact[0]
            return {
                'ИНН':inn,'Наименование':x.get('name_ex',''),'ОГРН':x.get('ogrn',''),
                'Основной ОКВЭД':x.get('okved1',''),'Название ОКВЭД':x.get('okved1name',''),
                'Категория МСП':x.get('category',''),'Регион':x.get('regioncode',''),
                'Дата включения МСП':x.get('dtregistry',''),'Активен':x.get('is_active',''),
                'Есть лицензии (флаг РМСП)':x.get('has_licenses',''),'Статус':'OK'
            }
        except Exception as e:
            last=repr(e); time.sleep(1.0*(a+1))
    return {'ИНН':inn,'Статус':'ERROR_'+last[:120]}

res={}
with ThreadPoolExecutor(max_workers=20) as ex:
    fut={ex.submit(lookup,i):i for i in inns}
    for n,f in enumerate(as_completed(fut),1):
        i=fut[f]
        try: res[i]=f.result()
        except Exception as e: res[i]={'ИНН':i,'Статус':'FATAL_'+repr(e)[:120]}
        if n%250==0: print('RMSP',n,'/5000',flush=True)

fields=['ИНН','Наименование','ОГРН','Основной ОКВЭД','Название ОКВЭД','Категория МСП','Регион','Дата включения МСП','Активен','Есть лицензии (флаг РМСП)','Статус','rowCount']
with (OUT/'rmsp_fast_5000.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=fields,delimiter=';',extrasaction='ignore'); w.writeheader(); w.writerows(res[i] for i in inns)
from collections import Counter
summary={'rows':5000,'statuses':dict(Counter(res[i].get('Статус','') for i in inns)),'with_okved':sum(bool(res[i].get('Основной ОКВЭД')) for i in inns)}
(OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
