import os, json, requests
def load_dotenv(p,override=True):
    import re
    for l in open(p,encoding="utf-8"):
        m=re.match(r"\s*([A-Za-z_]\w*)\s*=\s*(.*)",l)
        if m: os.environ[m.group(1)]=m.group(2).strip().strip("\"'")
load_dotenv(os.path.expanduser('~/mnt/2026/.env'), override=True)
B="https://api.unimelb-dash.com"
r=requests.post(f"{B}/accounts/login",json={"email":os.environ["DASH_EMAIL"],"password":os.environ["DASH_PASSWORD"]},timeout=60)
r.raise_for_status(); tok=r.json()["result"]["user"]["token"]
h={"Authorization":f"Token {tok}","Accept":"application/json"}
url=f"{B}/assessment/caf/v3/get?page_size=100&page=1&cohort=DDS1&year=2026&ordering=datetime,-cohort"
recs=[]
with requests.Session() as s:
    while url:
        p=s.get(url,headers=h,timeout=120); p.raise_for_status(); p=p.json()
        recs+=p["results"]; url=p.get("next")
json.dump(recs,open(os.path.expanduser('~/work/dds1_caf.json'),'w'),ensure_ascii=False)
print(len(recs))
