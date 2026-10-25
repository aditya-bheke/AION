import json, subprocess, re, sys
pdf=sys.argv[1]
L=json.load(open('lists.json'))
n=int(re.search(r'Pages:\s+(\d+)', subprocess.check_output(['pdfinfo',pdf]).decode()).group(1))
txt={p: re.sub(r'\s+',' ', subprocess.check_output(['pdftotext','-f',str(p),'-l',str(p),pdf,'-']).decode()) for p in range(1,n+1)}
start_body=next(p for p in txt if txt[p].strip().startswith('CHAPTER 1 '))
start_fm=next(p for p in txt if txt[p].strip().startswith('ACKNOWLEDGEMENT'))
def roman(i):
    vals=[(10,'x'),(9,'ix'),(5,'v'),(4,'iv'),(1,'i')]; out=''
    for v,r in vals:
        while i>=v: out+=r; i-=v
    return out
pages={}
def find(s):
    for p in range(start_body, n+1):
        if s in txt[p]: return p-start_body+1
    raise SystemExit('not found: '+s)
for r in L['tocRows']: pages[r['key']]=find(r['find'])
for f in L['figList']: pages[f['key']]=find(f"Figure {f['no']}: ")
for t in L['tabList']: pages[t['key']]=find(f"Table {t['no']}: ")
for key,head in [('fm_abbr','LIST OF ABBREVIATIONS ABBREVIATION'),('fm_figs','LIST OF FIGURES'),('fm_tabs','LIST OF TABLES'),('fm_nom','NOMENCLATURE SYMBOL')]:
    p=next(p for p in range(start_fm,start_body) if txt[p].strip().startswith(head))
    pages[key]=roman(p-start_fm+1)
json.dump(pages, open('pages.json','w'), indent=0)
print('body starts pdf page', start_body, '; entries', len(pages)); print({k:pages[k] for k in list(pages)[:12]})
