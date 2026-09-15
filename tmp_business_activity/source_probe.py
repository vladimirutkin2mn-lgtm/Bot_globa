import json, re, requests
from bs4 import BeautifulSoup

UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/140 Safari/537.36'
s=requests.Session(); s.headers.update({'User-Agent':UA,'Accept':'*/*'})

out={}

# GISP probe
for base in ['https://gisp.gov.ru/pp719v2/pub/prod/','https://portfolio.gisp.gov.ru/pp719v2/pub/prod/']:
    rec={'status':None,'links':[],'text_hits':[]}
    try:
        r=s.get(base,timeout=40,allow_redirects=True)
        rec['status']=r.status_code
        soup=BeautifulSoup(r.text,'html.parser')
        for a in soup.find_all('a',href=True):
            href=a.get('href','')
            txt=' '.join(a.stripped_strings)
            if 'xls' in href.lower() or 'скач' in txt.lower() or 'выгруз' in txt.lower():
                rec['links'].append({'text':txt[:200],'href':href})
        for m in re.findall(r'[^\"\'\s<>]{0,100}(?:xlsx|xls|excel|export|download)[^\"\'\s<>]{0,100}',r.text,re.I):
            rec['text_hits'].append(m[:300])
        rec['len']=len(r.text)
    except Exception as e:
        rec['error']=repr(e)
    out.setdefault('gisp',{})[base]=rec

# Chestny Znak probe
for inn in ['5445265650','6950086938','7701276779']:
    rec=[]
    for base in ['https://xn--80ajghhoc2aj1c8b.xn--p1ai/business/spisokuot/','https://chzweb01.crpt.ru/business/spisokuot/']:
        one={'url':base}
        try:
            r=s.get(base,params={'typeFilter':'INN','UF_INN':inn},timeout=40)
            one['status']=r.status_code; one['final_url']=r.url; one['contains_inn']=inn in r.text; one['len']=len(r.text)
            soup=BeautifulSoup(r.text,'html.parser')
            rows=[]
            for tr in soup.find_all('tr'):
                cells=[' '.join(td.stripped_strings) for td in tr.find_all(['td','th'])]
                if cells and any(inn in c for c in cells): rows.append(cells)
            one['rows']=rows[:10]
        except Exception as e: one['error']=repr(e)
        rec.append(one)
    out.setdefault('chz',{})[inn]=rec

# FSA probe
fsa=s
headers={'User-Agent':UA,'Accept':'application/json, text/plain, */*','Content-Type':'application/json','Authorization':'Bearer null','Referer':'https://pub.fsa.gov.ru/rds/declaration'}
try:
    lr=fsa.post('https://pub.fsa.gov.ru/login',json={'username':'','password':''},headers=headers,timeout=30,verify=False)
    out['fsa_login']={'status':lr.status_code,'headers':{k:v for k,v in lr.headers.items() if k.lower() in ['authorization','set-cookie','content-type']},'body':lr.text[:1000]}
    auth=lr.headers.get('Authorization') or lr.headers.get('authorization') or 'Bearer null'
except Exception as e:
    out['fsa_login']={'error':repr(e)}; auth='Bearer null'

fsa_headers=headers.copy(); fsa_headers['Authorization']=auth
for endpoint in ['https://pub.fsa.gov.ru/api/v1/rds/common/declarations/get','https://pub.fsa.gov.ru/api/v1/rss/common/certificates/get']:
    probes=[]
    for col in ['applicantName','manufacterName','applicantInn','applicantINN','manufacturerInn','manufacterInn','productFullName']:
        body={'size':5,'page':0,'filter':{'columnsSearch':[{'column':col,'search':'5445265650'}]},'columnsSort':[{'column':'date' if '/rss/' in endpoint else 'declDate','sort':'DESC'}]}
        try:
            rr=fsa.post(endpoint,json=body,headers=fsa_headers,timeout=40,verify=False)
            pr={'column':col,'status':rr.status_code,'text':rr.text[:1000]}
            try:
                jj=rr.json(); pr['total']=jj.get('total'); pr['items_sample']=(jj.get('items') or [])[:1]
            except Exception: pass
        except Exception as e: pr={'column':col,'error':repr(e)}
        probes.append(pr)
    out.setdefault('fsa',{})[endpoint]=probes

open('source_probe.json','w',encoding='utf-8').write(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps(out,ensure_ascii=False,indent=2)[:30000])
