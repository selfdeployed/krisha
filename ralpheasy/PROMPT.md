@plan.md @activity.md

You are running one iteration of an autonomous coding loop for the Krisha
"best offer" methodology project. This is a data-analyst project for
someone apartment-hunting on krisha.kz in Astana; the deliverable is a
METHODOLOGY (design docs + working utility code, exercised on a small real
sample), not a production run of a full-scale data pipeline.

## Hard constraints (read before doing anything)

- Do NOT run any script as a processing/modeling pipeline against the full
  AstanaLinksParserJune2026_parsed.csv (~35k rows) or 2025_data.csv
  (~38k rows). It is fine to open one of these files with a single read
  pass to hand-pick a small sample (this only happens in the
  sample_fixture task) — what is forbidden is running a parser,
  feature-engineering, or regression step over the full file, in any task.
- DO actually run the real code (parser, feature engineering, OLS fit)
  against methodology/samples/sample_rows.csv and its derived files —
  every implementation task's steps say exactly what to run and what
  output file to produce. Verifying "this would probably work" without
  running it is not acceptable; a synthetic/fabricated DataFrame is only
  acceptable for isolated pure-math checks (e.g. the haversine formula
  itself), never as a substitute for exercising the pipeline on the real
  sample.
- The sample-scale OLS fit (in ranking_scaffold_code) uses a deliberately
  TRIMMED formula (2-3 continuous predictors) because ~15-20 rows cannot
  support the full dummy-heavy formula without being rank-deficient. Its
  purpose is to prove the code path works, not to produce a trustworthy
  coefficient — say so explicitly wherever its output is presented.
- 2025_data.csv is out of scope for this run. Do not build anything that
  merges it in.
- Always read/write the CSVs and any Cyrillic text with encoding='utf-8'
  explicitly, including when writing to files. Avoid printing raw Cyrillic
  to the Windows console (cp1251 can crash on some characters, e.g. the
  tenge sign ₸) — write results to a UTF-8 file and read them back with
  the Read tool instead.
- Do not git init (a one-time bootstrap happens in the bootstrap_git task
  — never run it a second time). Do not change git remotes. Do not push.
- Never touch global git config; if commit identity is missing, set it
  locally for this repo only.
- No browser/UI verification tooling (Playwright etc.) is needed or should
  be configured — this is a pure data/stats task with no frontend.

## Steps for this iteration

1. Read activity.md to see what was recently accomplished and the current
   state of the project.
2. Open ralpheasy/plan.md and find the single highest-priority task whose
   "passes" is false AND all of whose depends_on tasks have "passes": true.
   If none qualify (all done, or all remaining are blocked), state that
   clearly and stop.
3. Set that task's "passes" to "in_progress" in plan.md.
4. Work on exactly that one task: implement only the steps listed for it.
   Do not start other tasks even if they look fast or related.
5. Verify by actually running the commands the task's steps specify and
   looking at the real output — do not assume it would pass. Fix and
   re-run until the real output looks correct.
6. Append a dated entry to activity.md: what you changed, which commands
   you ran to verify, and real example output/numbers as evidence. Update
   the "Current Status" block at the top of activity.md too.
7. Update that task's "passes" from "in_progress" to true in plan.md. Do
   not modify any other task's passes value, id, description, steps, or
   depends_on.
8. Make exactly one git commit for this task's changes only, with a clear
   single-line message referencing the task id.

When ALL tasks in plan.md have "passes": true, output exactly:
<promise>COMPLETE</promise>
