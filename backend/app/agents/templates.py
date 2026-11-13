"""GIU's four assistants, and the ready-made assistants (templates) any university can start from.

GIU_AGENTS: GIU's own rows of the agents table, as migration 004 inserted them (with the fixed
ids below, so GIU's document folders are the same on every computer). Their prompts are
complete (prompt_mode "complete"): exactly GIU's prompts in app/rag/prompts.py, unchanged, so
GIU answers as before (the Career prompt is what giu-cv was trained on). Their texts come
from the former agent classes (fallbacks), app/agents/directory.py (descriptions, used for
hand-overs) and frontend/src/agents.js (what the chat screen shows).

TEMPLATES: the agent_templates table since migration 005. The same four assistants for any
university: their prompt is built from parts (prompt_mode "composed", see system_prompt in
app/rag/prompts.py), and "{university}" stands for the university's short name.

At run time the app reads the database; this module is what the migrations were written from
and what the tests use without a database (tests/test_tenants.py checks they are identical).
"""
import uuid

from app.rag.prompts import ADVISING_SYSTEM_PROMPT, CAREER_SYSTEM_PROMPT, HR_SYSTEM_PROMPT, LABS_SYSTEM_PROMPT

AUDIENCES = ("student", "staff")
ANSWER_MODES = ("docs", "advice")  # docs: only from the documents; advice: may also give general advice
SKILLS = ("files", "images", "cv", "editor", "map", "voice")


def skills_for(campus_map: bool) -> list[str]:
    """The skills a new assistant gets: everything GIU's assistants do (files, pictures, CV
    rewrites, the document editor, the voice call), and the campus map where the university
    has one."""
    return [skill for skill in SKILLS if skill != "map" or campus_map]
PROMPT_MODES = ("composed", "complete")  # composed: built from parts; complete: the instructions are the whole prompt

GIU_AGENT_IDS = {
    "graduation_advising": uuid.UUID("a0000000-0000-4000-8000-000000000001"),
    "hr_policies": uuid.UUID("a0000000-0000-4000-8000-000000000002"),
    "internship_career": uuid.UUID("a0000000-0000-4000-8000-000000000003"),
    "labs_research": uuid.UUID("a0000000-0000-4000-8000-000000000004"),
}

