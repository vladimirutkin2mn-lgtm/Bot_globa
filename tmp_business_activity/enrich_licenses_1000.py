import csv,json,re,requests,zipfile,io
from pathlib import Path
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parent; OUT=ROOT/'output_licenses_1000'; OUT.mkdir(exist_ok=True)
inns=[]
for p in sorted(ROOT.glob('inns_1000.part*')): inns += [x.strip() for x in p.read_text().splitlines() if x.strip()]
T=set(inns); assert len(inns)==1000
S=requests.Session(); S.headers.update({'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/140 Safari/537.36','Accept':'*/*'})
res={i:{'ИНН':i,'Лицензия найдена':'NO','Лицензии количество':0,'Лицензии типы':'','Лицензии источники':'','Лицензии статус проверки':'PARTIAL_OK'} for i in inns}
agg={i:{'types':set(),'sources':set(),'count':0} for i in inns}
diag=[]

def match_bytes(data, lic_type, source):
    # INNs are ASCII digits in CSV/XML; exact 10-digit extraction avoids fuzzy matches.
    found=set(x.decode() for x in re.findall(rb'(?<!\d)\d{10}(?!\d)',data) if x.decode() in T)
    for inn in found:
        agg[inn]['types'].add(lic_type); agg[inn]['sources'].add(source); agg[inn]['count']+=1
    return len(found)

def download_and_scan_zip(url,lic_type):
    try:
        r=S.get(url,timeout=120); rec={'type':lic_type,'url':url,'status':r.status_code,'size':len(r.content)}
        if r.status_code!=200: diag.append(rec); return False
        z=zipfile.ZipFile(io.BytesIO(r.content)); total=set()
        for n in z.namelist():
            if n.lower().endswith(('.xml','.csv','.txt')):
                data=z.read(n); f=set(x.decode() for x in re.findall(rb'(?<!\d)\d{10}(?!\d)',data) if x.decode() in T); total |= f
        for inn in total:
            agg[inn]['types'].add(lic_type); agg[inn]['sources'].add(url); agg[inn]['count']+=1
        rec['matched']=len(total); rec['files']=len(z.namelist()); diag.append(rec); return True
    except Exception as e: diag.append({'type':lic_type,'url':url,'error':repr(e)}); return False

# Roszdravnadzor current public open-data dumps. Try freshest known host/date then fallbacks.
rz_sources={
 'Росздравнадзор: фармацевтическая деятельность':[
  'https://ns1.roszdravnadzor.gov.ru/opendata/7710537160-ls_licenses/data-20260906-structure-20210307.zip',
  'https://79reg.roszdravnadzor.gov.ru/opendata/7710537160-ls_licenses/data-20260830-structure-20210307.zip'],
 'Росздравнадзор: техническое обслуживание медицинских изделий':[
  'https://79reg.roszdravnadzor.gov.ru/opendata/7710537160-md_licenses/data-20260830-structure-20210307.zip',
  'https://roszdravnadzor.gov.ru/opendata/7710537160-md_licenses/data-20260816-structure-20210307.zip'],
 'Росздравнадзор: оборот наркотических/психотропных веществ':[
  'https://79reg.roszdravnadzor.gov.ru/opendata/7710537160-nark_licenses/data-20260830-structure-20210307.zip',
  'https://roszdravnadzor.gov.ru/opendata/7710537160-nark_licenses/data-20260809-structure-20210307.zip'],
}
source_success=0
for typ,urls in rz_sources.items():
    ok=False
    for u in urls:
        if download_and_scan_zip(u,typ): ok=True; source_success+=1; break
    if not ok: print('FAILED',typ,flush=True)

# Rostранснадзор: discover current CSV download from official open-data page.
try:
    page='https://rostransnadzor.gov.ru/opendata'; r=S.get(page,timeout=40); soup=BeautifulSoup(r.text,'html.parser')
    candidates=[]
    for a in soup.find_all('a',href=True):
        text=' '.join(a.stripped_strings).lower(); href=a['href']
        parent=' '.join(a.parent.parent.stripped_strings).lower() if a.parent and a.parent.parent else text
        if ('реестр лиценз' in parent or 'реестр лиценз' in text) and ('скач' in text or '.csv' in href.lower()): candidates.append(requests.compat.urljoin(page,href))
    # Also collect CSV links near text occurrence from raw html.
    for m in re.findall(r'href=["\']([^"\']+\.csv[^"\']*)["\']',r.text,re.I):
        u=requests.compat.urljoin(page,m)
        if u not in candidates: candidates.append(u)
    matched=False
    for u in candidates[:30]:
        try:
            rr=S.get(u,timeout=90); ct=rr.headers.get('content-type','').lower()
            if rr.status_code==200 and len(rr.content)>10000:
                n=match_bytes(rr.content,'Ространснадзор: реестр лицензий',u); diag.append({'type':'Ространснадзор: реестр лицензий','url':u,'status':200,'size':len(rr.content),'matched':n}); source_success+=1; matched=True; break
        except Exception: pass
    if not matched: diag.append({'type':'Ространснадзор: реестр лицензий','page_status':r.status_code,'candidates':candidates[:20],'error':'download_not_resolved'})
except Exception as e: diag.append({'type':'Ространснадзор: реестр лицензий','error':repr(e)})

for inn in inns:
    a=agg[inn]
    if a['types']:
        res[inn].update({'Лицензия найдена':'YES','Лицензии количество':a['count'],'Лицензии типы':' | '.join(sorted(a['types'])),'Лицензии источники':' | '.join(sorted(a['sources']))})
# The source set is deliberately partial: no universal NO conclusion for companies without a hit.
for inn in inns:
    if res[inn]['Лицензия найдена']=='NO': res[inn]['Лицензии статус проверки']='CHECKED_SELECTED_FEDERAL_REGISTRIES_NO_HIT'
fields=list(next(iter(res.values())).keys())
with (OUT/'licenses_1000.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=fields,delimiter=';'); w.writeheader(); w.writerows(res[i] for i in inns)
summary={'rows':1000,'license_hits':sum(1 for i in inns if res[i]['Лицензия найдена']=='YES'),'source_groups_succeeded':source_success,'diagnostics':diag}
(OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(summary,ensure_ascii=False,indent=2)[:30000])
