"""Parse quarterly AUM-by-strategy blocks from CNS 8-K Ex.99 earnings releases -> cns_strategy.json"""
import re,html,json,requests,pathlib
H={"User-Agent":"Eric Hines ehines@example.com"}
RAW=pathlib.Path(__file__).parents[1]/"raw"/"cns_raw.json"
ENDS=["2021-12-31","2022-03-31","2022-06-30","2022-09-30","2022-12-31","2023-03-31","2023-06-30","2023-09-30","2023-12-31","2024-03-31","2024-06-30","2024-09-30","2024-12-31","2025-03-31","2025-06-30","2025-09-30","2025-12-31","2026-03-31","2026-06-30","2026-09-30"]
NAMES=["U.S. Real Estate","Global/International Real Estate","Real Estate","Preferred Securities","Global Listed Infrastructure","Multi-Strategy Real Assets","Natural Resource Equities","Other"]
num=r'\(?\$? ?([\d,]+|—|–)\)?'
def first(seg,lab):
    m=re.search(re.escape(lab)+r' (?:\$ ?)?(\(?[\d,]+\)?|—|–)',seg)
    if not m: return None
    s=m.group(1)
    if s in '—–': return 0.0
    neg=s.startswith('(') or s.endswith(')'); x=float(s.strip('()').replace(',',''))
    return -x if neg else x
    return -float(s.strip('()').replace(',','')) if s.startswith('(') else float(s.replace(',',''))
out={}
for r,end in zip(json.loads(RAW.read_text()),ENDS):
    t=re.sub(r'\s+',' ',html.unescape(re.sub('<[^>]+>',' ',requests.get(r['url'],headers=H).text))).replace('$ (','($ ').replace('( ','(')
    i=t.find('By Investment Strategy (in millions) Three Months Ended'); i=t.find('Assets under management, beginning',i); e=min([x for x in (t.find('Six Months Ended',i),t.find('Nine Months Ended',i),t.find('Year Ended',i)) if x>0]+[i+30000]); blk=t[i-200:e]
    # cut to first "Total" block end
    s={}
    def fnd(n):
        m=re.search(r'(?<!U\.S\. )(?<!International )(?<!/)'+re.escape(n)+' Assets under management, beginning',blk)
        return m.start() if m else -1
    pos=[(n,fnd(n)) for n in NAMES]
    pos=sorted([(p,n) for n,p in pos if p>=0])
    for k,(p,n) in enumerate(pos):
        seg=blk[p:pos[k+1][0] if k+1<len(pos) else p+1500]
        s[n]={"beg":first(seg,'beginning of period'),"net":first(seg,'Net inflows (outflows)'),"mkt":first(seg,'Market appreciation (depreciation)'),"dist":first(seg,'Distributions'),"end":first(seg,'end of period'),"avg":first(seg,'Average assets under management')}
    out[end]={"src":r['url'],"strat":s}
    tot=sum(v['end'] or 0 for v in s.values()); print(end,list(s),round(tot))
pathlib.Path(__file__).with_name("cns_strategy.json").write_text(json.dumps(out,indent=1))
