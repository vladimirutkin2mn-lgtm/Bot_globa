import csv,json,requests,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'output_chz_1000'; OUT.mkdir(exist_ok=True)
inns=[]
for p in sorted(ROOT.glob('inns_1000.part*')):
    inns += [x.strip() for x in p.read_text().splitlines() if x.strip()]
assert len(inns)==1000, len(inns)
S=requests.Session(); S.headers.update({'User-Agent':'Mozilla/5.0','Accept':'application/json'})
base_urls=['https://markirovka.crpt.ru/api/v4/true-api','https://markirovka.crpt.ru/api/v3/true-api']
res={i:{'ИНН':i,'ЧЗ статус источника':'NOT_CHECKED','ЧЗ зарегистрирован':'','ЧЗ статус':'','ЧЗ наименование':'','ЧЗ роли':'','ЧЗ товарные группы':'','ЧЗ raw':''} for i in inns}

def compact(v):
    if isinstance(v,list): return '; '.join(str(x) for x in v if x not in (None,''))
    if isinstance(v,dict): return json.dumps(v,ensure_ascii=False,separators=(',',':'))[:1500]
    return '' if v is None else str(v)

def get_any(d,*keys):
    if not isinstance(d,dict): return None
    low={str(k).lower():v for k,v in d.items()}
    for k in keys:
        if k.lower() in low: return low[k.lower()]
    return None

for bi in range(0,1000,100):
    batch=inns[bi:bi+100]
    ok=False; last=''
    for base in base_urls:
        params=[('inns',x) for x in batch]
        for headers in ({}, {'Authorization':'Bearer null'}):
            try:
                r=S.get(base+'/participants',params=params,headers=headers,timeout=35)
                last=f'{base} HTTP {r.status_code}'
                if r.status_code!=200: continue
                data=r.json()
                items=data if isinstance(data,list) else (data.get('items') or data.get('results') or data.get('participants') or [])
                if isinstance(items,dict): items=list(items.values())
                # Some versions return a single dict keyed by INN or one participant object.
                if not items and isinstance(data,dict):
                    if get_any(data,'inn'): items=[data]
                    else:
                        cand=[v for v in data.values() if isinstance(v,dict) and get_any(v,'inn')]
                        if cand: items=cand
                seen=set()
                for d in items:
                    inn=str(get_any(d,'inn','participantInn') or '').strip()
                    if inn not in res: continue
                    seen.add(inn)
                    roles=get_any(d,'role','roles','organizationTypes','participantTypes')
                    pgs=get_any(d,'productGroups','productGroup','groups','goodsGroups')
                    registered=get_any(d,'is_registered','isRegistered','registered')
                    status=get_any(d,'status','statusInn','status_inn')
                    name=get_any(d,'name','fullName','organizationName')
                    res[inn].update({'ЧЗ статус источника':'OK','ЧЗ зарегистрирован':compact(registered),'ЧЗ статус':compact(status),'ЧЗ наименование':compact(name),'ЧЗ роли':compact(roles),'ЧЗ товарные группы':compact(pgs),'ЧЗ raw':json.dumps(d,ensure_ascii=False,separators=(',',':'))[:2500]})
                for inn in batch:
                    if inn not in seen:
                        res[inn]['ЧЗ статус источника']='OK_NOT_RETURNED'
                ok=True; break
            except Exception as e: last=repr(e)
        if ok: break
    if not ok:
        for inn in batch: res[inn]['ЧЗ статус источника']='ERROR: '+last[:180]
    print(f'CHZ {bi+len(batch)}/1000 ok={sum(1 for x in batch if res[x]["ЧЗ статус источника"]=="OK")}',flush=True)
    time.sleep(.3)
fields=list(next(iter(res.values())).keys())
with (OUT/'chz_1000.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=fields,delimiter=';'); w.writeheader(); w.writerows(res[i] for i in inns)
summary={'rows':1000,'source_ok':sum(1 for i in inns if res[i]['ЧЗ статус источника']=='OK'),'registered_true':sum(1 for i in inns if res[i]['ЧЗ зарегистрирован'].lower()=='true'),'with_roles':sum(1 for i in inns if res[i]['ЧЗ роли']),'statuses':{}}
for i in inns: summary['statuses'][res[i]['ЧЗ статус источника']]=summary['statuses'].get(res[i]['ЧЗ статус источника'],0)+1
(OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