GIU_AGENTS = [
    {
        "key": "graduation_advising",
        "name": "Graduation & Advising Assistant",
        "summary": "Advising, probation, course plans and ECTS, B.Sc./internship eligibility",
        "subtitle": "Answers from the GIU advising guidelines",
        "description": (
            "Degree requirements, credit hours, prerequisites, course planning, study plan, "
            "which courses to take next semester, GPA, graduation timeline, graduation "
            "requirements, academic advising and advisors, the advising list, probation, adding "
            "hours, makeup exams, electives, Bachelor thesis and internship eligibility, memos "
            "and graduation plans, the courses and ECTS of each semester (Computer Science, "
            "Business Informatics, Business Administration, Design, Engineering, Biotechnology, "
            "Physical Therapy, Architectural Engineering and Pharmaceutical Engineering curriculum), "
            "which courses a major "
            "or program has, the majors of each program. "
            "التخرج، الساعات المعتمدة، المواد، الخطة الدراسية، الجي بي إيه، المرشد الأكاديمي، "
            "الادفايزنج، البروبيشن، تزويد الساعات، الميك اب، الباتشلر، مواد كل ترم، مواد التخصص، المنهج، التخصصات."
        ),
        "audiences": ["student", "staff"],
        "answer_mode": "docs",
        "instructions": ADVISING_SYSTEM_PROMPT,
        "fallback_en": ("Sorry, I don't have information about that. "
                        "Please contact the Academic Performance Department or your advisor."),
        "fallback_ar": ("آسف، معنديش معلومات عن ده. "
                        "من فضلك تواصل مع قسم الأداء الأكاديمي (Academic Performance) أو مع الأدفايزر بتاعك."),
        "welcome": "Ask about advising, probation, adding hours or B.Sc. eligibility, or try one of these:",
        "placeholder": "Ask about advising, probation, adding hours, eligibility...",
        "examples": [
            "Why was I put on the advising list?",
            "Can a probation student add hours?",
            "What is the minimum load I can take?",
            "Am I eligible for the Bachelor thesis?",
        ],
        "skills": ["files", "images", "editor", "map", "voice"],
        "max_answer_tokens": 400,
        "position": 1,
        "prompt_mode": "complete",
    },
    {
        "key": "hr_policies",
        "name": "HR & Policies Assistant",
        "summary": "Leave, public holidays, contracts, resignation and labour law",
        "subtitle": "Egyptian labour law and GIU HR information",
        "description": (
            "Staff leave types (annual, emergency, sick, maternity, paternity, childcare and unpaid "
            "leave), official public holidays in Egypt, salaries and annual raise, benefits, medical "
            "insurance for employees, staff policies, Egyptian labour law, contracts, resignation, "
            "notice period, termination, working hours and staff complaints. "
            "الإجازات، إجازة سنوية، إجازة عارضة، إجازة مرضية، إجازة وضع، الأجازات الرسمية، المرتبات، العلاوة، "
            "التأمين الطبي، لوائح الموظفين، قانون العمل، العقد، الاستقالة، الشكاوى."
        ),
        "audiences": ["staff"],
        "answer_mode": "docs",
        "instructions": HR_SYSTEM_PROMPT,
        "fallback_en": ("Sorry, I don't have information about that. "
                        "Please contact the GIU Human Resources (HR) department."),
        "fallback_ar": ("آسف، معنديش معلومات عن ده. "
                        "من فضلك تواصل مع إدارة الموارد البشرية (HR) في الجامعة."),
        "welcome": "Ask about leave, public holidays, contracts or resignation, or try one of these:",
        "placeholder": "Ask about leave, holidays, contracts, notice period...",
        "examples": [
            "How many days of annual leave do I get?",
            "How long is maternity leave?",
            "What are the official holidays in Egypt?",
            "What is the notice period if I resign?",
        ],
        "skills": ["files", "images", "editor", "map", "voice"],
        "max_answer_tokens": 400,
        "position": 2,
        "prompt_mode": "complete",
    },
    {
        "key": "internship_career",
        "name": "Internship & Career Assistant",
        "summary": "Internships, the career fair, CV review, interviews, skills and career paths",
        "subtitle": "GIU career information and general career advice",
        "description": (
            "Internships, the GIU Internship Semester, the GIU Career Fair and employers, CV and "
            "resume writing, CV review, interview preparation, job applications, LinkedIn, "
            "skills for a major and career paths. "
            "الانترنشيب، التدريب، معرض التوظيف، السي في، السيرة الذاتية، الانترفيو، الشغل، الوظايف."
        ),
        "audiences": ["student", "staff"],
        "answer_mode": "advice",  # CV, interview and career-path advice need no GIU document
        "instructions": CAREER_SYSTEM_PROMPT,
        "fallback_en": ("Sorry, I don't have information about that. "
                        "Please contact the GIU Career Center or your faculty for help."),
        "fallback_ar": ("آسف، معنديش معلومات عن ده. "
                        "من فضلك تواصل مع الكارير سنتر في الجامعة أو مع الكلية."),
        "welcome": "Ask about internships, the GIU Career Fair, your CV or interviews, or try one of these:",
        "placeholder": "Ask about internships, CVs, interviews, career paths...",
        "examples": [
            "When was the GIU Career Fair 2025?",
            "How long is the GIU Internship Semester?",
            "How do I prepare for an interview?",
            "What skills do I need as a computer science student?",
        ],
        "skills": ["files", "images", "cv", "editor", "map", "voice"],
        "max_answer_tokens": 1500,  # a full CV rewrite is long
        "position": 3,
        "prompt_mode": "complete",
    },
    {
        "key": "labs_research",
        "name": "Labs & Research Assistant",
        "summary": "Lab access, supervisors, equipment, research resources, campus offices",
        "subtitle": "Answers from official GIU documents",
        "description": (
            "Lab access, lab rooms and opening hours, lab supervisors, equipment and booking, "
            "research funding and grants, research resources, thesis support and publications. "
            "Where things are on campus: buildings A, M and S, rooms and floors, offices (admission, "
            "student affairs, finance, academic coordinator), the library, the clinic, the gym, the "
            "supermarket, sports courts, the food court and parking. "
            "المعامل، الأجهزة، منحة البحث، البحث العلمي، الرسالة، النشر، فين المباني والأوض والمكاتب، "
            "شئون الطلبة، الادميشن، المكتبة، العيادة، الجيم، الباركينج."
        ),
        "audiences": ["student", "staff"],
        "answer_mode": "docs",
        "instructions": LABS_SYSTEM_PROMPT,
        "fallback_en": ("Sorry, I don't have information about that. "
                        "Please contact the relevant office or department for help."),
        "fallback_ar": ("آسف، معنديش معلومات عن ده. "
                        "من فضلك تواصل مع المكتب أو القسم المختص للمساعدة."),
        "welcome": "Ask anything about GIU labs, rooms and offices, or try one of these:",
        "placeholder": "Ask about labs, offices, rooms, research funding...",
        "examples": [
            "Where is the AI lab?",
            "Where is the Admission Office?",
            "How do I pay my tuition fees?",
            "Where is the gym?",
        ],
        "skills": ["files", "images", "editor", "map", "voice"],
        "max_answer_tokens": 400,
        "position": 4,
        "prompt_mode": "complete",
    },
]


