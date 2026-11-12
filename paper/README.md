# EvoPolicy-SDD no modelo SBC (base: Traduz Saúde)

- `projeto_evopolicy_sdd.tex` — mesmo preâmbulo do Traduz Saúde (sbc-template, BibTeX + sbc.bst)
- `references.bib` — 46 referências; DOI/URL/arXiv no campo `note` (o sbc.bst não imprime doi/url)
- `figs/` — 4 gráficos gerados de `results/` do protótipo v0.1.1 (`gerar_figuras.py`)
- `sbc-template.sty` / `sbc.bst` — versão pública do modelo SBC; no .sty, `caption2` foi trocado por `caption`
  para funcionar com `subcaption`/`capt-of`. Se você tiver o .sty do Traduz Saúde, pode substituir por ele.

Compilar: `latexmk -pdf projeto_evopolicy_sdd.tex` (pdflatex + bibtex).
