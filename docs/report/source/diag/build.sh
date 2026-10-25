#!/bin/bash
cd /tmp/claude-0/report/diag
for f in "$@"; do
  pdflatex -interaction=nonstopmode -halt-on-error $f.tex > $f.log 2>&1 || { echo "FAIL $f"; grep -A3 "^!" $f.log | head -8; continue; }
  pdftoppm -png -r 300 -singlefile $f.pdf $f
  python3 -c "from PIL import Image; im=Image.open('$f.png'); print('$f', im.size, round(im.size[0]/300,2),'x',round(im.size[1]/300,2),'in')"
done
