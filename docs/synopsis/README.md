# AION Project Synopsis

| File | |
|---|---|
| [AION_Synopsis.docx](AION_Synopsis.docx) | Synopsis / project proposal (college format, Word) |
| [AION_Synopsis.pdf](AION_Synopsis.pdf) | PDF export of the same document |
| [images/process_diagram.png](images/process_diagram.png) | Process diagram (section 2a) |
| [images/system_architecture.png](images/system_architecture.png) | System architecture (section 2b) |

The document follows the NextHire AI synopsis layout (same sections, order and look),
built with real Word heading styles, list numbering and keep-together rules so it
does not break when edited.

## Regenerating

Small text edits can be made directly in the `.docx`. To regenerate everything from source:

```bash
cd docs/synopsis/source
npm install
npx playwright install chromium   # or set CHROMIUM_PATH to an existing Chromium
npm run all                       # diagrams -> images/, document -> AION_Synopsis.docx
```

Content lives in `source/build_synopsis.js`; diagrams in `source/diagrams/`.
