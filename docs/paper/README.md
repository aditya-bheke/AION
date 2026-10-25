# AION Research Paper (IEEE conference format)

| File | |
|---|---|
| [aion_paper.pdf](aion_paper.pdf) | Compiled paper (11 pages, IEEEtran conference template) |
| [AION_paper.docx](AION_paper.docx) | Word version (editable; same content, IEEE two-column layout; figures and algorithms as images) |
| [aion_paper.tex](aion_paper.tex) | LaTeX source (figures drawn in TikZ, no image files needed) |
| [references.bib](references.bib) | 33 references (BibTeX, IEEEtran style) |
| [AION_paper_overleaf.zip](AION_paper_overleaf.zip) | Source bundle: upload to Overleaf as a new project |

Build locally: `pdflatex aion_paper && bibtex aion_paper && pdflatex aion_paper && pdflatex aion_paper`.

All results in the paper come from `evaluation/results/` and `docs/EVALUATION.md`.
