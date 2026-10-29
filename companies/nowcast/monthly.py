"""Scrape CNS monthly preliminary AUM press releases (PR Newswire) -> cns_monthly.json"""
import re,html,json,requests,calendar,pathlib
H={"User-Agent":"Mozilla/5.0"}
M={m.lower():i for i,m in enumerate(calendar.month_name) if m}
OUT=pathlib.Path(__file__).with_name("cns_monthly.json")
def parse(t):
    t=re.sub(r'\s+',' ',html.unescape(re.sub('<[^>]+>',' ',t)))
    def row(lbl):
        m=re.search(re.escape(lbl)+r'((?: \(?\$? ?[\d,]+\)?| –| -| —){5})',t)
        if not m: return None
        v=[]
        for n in m.group(1).split():
            if n in '–-—': v.append(0.0);continue
            x=float(n.strip('()$').replace(',',''));v.append(-x if n.startswith('(') else x)
        return dict(zip(['beg','net','mkt','dist','end'],v))
    r={k:row(l) for k,l in [('adv','Advisory'),('sub','Subadvisory'),('inst','Total Institutional Accounts'),('oe','Open-end Funds'),('wealth','Total Wealth'),('cef','Closed-end Funds'),('tot','Total AUM')]}
    return {k:v for k,v in r.items() if v}
def main():
    out=json.loads(OUT.read_text()) if OUT.exists() else {}
    links=set()
    for p in range(1,7):
        t=requests.get(f"https://www.prnewswire.com/news/cohen-%26-steers%2C-inc./?page={p}&pagesize=100",headers=H,timeout=30).text
        links|=set(re.findall(r'href="(/news-releases/[^"]*assets-under-management[^"]*)"',t))
    for l in sorted(links):
        m=re.search(r'for-([a-z]+)-(\d{4})-',l)
        if not m: continue
        k=f"{m.group(2)}-{M[m.group(1)]:02d}"
        if k in out: continue
        u="https://www.prnewswire.com"+l; p=parse(requests.get(u,headers=H,timeout=30).text)
        if 'tot' in p: out[k]={"url":u,**p}
    OUT.write_text(json.dumps(dict(sorted(out.items())),indent=1)); return out
if __name__=="__main__":
    o=main(); print(len(o),list(o)[:2],list(o)[-1])
