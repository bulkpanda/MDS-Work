# `assessor_analysis.py`

> Loads BOH1 assessor-submitted form data from Postgres, scores every checklist item via a fixed option→score map, and quantifies each assessor's harshness and internal consistency using z-scores, one-way ANOVA and ICC(1,1).

| | |
|---|---|
| **Lines of code** | 414 |
| **Top-level functions** | 12 |
| **Classes** | 0 |
| **Module constants** | 4 (`SCORE_MAP`, `MIN_ASSESSMENTS`, `UNI_COLOR`, `FETCH_SQL`) |
| **Imports from this codebase** | `Utils` (`readDf`) |
| **Imported by** | No other module in `src/` imports it. `main.ipynb` imports it twice — `from assessor_analysis import run_assessor_analysis` and `from assessor_analysis import load_data, add_scores` |
| **Run how** | Imported by `main.ipynb` (`from assessor_analysis import run_assessor_analysis`; then `run_assessor_analysis(engine)`). Also has an `if __name__ == "__main__":` block (lines 411–414) so `python assessor_analysis.py` runs standalone — but that block hard-codes a placeholder connection string and will fail as shipped. |

---

## 1. Purpose and role in the pipeline

This module is the **assessor-bias diagnostic** for the BOH1 cohort (Bachelor of Oral Health, year 1). Where the rest of the codebase turns assessment data into student-facing PDFs and cohort reports, this module turns the same data around and asks a quality-assurance question: *do different assessors mark the same kind of work differently?*

