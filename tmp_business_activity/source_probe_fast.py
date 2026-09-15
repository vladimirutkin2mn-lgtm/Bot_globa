import json, re, requests, urllib3
from bs4 import BeautifulSoup
urllib3.disable_warnings()
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/140 Safari/537.36'
s=requests.Session(); s.headers.update({'User-Agent':UA,'Accept':'*/*'})
out={}
# GISP
for base in ['https://portfolio.gisp.gov.ru/pp719v2/pub/prod/','https://gisp.gov.ru/pp719v2/pub/prod/']:
  try:
    r=s.get(base,timeout=10); soup=BeautifulSoup(r.text,'html.parser')
    out.setdefault('gisp',{})[base]={'status':r.status_code,'len':len(r.text),'links':[{'text':' '.join(a.stripped_strings),'href':a.get('href')} for a in soup.find_all('a',href=True) if ('xls' in a.get('href','').lower() or 'скач' in ' '.join(a.stripped_strings).lower() or 'выгруз' in ' '.join(a.stripped_strings).lower())][:30],'hits':re.findall(r'[^\"\'\s<>]{0,80}(?:xlsx|excel|export|download)[^\"\'\s<>]{0,80}',r.text,re.I)[:30]}
  except Exception as e: out.setdefault('gisp',{})[base]={'error':repr(e)}
# CHZ
inn='5445265650'
for base in ['https://xn--80ajghhoc2aj1c8b.xn--p1ai/business/spisokuot/','https://chzweb01.crpt.ru/business/spisokuot/']:
  try:
    r=s.get(base,params={'typeFilter':'INN','UF_INN':inn},timeout=10); soup=BeautifulSoup(r.text,'html.parser')
    rows=[]
    for tr in soup.find_all('tr'):
      cells=[' '.join(x.stripped_strings) for x in tr.find_all(['td','th'])]
      if cells and any(inn in c for c in cells): rows.append(cells)
    out.setdefault('chz',{})[base]={'status':r.status_code,'url':r.url,'len':len(r.text),'contains':inn in r.text,'rows':rows[:10]}
  except Exception as e: out.setdefault('chz',{})[base]={'error':repr(e)}
# FSA
h={'User-Agent':UA,'Accept':'application/json, text/plain, */*','Content-Type':'application/json','Authorization':'Bearer null','Referer':'https://pub.fsa.gov.ru/rds/declaration'}
try:
  lr=s.post('https://pub.fsa.gov.ru/login',json={'username':'','password':''},headers=h,timeout=10,verify=False)
  auth=lr.headers.get('Authorization','Bearer null'); out['fsa_login']={'status':lr.status_code,'auth':auth[:80],'body':lr.text[:300]}
except Exception as e: auth='Bearer null'; out['fsa_login']={'error':repr(e)}
h['Authorization']=auth
for ep,sort in [('https://pub.fsa.gov.ru/api/v1/rds/common/declarations/get','declDate'),('https://pub.fsa.gov.ru/api/v1/rss/common/certificates/get','date')]:
  arr=[]
  for col,search in [('applicantName','МУЛЬТИ-ПАК'),('manufacterName','МУЛЬТИ-ПАК'),('applicantInn',inn),('applicantINN',inn)]:
    body={'size':3,'page':0,'filter':{'columnsSearch':[{'column':col,'search':search}]},'columnsSort':[{'column':sort,'sort':'DESC'}]}
    try:
      rr=s.post(ep,json=body,headers=h,timeout=10,verify=False); x={'col':col,'status':rr.status_code,'text':rr.text[:300]}
      try: j=rr.json(); x['total']=j.get('total'); x['items']=(j.get('items') or [])[:1]
      except: pass
    except Exception as e: x={'col':col,'error':repr(e)}
    arr.append(x)
  out.setdefault('fsa',{})[ep]=arr
open('source_probe_fast.json','w',encoding='utf-8').write(json.dumps(out,ensure_ascii=False,indent=2)); print(json.dumps(out,ensure_ascii=False,indent=2))
