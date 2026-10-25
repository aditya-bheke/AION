# AION Preliminary Project Report (work in progress)

DRAFT: page numbers in the contents and figure/table lists are still placeholders ("00").

Remaining steps:
1. Trim so the chapters and appendices fit in about 36 pages. Currently 41; the short last pages are Chapter 4 (p.28), Chapter 6 (p.43), Chapter 7 (p.45) and Appendix A (p.48).
2. Second pass: read the page numbers from the rendered PDF, write them to pages.json, then rebuild with `node build.js out.docx pages.json`.
3. Fill in the Exam Nos (left blank on purpose).

Build: `python3 gen_refs.py && node build.js AION_Report.docx` (needs the docx npm package; build.js expects `diag/` and `src/media/word/media/image1.png`, i.e. the logo).