**What it consumes.** A single SQL query (`FETCH_SQL`, lines 40–58) against `public.rawform_forms` — the raw form table used for the BOH1 cohort (other cohorts in this codebase use `rawform_forms_v3`; BOH1 sits on the non-versioned table, matching `BOH1_TABLE = "rawform_forms"` in `boh1_utils.py`). The query pulls one row per submitted form, extracting two Likert scales out of the `assessor_data` JSONB column at the SQL level — `scale-global-rating` (**GR**, the assessor's holistic 1–5 judgement of the student) and `scale-practice-readiness` (a 1–4 judgement of readiness for practice) — and returns the whole `assessor_data` blob so the per-item checklist can be scored in Python.

**What it produces.** Nothing on disk. It returns two in-memory DataFrames — a form-level `df` (with added `scores` and `checklist_mean` columns) and an assessor-level `assessor_stats` — prints a text summary to stdout, and draws three matplotlib figures. It writes no files and touches no database tables.

**Who calls it.** `main.ipynb` in two separate cells. One cell runs the whole thing (`df, assessor_stats = run_assessor_analysis(engine)`); a later cell reuses only the loading/scoring half (`df = add_scores(load_data(engine))`) and hands the result to `assessor_confound.run_confound_analysis(df)`. That second usage makes `load_data` + `add_scores` a de-facto public data-preparation API for the companion `assessor_confound` module — the column names produced here (`checklist_mean`, `global_rating`, `practice_readiness`, `student_number`, `student_name`, `assessor_name`, `assessmentid`) are exactly the columns `assessor_confound` expects.

**Statistical model summary.** Three distinct models are fitted:

1. **Composite harshness z-score** (`build_assessor_stats`) — descriptive, not inferential. Each assessor's mean on three metrics is standardised across assessors (population SD, `ddof=0`), and `harshness_z` is the unweighted mean of those three z-scores. There is no fitted model object; it is arithmetic on group means.
2. **One-way ANOVA** (`anova_test`) — dependent variable = one of `checklist_mean` / `global_rating` / `practice_readiness` at the *form* level; single independent variable (factor) = `assessor_name`. Fitted with `scipy.stats.f_oneway(*groups)` where each group is one assessor's vector of scores. Reported as `{F, p}` rounded to 3 / 4 dp, with `**` printed when `p < 0.05`.
3. **ICC(1,1), one-way random effects** (`icc_oneway`) — hand-computed from a `student_number × assessor_name` pivot of the metric, using the classic `(MS_between − MS_within) / (MS_between + (k−1)·MS_within)` formula. No library call; there is no `pingouin`/`statsmodels` dependency. Reported with a hard-coded verbal band (poor / moderate / good / excellent).

---

## 2. External dependencies

| Library / resource | Used for |
|---|---|
| `numpy` (`np`) | `np.mean` for item and checklist means; `np.arange` / `np.argsort` / `np.array` / `np.linspace` for plot ordering; `np.polyfit` for the scatter trend line; `np.nan` sentinels |
| `pandas` (`pd`) | All DataFrame handling; `pd.to_datetime` on the `date` column; `pivot_table` for the ICC ratings matrix; `groupby`/`agg` |
| `matplotlib.pyplot` (`plt`) | All three figures; `plt.show()` in `run_assessor_analysis` |
| `matplotlib.gridspec` (`gridspec`) | **Imported at line 16 but never referenced anywhere in the file** — dead import |
| `scipy.stats` (`stats`) | `stats.f_oneway` — the only inferential library call in the module |
| `sqlalchemy.create_engine` | Only used inside the `__main__` block (line 413); the comment at line 18 says "only needed if running standalone" |
| `Utils.readDf` | Executes `FETCH_SQL` against the engine (`readDf(engine, sql, params=None)` → `pd.read_sql(text(sql), conn)`) |
| **Database** | Postgres table `public.rawform_forms`, columns `assessmentid`, `form_code`, `assessor_name`, `student_number`, `student_name`, `datetimeutc`, `type`, `clinic`, `cohort`, `submitted_by_assessor`, `assessor_data` (JSONB) |
| **Env vars / config files** | None. The SQLAlchemy `engine` is passed in by the caller — the module never builds its own connection except in the `__main__` placeholder |
| **Filesystem** | None. No file is read or written |

---

## 3. Module-level constants and variables

| Name | Type | Value / shape | Purpose |
|---|---|---|---|
| `SCORE_MAP` | `dict` (7 entries) | `{'O1': 1.0, 'O2': 0.8, 'O3': 0.6, 'O4': 0.4, 'O5': 0.0, 'Yes': 1.0, 'No': 0.0}` | Maps a raw checklist answer to a 0–1 numeric score. `O1`–`O5` are the five-point rubric options (O1 best); `Yes`/`No` are binary items. Default value of `calc_score`'s `score_map` parameter. Any answer string not in this dict is silently ignored |
| `MIN_ASSESSMENTS` | `int` | `2` | Minimum number of assessments an assessor must have before appearing in any output. Applied in three different places with three different meanings — see Gotchas |
| `UNI_COLOR` | `str` | `'#010d44'` | University of Melbourne navy. Default bar colour and title colour across all plots |
| `FETCH_SQL` | `str` | 569-char SQL, lines 40–58 | The single query the module runs |

`FETCH_SQL` in full shape:

```sql
SELECT
    assessmentid, form_code, assessor_name, student_number, student_name,
    datetimeutc::date AS date, type, clinic,
    NULLIF(assessor_data->'scale-global-rating'->>'scale',  '')::int AS global_rating,
    NULLIF(assessor_data->'scale-practice-readiness'->>'scale', '')::int AS practice_readiness,
    assessor_data
FROM public.rawform_forms
WHERE cohort = 'BOH1'
  AND submitted_by_assessor
  AND datetimeutc >= '2026-01-01'
ORDER BY assessmentid ASC, form_code ASC
```

Note the three hard-coded filters: cohort `'BOH1'`, only forms where `submitted_by_assessor` is true, and a hard-coded start date of `2026-01-01`.

---

## 4. Classes

None. This module defines no classes.

---

## 5. Function reference

Sections below follow the source's own `# ─── … ───` banner comments.

### 5.1 Data loading

#### `load_data(engine) -> pd.DataFrame`

*Lines 61–64.* Runs `FETCH_SQL` and normalises the `date` column to datetime.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `engine` | SQLAlchemy `Engine` | — | Live connection to the DASH Postgres database. Supplied by the caller; in `main.ipynb` it is the notebook-level `engine = create_engine(dbUrl, pool_pre_ping=True)` |

**Returns** — a `pd.DataFrame`, one row per assessor-submitted BOH1 form since 2026-01-01, with the columns listed in `FETCH_SQL` plus `date` cast to `datetime64`.

**Behaviour**

1. Calls `readDf(engine, FETCH_SQL)` — no parameters are bound; the query is fully literal.
2. Overwrites `df["date"]` with `pd.to_datetime(df["date"])` (the SQL already cast it to `::date`, so this converts the Python `date` objects to pandas timestamps).

**Side effects** — Opens a database connection (via `readDf`) and issues a SELECT. Read-only; no writes.

**Calls** — `Utils:readDf`, `pd.to_datetime`.
**Called by** — `assessor_analysis:run_assessor_analysis`, and directly from `main.ipynb`.

**Example** (from `main_notebook_code.py`, lines 1417–1421):

```python
from assessor_analysis import load_data, add_scores
from assessor_confound  import run_confound_analysis

df = add_scores(load_data(engine))
results = run_confound_analysis(df)
```

---

### 5.2 Scoring

#### `calc_score(assessor_data: dict, score_map: dict = SCORE_MAP) -> dict`

*Lines 69–112.* Converts one form's raw `assessor_data` JSON blob into per-item-code mean scores.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `assessor_data` | `dict` | — | One row's JSONB blob: `{item_code: {mc_key: answer_string, …}, …}`. Item codes are things like `"221"`, `"BOH-DD"`, `"022/024"` |
| `score_map` | `dict` | `SCORE_MAP` | Answer-string → 0–1 score lookup |

**Returns** — `dict` keyed by cleaned item code; each value is `{"score": float (mean, 4 dp), "n_items": int, "items": {mc_key: float, …}}`. Returns `{}` when `assessor_data` is not a dict (covers `None`/NULL rows).

**Behaviour**

1. Type-guards: non-dict input → `{}` (line 85–86).
2. Iterates `assessor_data.items()`. **Skips any key containing the substring `"scale"`** (line 90) — this is how the global-rating and practice-readiness scale blocks are excluded, since they are already pulled out in SQL. Also skips values that are not dicts.
3. Within an item, keeps only sub-answers whose value is a key of `score_map` — anything else (free text, unanswered, `"N/A"`) is dropped rather than scored zero.
4. Items with no scoreable sub-answers are dropped entirely (line 100–101).
5. **Compound code stripping** (line 105): `item_code.split("/")[0]`, so `"022/024"` is stored under `"022"`.
6. `score` is the unweighted mean of the surviving sub-answer scores, rounded to 4 dp.

**Called by** — invoked as `df["assessor_data"].apply(calc_score)` inside `add_scores`; no static caller edge is recorded in the facts because it is passed as a callable.

---

#### `add_scores(df: pd.DataFrame) -> pd.DataFrame`

*Lines 115–123.* Adds the `scores` (dict) and `checklist_mean` (float) columns.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `df` | `pd.DataFrame` | — | Output of `load_data` — must contain an `assessor_data` column |

**Returns** — a **copy** of `df` with two extra columns: `scores` (the `calc_score` dict) and `checklist_mean` (float or `NaN`).

**Behaviour**

1. `df = df.copy()` — the input is *not* mutated in place.
2. `scores` = `calc_score` applied row-wise.
3. `checklist_mean` = mean of the `"score"` values across *item codes*, 4 dp; `np.nan` when the `scores` dict is empty. This is an **unweighted mean over item codes** — an item code with 10 sub-answers counts exactly as much as one with a single sub-answer.

**Called by** — `assessor_analysis:run_assessor_analysis`, and directly from `main.ipynb`.

**Example** — see the `load_data` example above; `add_scores(load_data(engine))` is the exact call site.

---

### 5.3 Assessor-level aggregation

#### `build_assessor_stats(df: pd.DataFrame) -> pd.DataFrame`

*Lines 128–162.* Collapses form-level rows to one row per assessor and computes the composite harshness z-score.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `df` | `pd.DataFrame` | — | Form-level DataFrame with `checklist_mean` already added |

**Returns** — a DataFrame indexed by `assessor_name`, sorted ascending by `harshness_z`, with columns: `n_assessments`, `checklist_mean`, `checklist_std`, `global_rating_mean`, `global_rating_std`, `pr_mean`, `pr_std`, `checklist_mean_z`, `global_rating_mean_z`, `pr_mean_z`, `harshness_z`.

**Behaviour**

1. Groups by `assessor_name`; `n_assessments` = `count()` of `assessmentid`; means and SDs (`std()`, pandas default `ddof=1`) of the three metrics, all rounded to 4 dp.
2. Filters to `n_assessments >= MIN_ASSESSMENTS` (2) — line 149.
3. **The model**: for each of `checklist_mean`, `global_rating_mean`, `pr_mean`, computes a z-score *across assessors* using the **population** SD (`ddof=0`, line 153) and stores it as `<col>_z`, 3 dp.
4. `harshness_z` = unweighted row-mean of the three z-scores, 3 dp. **Lower (more negative) = harsher**, because no inversion is actually applied despite the comments — see Gotchas.
5. Sorts ascending, so the harshest assessor is the first row.

**Called by** — `assessor_analysis:run_assessor_analysis`.

---

### 5.4 Inter-rater statistics

#### `anova_test(df: pd.DataFrame, metric: str) -> dict`

*Lines 167–173.* One-way ANOVA of `metric` across assessors.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `df` | `pd.DataFrame` | — | Form-level DataFrame |
| `metric` | `str` | — | Column to test — used with `"checklist_mean"`, `"global_rating"`, `"practice_readiness"` |

**Returns** — `{"F": float, "p": float}`, rounded to 3 and 4 dp; `{"F": nan, "p": nan}` when fewer than 2 usable assessor groups exist.

**Model** — dependent variable: the chosen `metric` at form level. Independent variable: the single categorical factor `assessor_name`. Fitted by `scipy.stats.f_oneway(*groups)`, where `groups` is a list of 1-D arrays, one per assessor.

**Behaviour**

1. Builds the group list by iterating `df.groupby("assessor_name")`, dropping NaNs, and keeping only groups where `g[metric].count() >= MIN_ASSESSMENTS` (line 169).
2. Bails out with NaNs when fewer than 2 groups survive.
3. `stats.f_oneway` assumes independent observations, homogeneity of variance, and normality — none of which are checked here.

**Called by** — `assessor_analysis:print_summary`.

---

#### `icc_oneway(df: pd.DataFrame, metric: str) -> float`

*Lines 176–199.* Hand-rolled ICC(1,1) intraclass correlation, one-way random effects.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `df` | `pd.DataFrame` | — | Form-level DataFrame |
| `metric` | `str` | — | Column to compute agreement on |

**Returns** — `float` rounded to 4 dp, or `np.nan` when the ratings matrix has fewer than 2 rows or 2 columns, or when the input subset is empty.

**Model** — the unit of analysis is the *student* (`student_number`); the rater is `assessor_name`. Builds an `n × k` ratings matrix by `pivot_table(index="student_number", columns="assessor_name", values=metric, aggfunc="mean")`, then:

```
SS_between = k · Σ(row_mean − grand_mean)²
SS_within  = Σ(cell − row_mean)²
MS_between = SS_between / (n − 1)
MS_within  = SS_within  / (n · (k − 1))
ICC        = (MS_between − MS_within) / (MS_between + (k − 1) · MS_within)
```

No statistics library is used — this is pure numpy/pandas arithmetic. There is no significance test or confidence interval.

**Behaviour**

1. Subsets to `["assessor_name", "student_number", metric]` and drops rows with any NaN.
2. Pivots; drops rows that are all-NaN (`dropna(how="all")`) but **not** columns.
3. Returns NaN if `n < 2` or `k < 2`.
4. `grand_mean` uses `pivot.stack().mean()`, which skips missing cells; `SS_within` likewise skips missing cells via `.stack().sum()`, but the `MS_within` denominator `n·(k−1)` counts *all* cells including the missing ones — see Gotchas.

**Called by** — `assessor_analysis:print_summary`.

---

### 5.5 Plots

#### `_bar_with_error(ax, series_mean, series_std, title, ylabel, color=UNI_COLOR)`

*Lines 204–216.* Private helper: draws one sorted bar-with-error-bar panel.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `ax` | matplotlib `Axes` | — | Target axes |
| `series_mean` | `pd.Series` | — | Index = assessor names, values = means |
| `series_std` | `pd.Series` | — | Matching SDs, used as `yerr` |
| `title` | `str` | — | Panel title |
| `ylabel` | `str` | — | Y-axis label |
| `color` | `str` | `UNI_COLOR` | Bar colour |

**Returns** — `None` (mutates `ax`).

**Behaviour** — computes `order = np.argsort(series_mean.values)` and re-orders both bars and tick labels by that, so **the panel is always sorted by its own metric**, regardless of how the caller sorted the data. Bars use `alpha=0.75`, `capsize=4`, error-bar linewidth 1.2; x tick labels rotated 40° at fontsize 8; top and right spines hidden.

**Side effects** — mutates the passed `Axes`.

**Called by** — `assessor_analysis:plot_assessor_overview`.

---

#### `plot_assessor_overview(assessor_stats: pd.DataFrame, df: pd.DataFrame)`

*Lines 219–265.* Four-panel overview figure.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `assessor_stats` | `pd.DataFrame` | — | Output of `build_assessor_stats` |
| `df` | `pd.DataFrame` | — | **Accepted but never used in the body** |

**Returns** — the matplotlib `Figure`.

**Behaviour**

1. `plt.subplots(2, 2, figsize=(14, 9))`; suptitle "Assessor Harshness & Consistency – BOH1" in `UNI_COLOR` bold at `y=1.01`.
2. Panels 1–3 delegate to `_bar_with_error` for checklist mean (navy), global rating (`#4f5fb2`) and practice readiness (`#2e7d4f`), each with `std.fillna(0)` so single-assessment assessors get zero-length error bars.
3. Panel 4 is drawn inline: a horizontal diverging bar of `harshness_z`, coloured `#c0392b` (red) when `z < 0` and `#27ae60` (green) otherwise, with a black vertical line at 0. The title states "red = harsher, green = more lenient".
4. `plt.tight_layout()` then returns the figure — it does not call `plt.show()`.

**Side effects** — creates a matplotlib figure (never closed).

**Calls** — `assessor_analysis:_bar_with_error`.
**Called by** — `assessor_analysis:run_assessor_analysis`.

---

#### `plot_score_distributions(df: pd.DataFrame)`

*Lines 268–303.* Box plot of `checklist_mean` per assessor.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `df` | `pd.DataFrame` | — | Form-level DataFrame with `checklist_mean` |

**Returns** — the matplotlib `Figure`.

**Behaviour**

1. Selects assessors with `count() >= MIN_ASSESSMENTS` non-null `checklist_mean` values (lines 272–277, via a `.loc[lambda s: …]` filter).
2. Orders assessors by **median** `checklist_mean` ascending, so the left-most box is the harshest.
3. `ax.boxplot(..., patch_artist=True, vert=True)` with white median lines of width 2; boxes filled from `plt.cm.Blues` sampled over `np.linspace(0.3, 0.85, len(order))`.
4. Title notes the sort order; top/right spines hidden.

**Side effects** — creates a matplotlib figure. Note the docstring says "KDE / box-plot" but only a box plot is drawn.

**Called by** — `assessor_analysis:run_assessor_analysis`.

---

#### `plot_scatter_gr_vs_checklist(df: pd.DataFrame)`

*Lines 306–337.* Scatter of global rating against checklist mean, one colour per assessor, with a single pooled trend line.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `df` | `pd.DataFrame` | — | Form-level DataFrame |

**Returns** — the matplotlib `Figure`.

**Behaviour**

1. Drops rows missing either `global_rating` or `checklist_mean`.
2. Builds a colour palette from `plt.cm.tab20` over the number of unique assessors — **more than 20 assessors will reuse colours**.
3. Scatters each assessor's points (`alpha=0.7`, `s=50`), skipping assessors with fewer than `MIN_ASSESSMENTS` rows.
4. Fits a **degree-1 `np.polyfit`** on the *whole* `sub` set (x = `checklist_mean`, y = `global_rating`) — including the assessors excluded from the scatter — and draws it as a black dashed line labelled `"_trend"` (the leading underscore hides it from the legend).
5. Legend placed outside the axes at `bbox_to_anchor=(1.01, 1)`.

The purpose stated in the docstring is spotting assessors whose rubric scores do not match their holistic rating.

**Side effects** — creates a matplotlib figure.

**Called by** — `assessor_analysis:run_assessor_analysis`.

---

### 5.6 Summary table

#### `print_summary(assessor_stats: pd.DataFrame, df: pd.DataFrame)`

*Lines 342–376.* Prints the assessor table, the three ANOVA results and the three ICC results.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `assessor_stats` | `pd.DataFrame` | — | Output of `build_assessor_stats` |
| `df` | `pd.DataFrame` | — | Form-level DataFrame, passed through to `anova_test` and `icc_oneway` |

**Returns** — `None`.

**Behaviour**

1. Prints a 70-character `=` banner and the header "ASSESSOR HARSHNESS SUMMARY (sorted: harshest → most lenient)".
2. `print(assessor_stats[display_cols].to_string())` for the 8 display columns (the three `_z` columns are deliberately omitted; only `harshness_z` is shown).
3. Loops the three (metric, label) pairs and prints `anova_test` results as `F=%7.3f  p=%.4f`, appending `**` when `p < 0.05`.
4. Loops the same three pairs for `icc_oneway`, mapping the value to a verbal band with hard-coded cut-points: `< 0.4` poor, `< 0.6` moderate, `< 0.75` good, else excellent.

**Side effects** — prints to stdout only.

**Calls** — `assessor_analysis:anova_test`, `assessor_analysis:icc_oneway`.
**Called by** — `assessor_analysis:run_assessor_analysis`.

---

### 5.7 Entrypoint

#### `run_assessor_analysis(engine, show_plots: bool = True)`

*Lines 381–407.* Main entry point: load → score → aggregate → print → plot.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `engine` | SQLAlchemy `Engine` | — | Passed straight to `load_data` |
| `show_plots` | `bool` | `True` | When false, skips all three figures and `plt.show()` |

**Returns** — a 2-tuple `(df, assessor_stats)`: the form-level DataFrame with `scores` and `checklist_mean`, and the assessor-level aggregate.

**Behaviour**

1. Prints `"Loading BOH1 data …"`, calls `load_data(engine)`, then prints the form count and `df['assessor_name'].nunique()`.
2. `df = add_scores(df)`; `assessor_stats = build_assessor_stats(df)`.
3. `print_summary(assessor_stats, df)`.
4. If `show_plots`, builds all three figures (assigned to `fig1`/`fig2`/`fig3`, which are never used again) and calls `plt.show()` once.

**Side effects** — database read; prints to stdout; opens matplotlib windows / renders inline in the notebook. No files written.

**Calls** — `assessor_analysis:load_data`, `add_scores`, `build_assessor_stats`, `print_summary`, `plot_assessor_overview`, `plot_score_distributions`, `plot_scatter_gr_vs_checklist`.
**Called by** — `main.ipynb`.

**Example** (from `main_notebook_code.py`, lines 1412–1413):

```python
from assessor_analysis import run_assessor_analysis
df, assessor_stats = run_assessor_analysis(engine)
```

---

### 5.8 Module `__main__` block

*Lines 411–414.* Not a function. Creates `_engine = create_engine("postgresql://user:pass@localhost/dental_db")` and calls `run_assessor_analysis(_engine)`. The connection string is an unedited placeholder (the comment at line 412 says "Replace with your actual connection string"), so running `python assessor_analysis.py` as-is fails at connection time.

---

## 6. Call graph (this module)

```mermaid
flowchart LR
    run["run_assessor_analysis"] --> load["load_data"]
    run --> add["add_scores"]
    run --> build["build_assessor_stats"]
    run --> psum["print_summary"]
    run --> p1["plot_assessor_overview"]
    run --> p2["plot_score_distributions"]
    run --> p3["plot_scatter_gr_vs_checklist"]
    psum --> anova["anova_test"]
    psum --> icc["icc_oneway"]
    p1 --> u_bar["_bar_with_error"]
    load --> readdf["Utils:readDf"]
    add -.-> calc["calc_score"]
```

`calc_score` is shown with a dashed edge because it is passed to `.apply()` rather than called directly, so the static analyser records no edge. `Utils:readDf` is the module's only cross-module call.

---

## 7. Gotchas and known issues

- **Module name mismatch in the docstring.** Lines 1–11 call the file `boh1_assessor_analysis.py` and tell you to `from boh1_assessor_analysis import run_assessor_analysis` "from PostGresProcess.ipynb". The file is actually `assessor_analysis.py` and the orchestrator is `main.ipynb`. The documented import will `ModuleNotFoundError`.
- **`harshness_z` is not inverted, despite two comments saying it is.** The docstring at line 135 says "composite_harshness (inverted, so higher = harsher)" and the comment at line 151 says "Z-score normalise each metric then invert (low score = harsher)" — but lines 152–160 apply no inversion. In the actual output **more negative = harsher**, which is what the sort at line 162, the comment at line 157 and the plot legend at line 258 assume. Only the docstring and the line-151 comment are wrong, but they are the first thing a maintainer reads.
- **`icc_oneway` inflates ICC on sparse data.** `SS_within` (line 195) skips missing cells because `.stack()` drops NaN, but `MS_within` divides by `n * (k - 1)` (line 197), which counts every cell of the pivot including the empty ones. In a typical student × assessor matrix most cells are empty, so `MS_within` is badly underestimated and the ICC is pushed toward 1.
- **A NaN ICC is reported as "excellent".** In `print_summary` lines 372–375, the chain `("poor" if icc < 0.4 else … else "excellent")` falls through to `"excellent"` when `icc` is `np.nan`, because every NaN comparison is `False`. So the "insufficient variance" case — exactly the case the docstring warns about — prints `ICC=   nan  (excellent)`.
- **`icc_oneway`'s docstring does not match its code.** Line 180 says it "Treats each (student, date) case as the unit", but the pivot at line 187 indexes on `student_number` only, with `aggfunc="mean"` collapsing all of a student's dates together. `date` is never used in this function.
- **Panels 1–3 of `plot_assessor_overview` ignore the harshness ordering.** `run_assessor_analysis` sorts by `harshness_z` (line 231) and passes that order in, but `_bar_with_error` re-sorts internally with `np.argsort(series_mean.values)` (line 208). Panels 1–3 are each sorted by their own metric while panel 4 is sorted by `harshness_z`, so the four panels do not line up row-for-row — easy to misread.
- **Mixed `ddof` conventions.** The per-assessor SDs at lines 145–147 use pandas' default sample SD (`ddof=1`), while the z-score denominator at line 153 uses `ddof=0`. Not wrong, but the two "standard deviations" in the same table are not computed the same way.
- **`MIN_ASSESSMENTS = 2` means three different things.** Line 149 = minimum forms per assessor; line 169 = minimum non-null values of a *specific metric* per assessor; line 317 = minimum rows in a scatter group. A change to the constant silently changes all three filters. A threshold of 2 is also extremely low for anything inferential — an assessor with exactly 2 forms gets a SD from 2 points and enters the ANOVA.
- **Hard-coded query filters.** `FETCH_SQL` pins cohort `'BOH1'` (line 54) and `datetimeutc >= '2026-01-01'` (line 56). The date will need editing every year, and there is no `cohort` parameter anywhere in the public API — this module cannot analyse any other cohort without editing the source.
- **`gridspec` is imported (line 16) and never used.** Dead import.
- **`plot_assessor_overview` takes a `df` argument it never uses** (line 219). Callers must still pass one.
- **The pooled trend line in `plot_scatter_gr_vs_checklist` is fitted on a different population than the scatter.** `np.polyfit` at line 326 uses all of `sub`, but the scatter skips assessors with `< MIN_ASSESSMENTS` rows (lines 317–318). The dashed line therefore describes points that are not all drawn.
- **`plt.cm.tab20` gives only 20 distinct colours** (line 313); a cohort with more than 20 assessors produces duplicate colours in the scatter legend.
- **Figures are created but never closed.** `fig1`/`fig2`/`fig3` in `run_assessor_analysis` (lines 402–404) are assigned and discarded; repeated runs in a long notebook session accumulate open figures.
- **Unmapped answers are dropped, not zeroed.** In `calc_score` (lines 96–98) any answer string outside `SCORE_MAP` is skipped, so a form with mostly unrecognised answers can produce a high `score` from a single recognised item. `n_items` is retained per item code but is never used downstream to weight anything.
- **Compound item codes can collide.** `item_code.split("/")[0]` (line 105) maps `"022/024"` to `"022"`; if a form also has a plain `"022"` item, whichever comes later in the dict wins silently.
- **`checklist_mean` is unweighted over item codes** (lines 120–122), so a one-question item code has the same influence as a fifteen-question one.
- **The `__main__` block is non-functional as shipped** (line 413): `postgresql://user:pass@localhost/dental_db` is a placeholder.
