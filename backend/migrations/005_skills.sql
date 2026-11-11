-- 005: skills, and prompts built from parts with the university's name.
--
-- * tenants: short_name (used for "{university}" in prompts and texts), has_cv_model (a CV
--   model trained on its CV templates: the "cv" skill works) and campus_map (its buildings,
--   rooms and map: the "map" skill works). GIU: "GIU", true, true; every other tenant: its
--   name, false, false.
-- * prompt_mode on templates and agents: "composed" (the prompt is built from parts: who it
--   is, its instructions, the rules of its answer mode and skills, the platform's rules) or
--   "complete" (the instructions are the whole prompt). GIU's four assistants keep their
--   complete prompts, unchanged (the Career prompt is what giu-cv was trained on).
-- * agent_templates: the four ready-made assistants for any university, in parts, with
--   "{university}" instead of GIU (from app/agents/templates.py: TEMPLATES).
-- * Other universities' assistants that still have 004's text (copied from GIU's) get the new
--   template text; their "cv" skill is dropped where the university has no CV model.
--
-- Safe to run again.

ALTER TABLE tenants ADD COLUMN IF NOT EXISTS short_name   TEXT NOT NULL DEFAULT '';
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS has_cv_model BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS campus_map   BOOLEAN NOT NULL DEFAULT false;
UPDATE tenants SET short_name = 'GIU', has_cv_model = true, campus_map = true WHERE slug = 'giu' AND short_name = '';
UPDATE tenants SET short_name = name WHERE short_name = '';

ALTER TABLE agent_templates ADD COLUMN IF NOT EXISTS prompt_mode TEXT NOT NULL DEFAULT 'composed'
    CHECK (prompt_mode IN ('composed', 'complete'));
ALTER TABLE agents ADD COLUMN IF NOT EXISTS prompt_mode TEXT NOT NULL DEFAULT 'composed'
    CHECK (prompt_mode IN ('composed', 'complete'));

-- GIU's four assistants: their instructions are their whole (unchanged) prompts.
UPDATE agents SET prompt_mode = 'complete' WHERE id IN ('a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000002', 'a0000000-0000-4000-8000-000000000003', 'a0000000-0000-4000-8000-000000000004') AND prompt_mode <> 'complete';

-- Templates: the ready-made assistants for any university, in parts.
UPDATE agent_templates SET
    summary = $t$Advising, probation, course plans and credits, thesis and internship eligibility$t$,
    subtitle = $t$Answers from the {university} advising guidelines$t$,
    description = $t$Degree requirements, credit hours, prerequisites, course planning, study plan, which courses to take next semester, GPA, graduation timeline, graduation requirements, academic advising and advisors, the advising list, probation, adding hours, makeup exams, electives, Bachelor thesis and internship eligibility, memos and graduation plans, the courses and credits of each semester, which courses a major or program has, the majors of each program. التخرج، الساعات المعتمدة، المواد، الخطة الدراسية، الجي بي إيه، المرشد الأكاديمي، الادفايزنج، البروبيشن، تزويد الساعات، الميك اب، الباتشلر، مواد كل ترم، مواد التخصص، المنهج، التخصصات.$t$,
    audiences = ARRAY[$t$student$t$, $t$staff$t$]::TEXT[],
    answer_mode = $t$docs$t$,
    prompt_mode = $t$composed$t$,
    instructions = $t$You help students and advisors with the advising process: what advising means, why a
student is put on the advising list, probation, adding courses or hours, schedule rules,
electives, Bachelor thesis / internship eligibility, memos, graduation plans, and the
courses and credits of each semester of each program. If a course question does not say
which program, and the programs differ, give the answer for each program.$t$,
    fallback_en = $t$Sorry, I don't have information about that. Please contact the academic advising office or your advisor.$t$,
    fallback_ar = $t$آسف، معنديش معلومات عن ده. من فضلك تواصل مع مكتب الإرشاد الأكاديمي أو مع الأدفايزر بتاعك.$t$,
    welcome = $t$Ask about advising, probation, adding hours or thesis eligibility, or try one of these:$t$,
    placeholder = $t$Ask about advising, probation, adding hours, eligibility...$t$,
    examples = ARRAY[$t$Why was I put on the advising list?$t$, $t$Can a probation student add hours?$t$, $t$What is the minimum load I can take?$t$, $t$Am I eligible for the Bachelor thesis?$t$]::TEXT[],
    skills = ARRAY[$t$files$t$, $t$images$t$, $t$editor$t$, $t$voice$t$]::TEXT[],
    max_answer_tokens = 400,
    name = $t$Graduation & Advising Assistant$t$
WHERE key = 'graduation_advising';

UPDATE agent_templates SET
    summary = $t$Leave, public holidays, contracts, resignation and labour law$t$,
    subtitle = $t${university} HR information and labour law$t$,
    description = $t$Staff leave types (annual, emergency, sick, maternity, paternity, childcare and unpaid leave), official public holidays, salaries and annual raise, benefits, medical insurance for employees, staff policies, labour law, contracts, resignation, notice period, termination, working hours and staff complaints. الإجازات، إجازة سنوية، إجازة عارضة، إجازة مرضية، إجازة وضع، الأجازات الرسمية، المرتبات، العلاوة، التأمين الطبي، لوائح الموظفين، قانون العمل، العقد، الاستقالة، الشكاوى.$t$,
    audiences = ARRAY[$t$staff$t$]::TEXT[],
    answer_mode = $t$docs$t$,
    prompt_mode = $t$composed$t$,
    instructions = $t$You help {university} staff with employment questions: annual and emergency leave,
maternity, paternity and childcare leave, contracts, the annual raise, resignation, notice
and termination, official public holidays and workplace conduct. When a rule in the context
comes from the labour law (marked "by law"), say it is the law, not a {university} policy.
Holiday dates marked as expected are not final: say they are expected.$t$,
    fallback_en = $t$Sorry, I don't have information about that. Please contact the {university} Human Resources (HR) department.$t$,
    fallback_ar = $t$آسف، معنديش معلومات عن ده. من فضلك تواصل مع إدارة الموارد البشرية (HR) في الجامعة.$t$,
    welcome = $t$Ask about leave, public holidays, contracts or resignation, or try one of these:$t$,
    placeholder = $t$Ask about leave, holidays, contracts, notice period...$t$,
    examples = ARRAY[$t$How many days of annual leave do I get?$t$, $t$How long is maternity leave?$t$, $t$What are the official holidays this year?$t$, $t$What is the notice period if I resign?$t$]::TEXT[],
    skills = ARRAY[$t$files$t$, $t$images$t$, $t$editor$t$, $t$voice$t$]::TEXT[],
    max_answer_tokens = 400,
    name = $t$HR & Policies Assistant$t$
WHERE key = 'hr_policies';

UPDATE agent_templates SET
    summary = $t$Internships, the career fair, CV review, interviews, skills and career paths$t$,
    subtitle = $t${university} career information and general career advice$t$,
    description = $t$Internships, the internship semester, the career fair and employers, CV and resume writing, CV review, interview preparation, job applications, LinkedIn, skills for a major and career paths. الانترنشيب، التدريب، معرض التوظيف، السي في، السيرة الذاتية، الانترفيو، الشغل، الوظايف.$t$,
    audiences = ARRAY[$t$student$t$, $t$staff$t$]::TEXT[],
    answer_mode = $t$advice$t$,
    prompt_mode = $t$composed$t$,
    instructions = $t$You help {university} students prepare for internships and jobs: career resources,
internship requirements, the career fair, how to apply, CVs, interviews, skills for their
major and career paths. When a student attaches a CV and asks for feedback, reply with
these short sections: Strengths, Problems, Improved bullets (two or three of theirs,
rewritten with action verbs and results), Skills to add, Next steps (three concrete actions).
Only help with internships, jobs and careers; for other topics, say politely that other
{university} assistants can help.$t$,
    fallback_en = $t$Sorry, I don't have information about that. Please contact the {university} Career Center or your faculty for help.$t$,
    fallback_ar = $t$آسف، معنديش معلومات عن ده. من فضلك تواصل مع الكارير سنتر في الجامعة أو مع الكلية.$t$,
    welcome = $t$Ask about internships, the career fair, your CV or interviews, or try one of these:$t$,
    placeholder = $t$Ask about internships, CVs, interviews, career paths...$t$,
    examples = ARRAY[$t$When is the next career fair?$t$, $t$How do I find an internship?$t$, $t$How do I prepare for an interview?$t$, $t$What skills do I need as a computer science student?$t$]::TEXT[],
    skills = ARRAY[$t$files$t$, $t$images$t$, $t$cv$t$, $t$editor$t$, $t$voice$t$]::TEXT[],
    max_answer_tokens = 1500,
    name = $t$Internship & Career Assistant$t$
WHERE key = 'internship_career';

UPDATE agent_templates SET
    summary = $t$Lab access, supervisors, equipment, research resources, campus offices$t$,
    subtitle = $t$Answers from official {university} documents$t$,
    description = $t$Lab access, lab rooms and opening hours, lab supervisors, equipment and booking, research funding and grants, research resources, thesis support and publications. Where things are on campus: buildings, rooms and floors, offices (admission, student affairs, finance, academic coordinator), the library, the clinic, the gym, sports courts, the food court and parking. المعامل، الأجهزة، منحة البحث، البحث العلمي، الرسالة، النشر، فين المباني والأوض والمكاتب، شئون الطلبة، الادميشن، المكتبة، العيادة، الجيم، الباركينج.$t$,
    audiences = ARRAY[$t$student$t$, $t$staff$t$]::TEXT[],
    answer_mode = $t$docs$t$,
    prompt_mode = $t$composed$t$,
    instructions = $t$You help students and staff with questions about labs, research facilities, research
funding, thesis support, and where to find campus buildings, rooms and offices.$t$,
    fallback_en = $t$Sorry, I don't have information about that. Please contact the relevant office or department for help.$t$,
    fallback_ar = $t$آسف، معنديش معلومات عن ده. من فضلك تواصل مع المكتب أو القسم المختص للمساعدة.$t$,
    welcome = $t$Ask anything about {university} labs, rooms and offices, or try one of these:$t$,
    placeholder = $t$Ask about labs, offices, rooms, research funding...$t$,
    examples = ARRAY[$t$Where is the AI lab?$t$, $t$Where is the Admission Office?$t$, $t$How do I pay my tuition fees?$t$, $t$Where is the library?$t$]::TEXT[],
    skills = ARRAY[$t$files$t$, $t$images$t$, $t$editor$t$, $t$map$t$, $t$voice$t$]::TEXT[],
    max_answer_tokens = 400,
    name = $t$Labs & Research Assistant$t$
WHERE key = 'labs_research';

-- Other universities' assistants made by 004 from a template and not changed since (their
-- instructions are still GIU's): the new template's text.
UPDATE agents a SET
    summary = t.summary,
    subtitle = t.subtitle,
    description = t.description,
    audiences = t.audiences,
    answer_mode = t.answer_mode,
    prompt_mode = t.prompt_mode,
    instructions = t.instructions,
    fallback_en = t.fallback_en,
    fallback_ar = t.fallback_ar,
    welcome = t.welcome,
    placeholder = t.placeholder,
    examples = t.examples,
    max_answer_tokens = t.max_answer_tokens,
    skills = CASE WHEN tn.has_cv_model THEN t.skills ELSE array_remove(t.skills, 'cv') END
FROM agent_templates t, tenants tn, agents g
WHERE t.key = a.template_key
  AND tn.id = a.tenant_id
  AND g.template_key = a.template_key AND g.id IN ('a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000002', 'a0000000-0000-4000-8000-000000000003', 'a0000000-0000-4000-8000-000000000004')  -- GIU's assistant from the same template
  AND a.id NOT IN ('a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000002', 'a0000000-0000-4000-8000-000000000003', 'a0000000-0000-4000-8000-000000000004')
  AND a.instructions = g.instructions;
