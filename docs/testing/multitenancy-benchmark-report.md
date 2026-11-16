# Multi-tenancy benchmark report

Run on 2026-11-16 02:03 with `python -m scripts.benchmark`: 50 questions to 3 made-up universities (`backend/benchmark/`), database `giu-bots-bench`.

Models: answers `ollama/giu-cv` (backups groq/qwen/qwen3.8-27b, google), embeddings `baai/bge-m3`.

| Measure | Result |
|---|---|
| Accuracy (all) | 48/50 (96%) |
| Leaks (another university's fact, document or assistant) | **0** |
| Errors (model or network) | 0 |
| Response time, mean / median / max | 6.83 s / 6.59 s / 31.56 s |
| Total run time | 346 s |

| Kind | Accuracy | Leaks |
|---|---|---|
| conflict | 21/21 (100%) | 0 |
| answerable | 14/14 (100%) | 0 |
| isolation | 6/6 (100%) | 0 |
| not_in_docs | 2/3 (67%) | 0 |
| arabic | 2/3 (67%) | 0 |
| handover | 3/3 (100%) | 0 |

| University | Accuracy | Leaks |
|---|---|---|
| bench-nvu | 16/17 (94%) | 0 |
| bench-dit | 17/17 (100%) | 0 |
| bench-rsu | 15/16 (94%) | 0 |

## Every question

| Id | University | Kind | Question | Result | Why | Time |
|---|---|---|---|---|---|---:|
| Q01 | bench-nvu | conflict | When is the application deadline? | ✅ |  | 31.6 s |
| Q02 | bench-nvu | conflict | How much is the tuition per semester? | ✅ |  | 12.0 s |
| Q03 | bench-nvu | conflict | How much is the application fee? | ✅ |  | 10.9 s |
| Q04 | bench-nvu | conflict | What is the minimum score for admission? | ✅ |  | 7.0 s |
| Q05 | bench-nvu | conflict | In how many installments can I pay the tuition? | ✅ |  | 14.9 s |
| Q06 | bench-nvu | answerable | Can I pay the summer semester in installments? | ✅ |  | 4.9 s |
| Q07 | bench-nvu | answerable | How many photos do I need to apply? | ✅ |  | 3.9 s |
| Q08 | bench-nvu | answerable | Where is the Admissions Office? | ✅ |  | 11.0 s |
| Q09 | bench-nvu | conflict | What are the library opening hours? | ✅ |  | 12.1 s |
| Q10 | bench-nvu | conflict | Where is the student clinic? | ✅ |  | 7.4 s |
| Q11 | bench-nvu | conflict | How much does a new student ID card cost? | ✅ |  | 7.4 s |
| Q12 | bench-nvu | answerable | How much is the monthly bus pass? | ✅ |  | 7.6 s |
| Q13 | bench-nvu | isolation | Where is the Marine Biology Lab? | ✅ |  | 2.6 s |
| Q14 | bench-nvu | isolation | How do I book the Coral Reef Field Station? | ✅ |  | 1.3 s |
| Q15 | bench-nvu | not_in_docs | Do you offer scholarships for athletes? | ✅ |  | 0.9 s |
| Q16 | bench-nvu | arabic | كام مصاريف الترم؟ | ❌ | missing 62,000 / 62000 / ٦٢٬٠٠٠ / ٦٢,٠٠٠ / 62 ألف / ٦٢ ألف | 1.0 s |
| Q17 | bench-nvu | handover | How much is the tuition per semester? | ✅ |  | 0.3 s |
| Q18 | bench-dit | conflict | When is the application deadline? | ✅ |  | 11.6 s |
| Q19 | bench-dit | conflict | How much is the tuition per semester? | ✅ |  | 10.5 s |
| Q20 | bench-dit | conflict | How much is the application fee? | ✅ |  | 9.5 s |
| Q21 | bench-dit | conflict | What is the minimum score for admission? | ✅ |  | 6.1 s |
| Q22 | bench-dit | conflict | In how many installments can I pay the tuition? | ✅ |  | 9.5 s |
| Q23 | bench-dit | answerable | Can I pay the summer semester in installments? | ✅ |  | 4.1 s |
| Q24 | bench-dit | answerable | If I withdraw in week 3, how much do I get back? | ✅ |  | 8.5 s |
| Q25 | bench-dit | answerable | Do I need my birth certificate to apply? | ✅ |  | 5.2 s |
| Q26 | bench-dit | conflict | What are the library opening hours? | ✅ |  | 8.4 s |
| Q27 | bench-dit | conflict | Where is the student clinic? | ✅ |  | 6.6 s |
| Q28 | bench-dit | conflict | How much does a new student ID card cost? | ✅ |  | 4.2 s |
| Q29 | bench-dit | answerable | Where do the buses come from? | ✅ |  | 4.8 s |
| Q30 | bench-dit | isolation | Who supervises the Marine Biology Lab? | ✅ |  | 0.7 s |
| Q31 | bench-dit | isolation | Is there a research vessel I can book? | ✅ |  | 0.8 s |
| Q32 | bench-dit | not_in_docs | Is there student housing on campus? | ✅ |  | 3.9 s |
| Q33 | bench-dit | arabic | امتى آخر ميعاد للتقديم؟ | ✅ |  | 5.0 s |
| Q34 | bench-dit | handover | What documents do I need to apply? | ✅ |  | 1.5 s |
| Q35 | bench-rsu | conflict | When is the application deadline? | ✅ |  | 9.1 s |
| Q36 | bench-rsu | conflict | How much is the tuition per semester? | ✅ |  | 7.7 s |
| Q37 | bench-rsu | conflict | How much is the application fee? | ✅ |  | 9.4 s |
| Q38 | bench-rsu | conflict | What is the minimum score for admission? | ✅ |  | 9.8 s |
| Q39 | bench-rsu | conflict | In how many installments can I pay the tuition? | ✅ |  | 7.5 s |
| Q40 | bench-rsu | answerable | Do I need a medical certificate to apply? | ✅ |  | 4.3 s |
| Q41 | bench-rsu | answerable | Where is the Marine Biology Lab? | ✅ |  | 10.2 s |
| Q42 | bench-rsu | answerable | Who supervises the Marine Biology Lab? | ✅ |  | 4.2 s |
| Q43 | bench-rsu | answerable | How do I book the Coral Reef Field Station? | ✅ |  | 5.0 s |
| Q44 | bench-rsu | answerable | When is the lab safety training held? | ✅ |  | 3.9 s |
| Q45 | bench-rsu | answerable | Can students book the research vessel? | ✅ |  | 6.6 s |
| Q46 | bench-rsu | isolation | What are the library opening hours? | ✅ |  | 4.4 s |
| Q47 | bench-rsu | isolation | How much is the monthly bus pass? | ✅ |  | 5.7 s |
| Q48 | bench-rsu | not_in_docs | Can I transfer from another university? | ❌ | missing don't have / do not have | 8.3 s |
| Q49 | bench-rsu | arabic | معمل الأحياء البحرية فين؟ | ✅ |  | 6.8 s |
| Q50 | bench-rsu | handover | What is the application deadline? | ✅ |  | 0.8 s |
