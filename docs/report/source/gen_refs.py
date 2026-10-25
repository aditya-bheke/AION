import json, re, subprocess, html
blocks = json.loads(subprocess.check_output(['node', '-e', "console.log(JSON.stringify([...require('./content1'),...require('./content2'),...require('./content3'),...require('./content4')]))"]))
order = []
def scan(s):
    for m in re.finditer(r'\[@([^\]]+)\]', s):
        for k in re.split(r';\s*@?', m.group(1)):
            if k not in order: order.append(k)
for b in blocks:
    if b['t'] == 'paper':
        if b['key'] not in order: order.append(b['key'])
    scan(json.dumps(b, ensure_ascii=False))
md = '\n\n'.join(f'[@{k}]' for k in order)
out = subprocess.run(['pandoc', '-f', 'markdown', '-t', 'html', '--citeproc', '--bibliography=references.bib', '--csl=ieee.csl'],
                     input=md, capture_output=True, text=True, check=True).stdout
refs = {}
for m in re.finditer(r'<div id="ref-([^"]+)"[^>]*>\s*<div class="csl-left-margin">\[(\d+)\]\s*</div><div\s+class="csl-right-inline">(.*?)</div>\s*</div>', out, re.S):
    key, n, body = m.group(1), int(m.group(2)), m.group(3)
    body = re.sub(r'<a [^>]*>(.*?)</a>', r'\1', body, flags=re.S)
    runs = []
    for part in re.split(r'(<em>.*?</em>)', body, flags=re.S):
        if not part: continue
        it = part.startswith('<em>')
        txt = html.unescape(re.sub(r'<[^>]+>', '', part)).replace('\n', ' ')
        txt = re.sub(r'\s+', ' ', txt)
        if txt: runs.append({'text': txt, 'italics': it})
    refs[key] = {'n': n, 'runs': runs}
assert len(refs) == len(order), (len(refs), len(order), set(order) - set(refs))
for k in order: assert refs[k]['n'] == order.index(k) + 1, k
json.dump(refs, open('refs.json', 'w'), ensure_ascii=False, indent=1)
print(len(order), 'refs in order;', order[:5])
for k in order[:3] + order[-2:]: print(refs[k]['n'], ''.join(r['text'] for r in refs[k]['runs'])[:150])
