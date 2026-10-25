# AION Preliminary Project Report (BE Project Work-I)

| File | |
|---|---|
| [AION_Report.docx](AION_Report.docx) | Report in Word (ADYPSOE / SPPU 2019-course Project Work-I format) |
| [AION_Report.pdf](AION_Report.pdf) | PDF render of the same file |

50 pages in total. The chapters and appendices take 37 pages (the format allows 30 to 40). The rest is the cover, the certificate, 8 front-matter pages (i–viii) and 3 pages of references.

Before submission:
- Fill in the Exam No. of each student on the cover and certificate (left blank).
- Attach the plagiarism check report after Appendix C.

Format points followed: Times New Roman 12 pt, 1.5 line spacing, justified text, a 0.5" first-line indent, Letter page with margins of 1" top, 1.5" left, 1.25" bottom and 1" right, a page border, and the footer "ADYPSOE, Department of Computer Engineering 2026-27" (10 pt, centred) with the page number below it. Front matter is numbered in small Roman numerals and the chapters from 1. Chapter and section headings are numbered, figure captions sit below the figure, and references are numbered in order of first citation.

## Rebuilding (`source/`)
```
cd source
ln -s <node_modules containing docx> node_modules        # docx (npm) 9.x
mkdir -p src/media/word/media && cp src/logo.png src/media/word/media/image1.png
python3 gen_refs.py                                      # needs pandoc
node build.js pass1.docx && soffice --headless --convert-to pdf pass1.docx
python3 pages.py pass1.pdf                               # writes pages.json
node build.js AION_Report.docx pages.json                # final, with page numbers
```
Diagrams: `diag/*.tex` (TikZ, built with `diag/build.sh`) → `diag/*.png`.
