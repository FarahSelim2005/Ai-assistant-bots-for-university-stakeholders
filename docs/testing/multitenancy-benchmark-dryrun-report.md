# Multi-tenancy benchmark report (dry run)

Run on 2026-11-15 00:23 with `python -m scripts.benchmark --dry-run`: 50 questions to 3 made-up universities (`backend/benchmark/`), database `giu-bots-test`.

**Dry run: no model and no network.** Embeddings are word-hashing stand-ins and the "answer" is the retrieved text, so this checks the pipeline and the isolation (which university's documents are searched), not the answer quality. Accuracy here is not the real one.

| Measure | Result |
|---|---|
| Accuracy (all) | 40/50 (80%) |
| Leaks (another university's fact, document or assistant) | **0** |
| Errors (model or network) | 0 |
| Response time, mean / median / max | 0.25 s / 0.25 s / 0.63 s |
| Total run time | 16 s |

| Kind | Accuracy | Leaks |
|---|---|---|
| conflict | 19/21 (90%) | 0 |
| answerable | 14/14 (100%) | 0 |
| isolation | 4/6 (67%) | 0 |
| not_in_docs | 3/3 (100%) | 0 |
| arabic | 0/3 (0%) | 0 |
| handover | 0/3 (0%) | 0 |

| University | Accuracy | Leaks |
|---|---|---|
| bench-nvu | 13/17 (76%) | 0 |
| bench-dit | 14/17 (82%) | 0 |
| bench-rsu | 13/16 (81%) | 0 |

## Every question

| Id | University | Kind | Question | Result | Why | Time |
|---|---|---|---|---|---|---:|
| Q01 | bench-nvu | conflict | When is the application deadline? | ✅ |  | 0.2 s |
| Q02 | bench-nvu | conflict | How much is the tuition per semester? | ✅ |  | 0.5 s |
| Q03 | bench-nvu | conflict | How much is the application fee? | ✅ |  | 0.0 s |
| Q04 | bench-nvu | conflict | What is the minimum score for admission? | ✅ |  | 0.5 s |
| Q05 | bench-nvu | conflict | In how many installments can I pay the tuition? | ✅ |  | 0.2 s |
| Q06 | bench-nvu | answerable | Can I pay the summer semester in installments? | ✅ |  | 0.0 s |
| Q07 | bench-nvu | answerable | How many photos do I need to apply? | ✅ |  | 0.3 s |
| Q08 | bench-nvu | answerable | Where is the Admissions Office? | ✅ |  | 0.2 s |
| Q09 | bench-nvu | conflict | What are the library opening hours? | ❌ | missing 8:00 / 8 am / 8am / 8 a.m, 20:00 / 8 pm / 8pm / 8 p.m | 0.2 s |
| Q10 | bench-nvu | conflict | Where is the student clinic? | ✅ |  | 0.3 s |
| Q11 | bench-nvu | conflict | How much does a new student ID card cost? | ✅ |  | 0.1 s |
| Q12 | bench-nvu | answerable | How much is the monthly bus pass? | ✅ |  | 0.4 s |
| Q13 | bench-nvu | isolation | Where is the Marine Biology Lab? | ❌ | missing don't have / do not have | 0.4 s |
| Q14 | bench-nvu | isolation | How do I book the Coral Reef Field Station? | ✅ |  | 0.4 s |
| Q15 | bench-nvu | not_in_docs | Do you offer scholarships for athletes? | ✅ |  | 0.3 s |
| Q16 | bench-nvu | arabic | كام مصاريف الترم؟ | ❌ | missing 62,000 / 62000 / ٦٢٬٠٠٠ / ٦٢,٠٠٠ / 62 ألف / ٦٢ ألف | 0.2 s |
| Q17 | bench-nvu | handover | How much is the tuition per semester? | ❌ | missing don't have / do not have; no hand-over to Admissions Office | 0.4 s |
| Q18 | bench-dit | conflict | When is the application deadline? | ✅ |  | 0.2 s |
| Q19 | bench-dit | conflict | How much is the tuition per semester? | ✅ |  | 0.3 s |
| Q20 | bench-dit | conflict | How much is the application fee? | ✅ |  | 0.2 s |
| Q21 | bench-dit | conflict | What is the minimum score for admission? | ✅ |  | 0.4 s |
| Q22 | bench-dit | conflict | In how many installments can I pay the tuition? | ✅ |  | 0.6 s |
| Q23 | bench-dit | answerable | Can I pay the summer semester in installments? | ✅ |  | 0.2 s |
| Q24 | bench-dit | answerable | If I withdraw in week 3, how much do I get back? | ✅ |  | 0.1 s |
| Q25 | bench-dit | answerable | Do I need my birth certificate to apply? | ✅ |  | 0.3 s |
| Q26 | bench-dit | conflict | What are the library opening hours? | ❌ | missing 9:00 / 9 am / 9am / 9 a.m, 21:00 / 9 pm / 9pm / 9 p.m | 0.3 s |
| Q27 | bench-dit | conflict | Where is the student clinic? | ✅ |  | 0.5 s |
| Q28 | bench-dit | conflict | How much does a new student ID card cost? | ✅ |  | 0.3 s |
| Q29 | bench-dit | answerable | Where do the buses come from? | ✅ |  | 0.3 s |
| Q30 | bench-dit | isolation | Who supervises the Marine Biology Lab? | ✅ |  | 0.3 s |
| Q31 | bench-dit | isolation | Is there a research vessel I can book? | ✅ |  | 0.1 s |
| Q32 | bench-dit | not_in_docs | Is there student housing on campus? | ✅ |  | 0.4 s |
| Q33 | bench-dit | arabic | امتى آخر ميعاد للتقديم؟ | ❌ | missing 31 / ٣١ | 0.3 s |
| Q34 | bench-dit | handover | What documents do I need to apply? | ❌ | no hand-over to Admissions Office | 0.3 s |
| Q35 | bench-rsu | conflict | When is the application deadline? | ✅ |  | 0.6 s |
| Q36 | bench-rsu | conflict | How much is the tuition per semester? | ✅ |  | 0.1 s |
| Q37 | bench-rsu | conflict | How much is the application fee? | ✅ |  | 0.0 s |
| Q38 | bench-rsu | conflict | What is the minimum score for admission? | ✅ |  | 0.5 s |
| Q39 | bench-rsu | conflict | In how many installments can I pay the tuition? | ✅ |  | 0.1 s |
| Q40 | bench-rsu | answerable | Do I need a medical certificate to apply? | ✅ |  | 0.3 s |
| Q41 | bench-rsu | answerable | Where is the Marine Biology Lab? | ✅ |  | 0.0 s |
| Q42 | bench-rsu | answerable | Who supervises the Marine Biology Lab? | ✅ |  | 0.0 s |
| Q43 | bench-rsu | answerable | How do I book the Coral Reef Field Station? | ✅ |  | 0.0 s |
| Q44 | bench-rsu | answerable | When is the lab safety training held? | ✅ |  | 0.0 s |
| Q45 | bench-rsu | answerable | Can students book the research vessel? | ✅ |  | 0.1 s |
| Q46 | bench-rsu | isolation | What are the library opening hours? | ✅ |  | 0.2 s |
| Q47 | bench-rsu | isolation | How much is the monthly bus pass? | ❌ | missing don't have / do not have | 0.2 s |
| Q48 | bench-rsu | not_in_docs | Can I transfer from another university? | ✅ |  | 0.3 s |
| Q49 | bench-rsu | arabic | معمل الأحياء البحرية فين؟ | ❌ | missing M210 / م210 | 0.2 s |
| Q50 | bench-rsu | handover | What is the application deadline? | ❌ | missing don't have / do not have; no hand-over to Admissions Office | 0.1 s |
