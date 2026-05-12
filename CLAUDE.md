# GWU AI Study Group — CLAUDE.md

## Project Overview

Materials for a 6-session study group on AI tools for academic economists, run by Elira Kuka and Tanner Regan at George Washington University. The audience is academic economists ranging from beginners to advanced coders.

Two types of content:
1. **LaTeX Beamer slides** for each session (`slides/`)
2. **Code examples** demonstrating data cleaning and analysis tasks (`code/`)

---

## Course Structure

| Session | Topic | Status |
|---------|-------|--------|
| 1 | AI for Coding — Tools, Concepts, and Setup | Complete |
| 2 | AI for Coding — Practical Workflows and Demos | Complete |
| 3 | Finding and Collecting Data | In development |
| 4 | Teaching: Slides, Exams, and Student Feedback | In development |
| 5 | Productivity and Workflow Automation | In development |
| 6 | Literature Review, Research Ideation, Academic Writing | In development |

---

## Slides (LaTeX Beamer)

### File Conventions
- All slides: `\documentclass[aspectratio=169, 12pt]{beamer}` and `\input{_preamble.tex}`
- Files named `Lecture_N.tex`, located in `slides/`
- Author line: `\author[AI for Economists]{Elira Kuka \& Tanner Regan}`
- Institution: `\date[\today]{The George Washington University}`

### Formatting Conventions
- Section headers: `\section{\textcolor{violet}{Section Title \vspace{0.3in}}}`
- Demo slides: `\item \textcolor{gray}{\textit{$\triangleright$ Demo slide --- [presenter name]}}`
- Placeholders: `\item \textcolor{gray}{\textit{$\triangleright$ Placeholder: description}}`
- Do not modify `_preamble.tex` unless explicitly asked

### Available Packages (from `_preamble.tex`)
`graphicx`, `hyperref`, `booktabs`, `enumerate`, `textpos`, `amsfonts`, `colortbl`, `tcolorbox`, lato font, `xcolor` (dvipsnames), `pgfplots` (compat=1.16), `comment`, `tikz`

### Build Artifacts — Do Not Commit
`.aux`, `.log`, `.nav`, `.snm`, `.toc`, `.fls`, `.fdb_latexmk`, `.synctex.gz`, `.out`

---

## Code Examples

Code examples are teaching materials — prioritize clarity and comments over conciseness. Each example should be self-contained and runnable. When writing the same task in multiple languages, produce identical output so they can be compared side by side.

### Python
- `pandas` for data manipulation (merging, reshaping, collapsing)
- `statsmodels` or `linearmodels` for econometrics (OLS, panel data, IV)
- `matplotlib` / `seaborn` for figures
- `requests` / `BeautifulSoup` for web scraping (Session 3 material)
- Manage environments with Anaconda; include `environment.yml` when a script has dependencies
- Prefer `.py` scripts for production pipelines; `.ipynb` for exploratory demos only
- Always run code and verify output before reporting the task complete

### Stata
- Target Stata 17 syntax
- Use `i.varname` for factor variables and fixed effects
- Use `esttab` or `outreg2` for LaTeX table export
- Comment every merge; print observation counts before and after each merge
- Do-files go in `code/lecture_N/stata_*/`

### R
- `tidyverse` style (`dplyr`, `tidyr`, `ggplot2`)
- `fixest` for fixed effects and IV regressions
- `modelsummary` for regression tables
- Scripts go in `code/lecture_N/r_*/`

### Folder Convention
Code is organized by lecture: `code/lecture_N/<language>_demo/`. Each subfolder contains scripts, versioned drafts (`_v0`, `_v1`), prompt logs (`.md`), and any output files.


---

## Project Folder Structure

```
GWU_AI_study_group/
├── slides/          # LaTeX Beamer source
│   ├── _preamble.tex
│   ├── Lecture_1.tex
│   └── Lecture_2.tex
├── code/            # Code examples, organized by lecture
│   ├── lecture_2/
│   │   ├── python_demo/     # GIS download, satellite embeddings, event study
│   │   └── stata_vscode_demo/  # Rwanda expenditure shares (NSIR-EICV7)
├── README.md
└── CLAUDE.md
```

---

