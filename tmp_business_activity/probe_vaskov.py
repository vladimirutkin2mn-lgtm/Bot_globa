import requests,re,json
from bs4 import BeautifulSoup
s=requests.Session();s.headers['User-Agent']='Mozilla/5.0'
out={}
for url in ['https://vaskov.pro/719?inn=5445265650','https://vaskov.pro/sertifikaty?inn=6950086938']:
 try:
  r=s.get(url,timeout=20); soup=BeautifulSoup(r.text,'html.parser')
  rec={'status':r.status_code,'len':len(r.text),'title':soup.title.get_text(' ',strip=True) if soup.title else '', 'contains_inn':url.split('=')[-1] in r.text}
  rec['scripts']=[x.get('src') for x in soup.find_all('script',src=True)]
  rec['api_strings']=list(dict.fromkeys(re.findall(r'[/A-Za-z0-9_.?=&:-]{0,80}(?:api|fetch|ajax)[/A-Za-z0-9_.?=&:-]{0,120}',r.text,re.I)))[:50]
  rec['text']=' '.join(soup.stripped_strings)[:4000]
  out[url]=rec
 except Exception as e: out[url]={'error':repr(e)}
print(json.dumps(out,ensure_ascii=False,indent=2));open('probe_vaskov.json','w').write(json.dumps(out,ensure_ascii=False,indent=2))