TEMPLATES = [
    {
        "key": "graduation_advising",
        "name": "Graduation & Advising Assistant",
        "summary": "Advising, probation, course plans and credits, thesis and internship eligibility",
        "subtitle": "Answers from the {university} advising guidelines",
        "description": (
            "Degree requirements, credit hours, prerequisites, course planning, study plan, "
            "which courses to take next semester, GPA, graduation timeline, graduation "
            "requirements, academic advising and advisors, the advising list, probation, adding "
            "hours, makeup exams, electives, Bachelor thesis and internship eligibility, memos "
            "and graduation plans, the courses and credits of each semester, which courses a major "
            "or program has, the majors of each program. "
            "التخرج، الساعات المعتمدة، المواد، الخطة الدراسية، الجي بي إيه، المرشد الأكاديمي، "
            "الادفايزنج، البروبيشن، تزويد الساعات، الميك اب، الباتشلر، مواد كل ترم، مواد التخصص، المنهج، التخصصات."
        ),
        "audiences": ["student", "staff"],
        "answer_mode": "docs",
        "instructions": (
            "You help students and advisors with the advising process: what advising means, why a\n"
            "student is put on the advising list, probation, adding courses or hours, schedule rules,\n"
            "electives, Bachelor thesis / internship eligibility, memos, graduation plans, and the\n"
            "courses and credits of each semester of each program. If a course question does not say\n"
            "which program, and the programs differ, give the answer for each program."
        ),
        "fallback_en": ("Sorry, I don't have information about that. "
                        "Please contact the academic advising office or your advisor."),
        "fallback_ar": ("آسف، معنديش معلومات عن ده. "
                        "من فضلك تواصل مع مكتب الإرشاد الأكاديمي أو مع الأدفايزر بتاعك."),
        "welcome": "Ask about advising, probation, adding hours or thesis eligibility, or try one of these:",
        "placeholder": "Ask about advising, probation, adding hours, eligibility...",
        "examples": [
            "Why was I put on the advising list?",
            "Can a probation student add hours?",
            "What is the minimum load I can take?",
            "Am I eligible for the Bachelor thesis?",
        ],
        "skills": ["files", "images", "editor", "voice"],
        "max_answer_tokens": 400,
        "position": 1,
        "prompt_mode": "composed",
    },
    {
        "key": "hr_policies",
        "name": "HR & Policies Assistant",
        "summary": "Leave, public holidays, contracts, resignation and labour law",
        "subtitle": "{university} HR information and labour law",
        "description": (
            "Staff leave types (annual, emergency, sick, maternity, paternity, childcare and unpaid "
            "leave), official public holidays, salaries and annual raise, benefits, medical "
            "insurance for employees, staff policies, labour law, contracts, resignation, "
            "notice period, termination, working hours and staff complaints. "
            "الإجازات، إجازة سنوية، إجازة عارضة، إجازة مرضية، إجازة وضع، الأجازات الرسمية، المرتبات، العلاوة، "
            "التأمين الطبي، لوائح الموظفين، قانون العمل، العقد، الاستقالة، الشكاوى."
        ),
        "audiences": ["staff"],
        "answer_mode": "docs",
        "instructions": (
            "You help {university} staff with employment questions: annual and emergency leave,\n"
            "maternity, paternity and childcare leave, contracts, the annual raise, resignation, notice\n"
            "and termination, official public holidays and workplace conduct. When a rule in the context\n"
            "comes from the labour law (marked \"by law\"), say it is the law, not a {university} policy.\n"
            "Holiday dates marked as expected are not final: say they are expected."
        ),
        "fallback_en": ("Sorry, I don't have information about that. "
                        "Please contact the {university} Human Resources (HR) department."),
        "fallback_ar": ("آسف، معنديش معلومات عن ده. "
                        "من فضلك تواصل مع إدارة الموارد البشرية (HR) في الجامعة."),
        "welcome": "Ask about leave, public holidays, contracts or resignation, or try one of these:",
        "placeholder": "Ask about leave, holidays, contracts, notice period...",
        "examples": [
            "How many days of annual leave do I get?",
            "How long is maternity leave?",
            "What are the official holidays this year?",
            "What is the notice period if I resign?",
        ],
        "skills": ["files", "images", "editor", "voice"],
        "max_answer_tokens": 400,
        "position": 2,
        "prompt_mode": "composed",
    },
    {
        "key": "internship_career",
        "name": "Internship & Career Assistant",
        "summary": "Internships, the career fair, CV review, interviews, skills and career paths",
        "subtitle": "{university} career information and general career advice",
        "description": (
            "Internships, the internship semester, the career fair and employers, CV and "
            "resume writing, CV review, interview preparation, job applications, LinkedIn, "
            "skills for a major and career paths. "
            "الانترنشيب، التدريب، معرض التوظيف، السي في، السيرة الذاتية، الانترفيو، الشغل، الوظايف."
        ),
        "audiences": ["student", "staff"],
        "answer_mode": "advice",
        "instructions": (
            "You help {university} students prepare for internships and jobs: career resources,\n"
            "internship requirements, the career fair, how to apply, CVs, interviews, skills for their\n"
            "major and career paths. When a student attaches a CV and asks for feedback, reply with\n"
            "these short sections: Strengths, Problems, Improved bullets (two or three of theirs,\n"
            "rewritten with action verbs and results), Skills to add, Next steps (three concrete actions).\n"
            "Only help with internships, jobs and careers; for other topics, say politely that other\n"
            "{university} assistants can help."
        ),
        "fallback_en": ("Sorry, I don't have information about that. "
                        "Please contact the {university} Career Center or your faculty for help."),
        "fallback_ar": ("آسف، معنديش معلومات عن ده. "
                        "من فضلك تواصل مع الكارير سنتر في الجامعة أو مع الكلية."),
        "welcome": "Ask about internships, the career fair, your CV or interviews, or try one of these:",
        "placeholder": "Ask about internships, CVs, interviews, career paths...",
        "examples": [
            "When is the next career fair?",
            "How do I find an internship?",
            "How do I prepare for an interview?",
            "What skills do I need as a computer science student?",
        ],
        "skills": ["files", "images", "cv", "editor", "voice"],  # cv only works with a trained CV model
        "max_answer_tokens": 1500,
        "position": 3,
        "prompt_mode": "composed",
    },
    {
        "key": "labs_research",
        "name": "Labs & Research Assistant",
        "summary": "Lab access, supervisors, equipment, research resources, campus offices",
        "subtitle": "Answers from official {university} documents",
        "description": (
            "Lab access, lab rooms and opening hours, lab supervisors, equipment and booking, "
            "research funding and grants, research resources, thesis support and publications. "
            "Where things are on campus: buildings, rooms and floors, offices (admission, "
            "student affairs, finance, academic coordinator), the library, the clinic, the gym, "
            "sports courts, the food court and parking. "
            "المعامل، الأجهزة، منحة البحث، البحث العلمي، الرسالة، النشر، فين المباني والأوض والمكاتب، "
            "شئون الطلبة، الادميشن، المكتبة، العيادة، الجيم، الباركينج."
        ),
        "audiences": ["student", "staff"],
        "answer_mode": "docs",
        "instructions": (
            "You help students and staff with questions about labs, research facilities, research\n"
            "funding, thesis support, and where to find campus buildings, rooms and offices."
        ),
        "fallback_en": ("Sorry, I don't have information about that. "
                        "Please contact the relevant office or department for help."),
        "fallback_ar": ("آسف، معنديش معلومات عن ده. "
                        "من فضلك تواصل مع المكتب أو القسم المختص للمساعدة."),
        "welcome": "Ask anything about {university} labs, rooms and offices, or try one of these:",
        "placeholder": "Ask about labs, offices, rooms, research funding...",
        "examples": [
            "Where is the AI lab?",
            "Where is the Admission Office?",
            "How do I pay my tuition fees?",
            "Where is the library?",
        ],
        "skills": ["files", "images", "editor", "map", "voice"],  # map only works with a campus map
        "max_answer_tokens": 400,
        "position": 4,
        "prompt_mode": "composed",
    },
]


def template(key: str) -> dict:
    """A ready-made assistant (for any university)."""
    return next(t for t in TEMPLATES if t["key"] == key)


def giu_agent(key: str) -> dict:
    """One of GIU's own four assistants, as its agents row has it."""
    return next(a for a in GIU_AGENTS if a["key"] == key)
