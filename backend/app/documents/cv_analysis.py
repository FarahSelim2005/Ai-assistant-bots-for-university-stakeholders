"""Check the CV model's CV ANALYSIS against the CV it wrote (CV model v6).

The model sometimes praises things the CV does not have (links, skill levels, numbers), gives
advice the CV does not need, and its rating is not always consistent. After each rewrite the
analysis is corrected in code:
- strengths the CV does not support are removed (profile links, skill levels, measurable
  results, a good range of skills with fewer than 6);
- "What I changed" notes the CV does not show are removed: action verbs (Arabic CVs or no
  bullets), "Added [placeholders] ..." (no "[" in the CV), "Fixed spelling mistakes." (no
  word of the original CV was corrected);
- "You have practical experience in more than one role." needs 2+ roles under EXPERIENCE;
- advice it does not need is removed: "Add 2-3 bullets about ..." when every role has its
  bullets, "Add more skills ..." when it lists 6 or more skills (and "Skills: a short list;
  add more." becomes "Skills: a good range."), "Say in your summary which role ..." when the
  summary already says it, "Keep personal details and hobbies out ..." unless "What I changed"
  says some were removed;
- "Section by section" lines are corrected: the Summary line when the target role is stated,
  the Experience line when there is no role yet ("no internship or job yet");
- missing advice is added: a LinkedIn link, more skills (fewer than 6), and one piece of advice
  about a first job when there is none (an internship, part-time job, project or volunteering
  role for a CV with nothing yet; an internship or part-time job when it has projects);
- "Rewrote your bullets to start with action verbs." is removed when there are no bullets;
- the Skills line says "a short list; add more." (fewer than 6 skills) or "a good range.";
- the Target length line is computed from the CV (years of full-time work, whatever the template);
- "Proofread your CV ..." is removed unless "What I changed" says spelling was fixed;
- "Write the start and end months for <role> ..." is removed unless that role's dates are only
  a duration ("2 years");
- the Summary line and its advice follow whether the summary names the role they want;
- "Your CV is still longer than the target length..." follows the PDF's real page count
  (check_length, called once the PDF is made);
- a list left empty gets a general line, so it never shows only its heading;
- the rating is computed again with a fixed rubric (rate_cv), between 1 and 10.
The rewritten CV itself is changed in five ways: the role line under the name keeps only the
job title (clean_role_line), roles are sorted newest first by start date (sort_roles), the
target-role placeholder goes when the summary already names the role (state_target_role),
roles that ended more than 10 years ago keep only their first bullet (condense_old_roles),
and degrees of the original CV that the model dropped are put back into EDUCATION
(restore_degrees). When the PDF is longer than the target length allows, fit_to_length
condenses it step by step (long extra lists on one line, then roles after the 3 newest and
projects after the first 3 to their first bullet). An academic CV (2+ publications and a research,
conferences or clinical rotations section) gets the academic target length.
Every change is logged in the backend terminal.
"""
import datetime
import difflib
import logging
import math
import re

import pymupdf

from app.documents.cv_file import ARABIC_LETTERS, blocks, cv_pdf, is_arabic, is_heading, is_one_page_target

log = logging.getLogger("uvicorn.error")

# The CV's section headings (English templates and Arabic CVs); any other heading is an
# extra section (certificates, courses, awards, publications, other sections).
SECTION_KINDS = {
    "summary": ("SUMMARY", "PROFILE", "ABOUT ME", "الملخص", "نبذة عني", "الملف الشخصي"),
    "education": ("EDUCATION", "التعليم"),
    "experience": ("EXPERIENCE", "WORK EXPERIENCE", "الخبرات العملية", "الخبرات", "الخبرة العملية"),
    "projects": ("PROJECTS", "المشاريع"),
    "activities": ("ACTIVITIES AND VOLUNTEERING", "ACTIVITIES", "VOLUNTEERING", "الأنشطة والتطوع", "الأنشطة", "التطوع"),
    "skills": ("SKILLS", "المهارات"),
    "languages": ("LANGUAGE", "LANGUAGES", "اللغات"),
    "references": ("REFERENCES", "المراجع"),
}
PLACEHOLDER = re.compile(r"^\[add [^\]]*\]$")             # a line that is only "[add ...]"
NO_DETAILS = "[add details about what you did]"
PHONE = re.compile(r"\+?\d[\d\s().-]{6,}\d")
PROFILE_LINK = re.compile(r"linkedin\.com|github\.com", re.IGNORECASE)
SKILL_LEVEL = re.compile(r"\([^(),]{1,25}\)")               # "Python (Basic)"
SKILL_GROUP = re.compile(r"^[^:]{1,30}:\s*\S.*[,·]")        # "Languages: Python, C++"

# Lines of the analysis
RATING = re.compile(r"^(?P<label>[^\n:]{0,40}:\s*)\d+(?:\.\d+)?\s*/\s*10\b.*$", re.MULTILINE)
WHAT_I_CHANGED = re.compile(r"^\W*(?:what i changed|ما غيرته|اللي غيرته)", re.IGNORECASE)
STRENGTHS = re.compile(r"^\W*(?:strengths|نقاط القوة|نقط القوة|المميزات|مميزات)", re.IGNORECASE)
TO_IMPROVE = re.compile(r"^\W*(?:most important to improve|أهم)", re.IGNORECASE)
LABEL = re.compile(r"^[^\s\-•*\d][^:\n]{0,50}:")            # "Section by section:", "Rating: ..."
ITEM = re.compile(r"^(?P<indent>\s*)(?:(?P<number>\d+)(?P<sep>[.)])|[-•*])\s*")
# What a strength is about
ABOUT_LINKS = re.compile(r"linkedin|github|لينكد|جيت ?هاب|\blinks?\b|روابط|لينكات", re.IGNORECASE)
ABOUT_LEVELS = re.compile(r"\blevels?\b|مستو", re.IGNORECASE)  # "show your level", "موضح مستواها"
ABOUT_NUMBERS = re.compile(r"measurable|quantif|numbers|metrics|أرقام|ارقام|قابلة للقياس|ملموسة", re.IGNORECASE)
# "You list a good range of skills." / "عندك مجموعة مهارات كويسة."
ABOUT_SKILL_RANGE = re.compile(r"good range of skills|مجموعة مهارات كويسة", re.IGNORECASE)
ABOUT_SEVERAL_ROLES = re.compile(r"experience in more than one role|خبرة عملية في أكتر من مكان", re.IGNORECASE)
# "What I changed" notes checked against the CV
ABOUT_PLACEHOLDERS = re.compile(r"placeholders", re.IGNORECASE)  # "Added [placeholders] ..." / "حطيت [placeholders] ..."
ABOUT_SPELLING_FIXED = re.compile(r"fixed spelling mistakes|صلحت الأخطاء الإملائية", re.IGNORECASE)
WORD = re.compile(r"[^\W\d_]{4,}")  # words of 4+ letters, for finding spelling corrections
ABOUT_LINKEDIN = re.compile(r"linkedin|لينكد", re.IGNORECASE)
# A "What I changed" note that is wrong for Arabic CVs (their bullets stay as written) and for
# CVs without experience or project bullets
ABOUT_ACTION_VERBS = re.compile(r"action verbs?", re.IGNORECASE)
# What an improvement is about
ABOUT_MISSING_BULLETS = re.compile(r"(?:add|ضيف)\s+2\s*[-–]\s*3\s+bullets", re.IGNORECASE)  # "Add 2-3 bullets about ..."
ABOUT_MORE_SKILLS = re.compile(r"add more skills|ضيف مهارات", re.IGNORECASE)
ABOUT_JOB = re.compile(r"internship or part-time job|تدريب أو شغل part-time", re.IGNORECASE)  # ADD_JOB
# The same advice for a CV with nothing yet: "Add an internship, part-time job, project or volunteering role"
ABOUT_FIRST_ROLE = re.compile(r"internship, part-time job, project or volunteering", re.IGNORECASE)
ABOUT_TARGET_ROLE = re.compile(r"which role or internship you are looking for|الوظيفة أو التدريب اللي بتدور عليه", re.IGNORECASE)
ABOUT_PERSONAL_DETAILS = re.compile(r"personal details and hobbies out|البيانات الشخصية والهوايات برا", re.IGNORECASE)
# A "What I changed" note saying personal details or hobbies were taken out
PERSONAL_DETAILS = re.compile(r"personal|hobb|interests|date of birth|nationality|marital|military|"
                              r"البيانات الشخصية|الهوايات|هوايات|تاريخ الميلاد|الجنسية|الحالة الاجتماعية|التجنيد",
                              re.IGNORECASE)
NO_TARGET_ROLE ="[add the role or internship you are looking for]"
# A summary that says which role they want ("Looking for a senior marketing role.")
TARGET_ROLE_PHRASE = re.compile(r"\b(?:seeking|looking for|interested in)\b[^.\n]*\b(?:role|position|internship)s?\b"
                                r"|أسعى|بدور|عايز", re.IGNORECASE)
ADD_TARGET_ROLE = {"en": "Say in your summary which role or internship you are looking for.",
                   "ar": "اكتب في الملخص الوظيفة أو التدريب اللي بتدور عليه."}
# "Write the start and end months for <role> instead of only the duration.": only for a role
# whose dates are a duration ("2 years", "3 months") without any year
ABOUT_DATES = re.compile(r"write the start and end months for (?P<role>.+?) instead of only the duration"
                         r"|اكتب شهر البداية والنهاية لـ ?(?P<role_ar>.+?) بدل المدة", re.IGNORECASE)
DURATION = re.compile(r"\b\d+\s*(?:months?|years?|weeks?)\b|\d+\s*(?:شهر|شهور|أشهر|سنة|سنين|سنوات)", re.IGNORECASE)
ABOUT_PROOFREAD = re.compile(r"proofread|راجع الـ CV كويس", re.IGNORECASE)
FIXED_SPELLING = re.compile(r"fixed spelling|إملائ", re.IGNORECASE)  # in "What I changed"
# Years of experience (London / Modern templates) -> the length the CV should have
YEAR = re.compile(r"(?<!\d)(?:19|20)\d\d(?!\d)")
PRESENT = re.compile(r"\bpresent\b|\bnow\b|الآن|حاليا|حاليًا", re.IGNORECASE)
# Start dates of roles, for sorting them newest first
MONTHS = {name: number for number, names in enumerate(
    [("jan", "يناير"), ("feb", "فبراير"), ("mar", "مارس"), ("apr", "أبريل", "ابريل"), ("may", "مايو"), ("jun", "يونيو"),
     ("jul", "يوليو"), ("aug", "أغسطس", "اغسطس"), ("sep", "سبتمبر"), ("oct", "أكتوبر", "اكتوبر"), ("nov", "نوفمبر"),
     ("dec", "ديسمبر")], start=1) for name in names}
MONTH_DATE = re.compile(r"(?P<month>\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?|يناير|فبراير|مارس|أبريل|ابريل"
                        r"|مايو|يونيو|يوليو|أغسطس|اغسطس|سبتمبر|أكتوبر|اكتوبر|نوفمبر|ديسمبر)\s+(?P<year>(?:19|20)\d\d)", re.IGNORECASE)
SEASONS = {"winter": 1, "spring": 3, "summer": 6, "fall": 9, "autumn": 9, "شتاء": 1, "ربيع": 3, "صيف": 6, "خريف": 9}
SEASON_DATE = re.compile(r"(?P<season>\b(?:winter|spring|summer|fall|autumn)\b|شتاء|ربيع|صيف|خريف)\s+(?P<year>(?:19|20)\d\d)",
                         re.IGNORECASE)
ACADEMIC_YEAR = re.compile(r"(?P<year>(?:19|20)\d\d)/\d\d(?!\d)")  # "2021/22"
OLD_ROLE_YEARS = 10  # roles that ended more than this many years ago keep only their first bullet
TARGET_LENGTHS = [  # (up to this many years, English, Arabic)
    (0, "1 page (student / fresh graduate)", "صفحة واحدة (طالب / خريج جديد)"),
    (5, "1-2 pages (1-5 years of experience)", "من صفحة لصفحتين (من سنة لـ 5 سنين خبرة)"),
    (10, "about 2 pages (5-10 years of experience)", "حوالي صفحتين (من 5 لـ 10 سنين خبرة)"),
    (None, "2-3 pages (more than 10 years of experience)", "من صفحتين لـ 3 صفحات (أكتر من 10 سنين خبرة)"),
]
# Most pages for each target length (the upper limit); an academic CV may be longer
PAGE_LIMITS = [(re.compile(r"2-3 pages|من صفحتين لـ 3"), 3), (re.compile(r"1-2 pages|من صفحة لصفحتين"), 2),
               (re.compile(r"about 2 pages|حوالي صفحتين"), 2), (re.compile(r"1 page|صفحة واحدة"), 1)]
ACADEMIC = re.compile(r"academic|أكاديمي", re.IGNORECASE)
# An academic CV: 2+ publications and a research, conferences or clinical rotations section
ACADEMIC_LENGTH = {"en": "academic CV: longer is fine because of your research and publications",
                   "ar": "CV أكاديمي: طوله مقبول عشان الأبحاث والمنشورات"}
PUBLICATIONS_HEADINGS = ("PUBLICATIONS", "المنشورات")
RESEARCH_HEADINGS = ("RESEARCH", "CONFERENCES", "CLINICAL ROTATIONS")
PUBLICATIONS_ADD_MORE = re.compile(r"^[^\w\n]*(?:Publications|المنشورات):.*(?:add more|ضيف).*\n?", re.MULTILINE | re.IGNORECASE)
EXTRAS_LINE = re.compile(r"^[^\w\n]*Extras\b", re.MULTILINE | re.IGNORECASE)
EXTRAS_KEEP = "- Extras (certificates, courses, awards, publications...): good additions; keep them."
SECTION_BY_SECTION = re.compile(r"^\W*(?:section by section|تحليل كل جزء|تفاصيل كل قسم)", re.IGNORECASE)
# Degrees the model dropped from the CV (test 11 lost its whole EDUCATION section)
DEGREE = re.compile(r"(?<![\w.])(?:Ph\.?\s?D\.?|Master(?:'s)?|M\.?\s?Sc\.?|MBA|Bachelor(?:'s)?|B\.?\s?Sc\.?|BBA|B\.?\s?Com\.?"
                    r"|B\.?\s?Pharm\.?|B\.?\s?Arch\.?|B\.?A\.?|LL\.?\s?B\.?|MBBCh|Diploma)(?=[\s,.\-–(]|$)")
UNIVERSITY = re.compile(r"\bUniv\w*|College|Institute|Academy|School|Faculty|جامعة|كلية|معهد", re.IGNORECASE)  # also "Univeristy"
STUDY_YEARS = re.compile(r"(?:19|20)\d\d(?:/\d\d)?\s*[-–]\s*(?:(?:19|20)\d\d(?:/\d\d)?|present|now|expected\s+(?:19|20)\d\d)"
                         r"|expected\s+(?:19|20)\d\d|(?:19|20)\d\d", re.IGNORECASE)
ORIGINAL_HEADING = re.compile(r"^\W*(education|academic background|qualifications|(?:work )?experience|internships|skills|"
                              r"summary|profile|objective|about me|projects|languages|certifications|courses|research|"
                              r"publications|conferences|awards|activities|volunteering|memberships|references|"
                              r"التعليم|الخبرات|المهارات|الملخص|اللغات|المشاريع)\W*$", re.IGNORECASE)
EDUCATION_HEADING = {"en": "EDUCATION", "ar": "التعليم"}
EDUCATION_LINE = {"en": re.compile(r"^(?P<prefix>[^\w\n]*)Education:.*$", re.MULTILINE | re.IGNORECASE),
                  "ar": re.compile(r"^(?P<prefix>[^\w\n]*)التعليم:.*$", re.MULTILINE)}
DEGREES_ADDED = {"en": "Education: some degrees were missing from the rewrite; they were added back from your CV.",
                 "ar": "التعليم: كانت فيه شهادات ناقصة في الـ CV الجديد، ورجعناها من الـ CV بتاعك."}
ABOUT_TOO_LONG = re.compile(r"your cv is still longer than the target length|الـ CV لسه أطول من الطول المناسب", re.IGNORECASE)
TOO_LONG = {"en": "Your CV is still longer than the target length: remove the items least related to the job you are applying for.",
            "ar": "الـ CV لسه أطول من الطول المناسب: شيل الحاجات اللي مالهاش علاقة بالوظيفة اللي بتقدم عليها."}
INTERNSHIP = re.compile(r"\bintern(?:ship)?s?\b|\btrainee\b|متدرب|تدريب", re.IGNORECASE)  # not full-time work
# The role line under the name: only the job title (or "<major> Student"); cut at a comma,
# "|", " - ", "(" or " at " (dates or a company the model added)
ROLE_LINE_EXTRA = re.compile(r"\s*(?:,|،|\||\(|\s[-–—]\s|\sat\s|\s@\s).*$", re.IGNORECASE)
CONTACT = re.compile(r"@|https?://|www\.|linkedin|github|\+?\d[\d\s]{7,}", re.IGNORECASE)
TARGET_LINE = re.compile(r"^(?P<prefix>[^\w\n]*(?:Target length|الطول[^:\n]{0,20}):[ \t]*).*$", re.MULTILINE | re.IGNORECASE)
CONDENSED = {"en": "Condensed older roles and extra projects to their main point to keep the CV focused.",
             "ar": "اختصرت الأدوار القديمة والمشاريع الزيادة لأهم نقطة فيها عشان الـ CV يفضل مركز."}
ABOUT_CONDENSED = re.compile(r"condensed|اختصرت", re.IGNORECASE)
GROUPED = {"en": "Grouped long lists into one line to save space.", "ar": "جمعت القوايم الطويلة في سطر واحد عشان المساحة."}
ABOUT_GROUPED = re.compile(r"grouped long lists|جمعت القوايم", re.IGNORECASE)
KEEP_AS_LIST = re.compile(r"CERTIF|AWARD|PUBLICATION|الشهادات|الجوائز|المنشورات", re.IGNORECASE)  # never one line
CHANGED_LABEL = {"en": "What I changed:", "ar": "ما غيرته:"}
MAX_CHANGES = 5
# "Section by section" lines (prefix: "- " or "1. ")
SKILLS_LINE = {"en": re.compile(r"^(?P<prefix>[^\w\n]*)Skills:.*$", re.MULTILINE | re.IGNORECASE),
               "ar": re.compile(r"^(?P<prefix>[^\w\n]*)المهارات:.*$", re.MULTILINE)}
FEW_SKILLS = {"en": "Skills: a short list; add more.", "ar": "المهارات: قليلة، ضيف أكتر."}
MANY_SKILLS = {"en": "Skills: a good range.", "ar": "المهارات: مجموعة كويسة."}
SUMMARY_LINE = re.compile(r"^(?P<prefix>[^\w\n]*)Summary:.*$", re.MULTILINE | re.IGNORECASE)
EXPERIENCE_LINE = {"en": re.compile(r"^(?P<prefix>[^\w\n]*)(?:Work )?Experience:.*$", re.MULTILINE | re.IGNORECASE),
                   "ar": re.compile(r"^(?P<prefix>[^\w\n]*)(?:الخبرات|الخبرة)(?: العملية)?:.*$", re.MULTILINE)}
NO_JOB_YET = {"en": "Experience: no internship or job yet.", "ar": "الخبرات: لسه مفيش تدريب أو شغل."}
ADD_JOB = {"en": "Add an internship or part-time job when you can.", "ar": "ضيف تدريب أو شغل part-time لما تقدر."}
ADD_FIRST_ROLE = {"en": "Add an internship, part-time job, project or volunteering role.", "ar": ADD_JOB["ar"]}
ADD_MORE_SKILLS = {"en": "Add more skills that match the jobs you want.", "ar": "ضيف مهارات أكتر تناسب الشغل اللي عايزه."}
ADD_LINKEDIN = {"en": "Add a link to your LinkedIn profile.", "ar": "ضيف لينك الـ LinkedIn بتاعك."}
# Added when a list is left empty
NO_IMPROVEMENTS = {"en": "Tailor your summary and skills to each job you apply for.",
                   "ar": "عدل الملخص والمهارات حسب كل وظيفة بتقدم عليها."}
NO_STRENGTHS = {"en": "You have a clear starting point: your education and skills.",
                "ar": "عندك بداية واضحة: التعليم والمهارات."}
# Lines the model sometimes writes before the CV
MODEL_TAG = re.compile(r"^\s*</?(?:tool_call|think)>\s*$")
RATING_LABEL = {"en": "Rating:", "ar": "التقييم:"}
IMPROVE_LABEL = {"en": "Most important to improve:", "ar": "أهم حاجات محتاجة تتحسن:"}
VERDICTS = [(8, "Strong CV", "CV قوي"), (6, "Good CV with a few gaps", "CV كويس بس فيه شوية حاجات ناقصة"),
            (4, "Needs work", "محتاج شغل"), (0, "Needs a lot of work", "محتاج شغل كتير")]


def cv_sections(cv: str) -> tuple[list[str], dict[str, list[tuple[str, str]]]]:
    """(the lines before the first heading: name, role, contact; each section's lines)."""
    top, sections, current = [], {}, None
    for kind, text in blocks(cv):
        if kind == "heading":
            current = next((k for k, names in SECTION_KINDS.items() if text.upper() in names), "extras")
            sections.setdefault(current, [])
        elif current is None:
            top.append(text)
        else:
            sections[current].append((kind, text))
    return top, sections


def real(lines: list[tuple[str, str]]) -> list[str]:
    """The lines that are not only a placeholder."""
    return [text for _, text in lines if not PLACEHOLDER.match(text)]


def roles_with_bullets(lines: list[tuple[str, str]]) -> tuple[int, bool]:
    """(how many roles have real bullets, whether there is any role at all). A role's bullets
    are the "- " lines that follow its title, company and date lines."""
    groups, current, roles = [], None, False
    for kind, text in lines:
        if kind == "bullet":
            if current is None:
                current = []
                groups.append(current)
            current.append(text)
        else:
            current = None
            roles = roles or not PLACEHOLDER.match(text)
    return sum(any(bullet != NO_DETAILS for bullet in group) for group in groups), roles


def skill_count(lines: list[tuple[str, str]]) -> int:
    """Skills listed one per line, on one line ("a, b · c") or in groups ("Tools: a, b")."""
    count = 0
    for text in real(lines):
        text = SKILL_LEVEL.sub("", text.split(":", 1)[-1])
        count += len([skill for skill in re.split(r"[,،·;|]", text) if skill.strip()])
    return count


def rate_cv(cv: str) -> float:
    """The CV's score out of 10, from what it contains (the rubric of the CV ANALYSIS)."""
    top, sections = cv_sections(cv)
    get = lambda kind: sections.get(kind, [])
    score = 1 if PHONE.search(" ".join(top)) else 0.5
    score += 1 if PROFILE_LINK.search(cv) else 0
    score += 0.5 if real(get("summary")) else 0
    score += 0.5 if "[add the role" not in cv else 0
    education = " ".join(text for _, text in get("education"))
    score += 0.5 if "[add your study dates]" in education else 1 if YEAR.search(education) else 0
    with_bullets, roles = roles_with_bullets(get("experience"))
    projects_or_activities = bool(real(get("projects")) or real(get("activities")))
    score += (2 if with_bullets >= 2 else 1.5 if with_bullets == 1 else 1 if roles
              else 0.5 if projects_or_activities else 0)
    score += 1 if numbers_in_bullets(sections) else 0
    score += 1 if projects_or_activities else 0
    skills = skill_count(get("skills"))
    score += 1 if skills >= 6 else 0.5 if skills >= 3 else 0
    score += 0.5 if real(get("languages")) else 0
    score += 0.5 if real(get("extras")) else 0
    score -= 0.5 if NO_DETAILS in cv else 0
    return score


def numbers_in_bullets(sections: dict) -> bool:
    """A measurable result: a digit in an experience or project bullet."""
    return any(kind == "bullet" and not PLACEHOLDER.match(text) and re.search(r"\d", text)
               for name in ("experience", "projects") for kind, text in sections.get(name, []))


def has_bullets(sections: dict) -> bool:
    """A real (not "[add ...]") bullet under EXPERIENCE or PROJECTS."""
    return any(kind == "bullet" and not PLACEHOLDER.match(text)
               for name in ("experience", "projects") for kind, text in sections.get(name, []))


def strip_model_tags(answer: str) -> str:
    """The answer without "<think>", "</think>", "<tool_call>", "</tool_call>" lines at its start."""
    lines = answer.lstrip().splitlines()
    start = 0
    while start < len(lines) and (MODEL_TAG.match(lines[start]) or not lines[start].strip()):
        start += 1
    if start:
        log.warning("CV answer: %d tag line(s) removed from the start", sum(bool(MODEL_TAG.match(l)) for l in lines[:start]))
    return "\n".join(lines[start:])


def experience_roles(cv: str, kind: str = "experience") -> list[dict]:
    """The roles under EXPERIENCE (or the projects, with kind="projects"): each {"text": its title / company / date lines, "bullets":
    the line numbers of its "- " bullets, "lines": all its line numbers, "start" and "end":
    years (None if no year)}."""
    roles, section, current = [], None, None
    for number, raw in enumerate(cv.splitlines()):
        line = raw.strip()
        if not line:
            continue
        if is_heading(line) and ":" not in line:
            section = next((k for k, names in SECTION_KINDS.items() if line.rstrip(":").upper() in names), "extras")
            current = None
        elif section != kind:
            continue
        elif line.startswith(("- ", "• ", "* ")):
            if current is None:
                current = {"text": [], "bullets": [], "lines": []}
                roles.append(current)
            current["bullets"].append(number)
            current["lines"].append(number)
        else:
            if current is None or current["bullets"]:
                current = {"text": [], "bullets": [], "lines": []}
                roles.append(current)
            current["text"].append(line)
            current["lines"].append(number)
    this_year = datetime.date.today().year
    for role in roles:
        dates = " ".join(role["text"])
        years = [int(y) for y in YEAR.findall(dates)]
        role["start"] = min(years) if years else None
        role["end"] = this_year if PRESENT.search(dates) else max(years) if years else None
    return roles


def start_date(text: str) -> tuple[int, int] | None:
    """(year, month) of the first date in a role's lines: "Oct 2024" -> (2024, 10),
    "Spring 2025" -> (2025, 3), "2021/22" -> (2021, 9), "2019" -> (2019, 1); None for a
    duration only ("3 months")."""
    found = []  # (position, priority, (year, month)): the first date is the start
    for match in MONTH_DATE.finditer(text):
        found.append((match.start(), 0, (int(match["year"]), MONTHS[match["month"].lower()[:3]
                                                                    if match["month"].isascii() else match["month"]])))
    for match in SEASON_DATE.finditer(text):
        found.append((match.start(), 0, (int(match["year"]), SEASONS[match["season"].lower()])))
    for match in ACADEMIC_YEAR.finditer(text):
        found.append((match.start(), 1, (int(match["year"]), 9)))
    for match in YEAR.finditer(text):
        found.append((match.start(), 2, (int(match.group()), 1)))
    return min(found)[2] if found else None


def end_date(text: str) -> tuple[int, int] | None:
    """(year, month) of the last date in a role's lines: "Present" -> today, "Feb 2025" ->
    (2025, 2), "2024/25" -> (2025, 6), "2021" -> (2021, 12); None for a duration only."""
    if PRESENT.search(text):
        today = datetime.date.today()
        return today.year, today.month
    # (where it ends, priority, (year, month)): the last date is the end; the year of "Feb 2025"
    # ends at the same place, so the month (higher priority) wins
    found = []
    for match in MONTH_DATE.finditer(text):
        found.append((match.end(), 2, (int(match["year"]), MONTHS[match["month"].lower()[:3]
                                                                  if match["month"].isascii() else match["month"]])))
    for match in SEASON_DATE.finditer(text):
        found.append((match.end(), 2, (int(match["year"]), SEASONS[match["season"].lower()])))
    for match in ACADEMIC_YEAR.finditer(text):
        found.append((match.end(), 1, (int(match["year"]) + 1, 6)))
    for match in YEAR.finditer(text):
        found.append((match.end(), 0, (int(match.group()), 12)))
    return max(found)[2] if found else None


def sort_roles(cv: str) -> str:
    """The CV with its roles under EXPERIENCE newest first by start date: roles until
    "Present" first, roles with only a duration ("3 months") last in their order. Each
    role keeps its lines together."""
    roles = experience_roles(cv)
    if len(roles) < 2:
        return cv

    def key(item):
        order, role = item
        text = " ".join(role["text"])
        start = start_date(text)
        if start is None:
            return (2, 0, order)  # a duration only: last, as they were
        return (0 if PRESENT.search(text) else 1, -(start[0] * 12 + start[1]), order)

    ordered = [role for _, role in sorted(enumerate(roles), key=key)]
    if ordered == roles:
        return cv
    lines = cv.splitlines()
    first, last = roles[0]["lines"][0], roles[-1]["lines"][-1]
    gap = [""] if any(not lines[n].strip() for n in range(first, last + 1)) else []  # keep blank lines between roles
    block = [line for i, role in enumerate(ordered) for line in ((gap if i else []) + [lines[n] for n in role["lines"]])]
    log.info("CV: roles sorted newest first: %s", [" | ".join(role["text"]) for role in ordered])
    return "\n".join(lines[:first] + block + lines[last + 1:])


def state_target_role(cv: str) -> str:
    """The CV without the "[add the role or internship you are looking for]" placeholder
    when its summary already names the role(s) it wants ("interested in public relations
    and digital content roles")."""
    _, sections = cv_sections(cv)
    summary = " ".join(text for _, text in sections.get("summary", []))
    if NO_TARGET_ROLE not in summary or not TARGET_ROLE_PHRASE.search(summary.replace(NO_TARGET_ROLE, "")):
        return cv
    lines, inside = cv.splitlines(), False
    for number, line in enumerate(lines):
        if is_heading(line.strip()) and ":" not in line:
            inside = line_kind(line) == "summary"
        elif inside and NO_TARGET_ROLE in line:
            lines[number] = re.sub(r"\s{2,}", " ", line.replace(NO_TARGET_ROLE, "")).rstrip()
    log.info("CV: target-role placeholder removed (the summary names the role)")
    return "\n".join(line for number, line in enumerate(lines)
                     if line.strip() or not cv.splitlines()[number].strip())  # a line that held only it goes


def is_academic(cv: str) -> bool:
    """2+ publications and a RESEARCH, CONFERENCES or CLINICAL ROTATIONS section."""
    heading, publications, research = "", 0, False
    for kind, text in blocks(cv):
        if kind == "heading":
            heading = text.upper()
            research = research or heading in RESEARCH_HEADINGS
        elif heading in PUBLICATIONS_HEADINGS and not PLACEHOLDER.match(text):
            publications += 1
    return publications >= 2 and research


def target_length(cv: str, language: str) -> str:
    """The length the CV should have: longer for an academic CV, otherwise by the years of
    full-time work only (whatever the template): from the first job's start to the last
    job's end. Internships do not count, so students and fresh graduates (under a year)
    get 1 page."""
    if is_academic(cv):
        return ACADEMIC_LENGTH[language]
    texts = [" ".join(role["text"]) for role in experience_roles(cv)]
    spans = [(start_date(text), end_date(text)) for text in texts if not INTERNSHIP.search(text)]
    spans = [(start, end) for start, end in spans if start and end]
    months = (max(end[0] * 12 + end[1] for _, end in spans) - min(start[0] * 12 + start[1] for start, _ in spans)
              if spans else 0)
    years = 0 if months < 12 else round(months / 12)  # Oct 2024 - Feb 2025 is not a year
    _, english, arabic = next(level for level in TARGET_LENGTHS if level[0] is None or years <= level[0])
    return english if language == "en" else arabic


def clean_role_line(cv: str) -> str:
    """The CV with the role line under the name cut to the job title: "Marketing Specialist,
    Jan 2023 - Present" -> "Marketing Specialist". In the London template the role follows
    the name on the same line ("Name, Role")."""
    lines = cv.splitlines()
    numbers = [n for n, line in enumerate(lines) if line.strip() and not line.startswith("Template:")]
    if len(numbers) < 2:
        return cv
    name_number, next_number = numbers[0], numbers[1]
    if cv.lower().startswith("template: london") and "," in lines[name_number]:
        name, _, role = lines[name_number].partition(",")
        title = ROLE_LINE_EXTRA.sub("", role.strip())
        new = f"{name}, {title}" if title else name
        number = name_number
    else:
        role = lines[next_number].strip()
        if is_heading(role) or CONTACT.search(role):
            return cv  # no role line
        new = ROLE_LINE_EXTRA.sub("", role) or role
        number = next_number
    if new.strip() == lines[number].strip():
        return cv
    log.info("CV: role line %r -> %r", lines[number].strip(), new.strip())
    lines[number] = new
    return "\n".join(lines)


def original_degrees(original: str) -> list[dict]:
    """The degrees of the CV the user sent: {"degree", "university", "years"} from each
    degree line (PhD, B.Sc., Bachelor ...) and the line after it. Only the Education
    section is read when there is one ("Scrum Master" elsewhere is not a degree)."""
    lines = [re.sub(r"^\w(?: \w)+$", lambda m: m.group().replace(" ", ""), line.strip())  # "E D U C A T I O N"
             for line in original.splitlines()]
    start = next((n for n, line in enumerate(lines) if ORIGINAL_HEADING.match(line)
                  and ORIGINAL_HEADING.match(line)[1].lower() in ("education", "academic background", "qualifications", "التعليم")), None)
    if start is not None:
        end = next((n for n in range(start + 1, len(lines)) if ORIGINAL_HEADING.match(lines[n])), len(lines))
        lines = lines[start + 1:end]
    degrees = []
    for number, line in enumerate(lines):
        if not DEGREE.search(line):
            continue
        nearby = [line] + [next_line for next_line in lines[number + 1:number + 3] if next_line and not DEGREE.search(next_line)][:2]
        parts = [part.strip(" -•*") for text in nearby for part in re.split(r"\s+[-–—|]\s+|,\s*", text)]
        degree = next(part for part in parts if DEGREE.search(part))
        university = next((part for part in parts if UNIVERSITY.search(part) and part != degree), "")
        years = next((match.group() for text in nearby if (match := STUDY_YEARS.search(text))), "")
        degrees.append({"degree": degree, "university": university, "years": years})
    return degrees


def restore_degrees(cv: str, original: str) -> tuple[str, bool]:
    """The CV with the degrees of the original CV that the model dropped put back into
    EDUCATION (created if missing), in the template's format, newest first; and whether
    any was missing. A degree counts as present when its name is in the CV (ignoring
    case, spaces and dots: "BSc" = "B.Sc.")."""
    squash = lambda text: re.sub(r"[\W_]+", "", text.lower())
    missing = [d for d in original_degrees(original) if squash(d["degree"]) not in squash(cv)]
    if not missing:
        return cv, False
    last_year = lambda d: 9999 if re.search(r"present|now|expected", d["years"], re.I) else max(
        (int(y) for y in YEAR.findall(d["years"])), default=0)
    missing.sort(key=last_year, reverse=True)
    template = cv.splitlines()[0].partition(":")[2].strip().lower() if cv.startswith("Template:") else "student"

    def entry(d):  # the degree in the template's format
        if template == "london":
            return [d["years"], " - ".join(p for p in (d["degree"], d["university"]) if p)]
        if template == "modern":
            return [d["degree"], ", ".join(p for p in (d["university"], d["years"]) if p)]
        return [", ".join(p for p in (d["university"].upper(), d["years"]) if p), d["degree"]]

    lines = cv.splitlines()
    headings = [n for n, line in enumerate(lines) if is_heading(line.strip()) and ":" not in line]
    education = next((n for n in headings if line_kind(lines[n]) == "education"), None)
    if education is None:  # Student: before EXPERIENCE; London / Modern: before SKILLS; else at the end
        order = ("experience", "skills") if template not in ("london", "modern") else ("skills",)
        before = next((n for kind in order for n in headings if line_kind(lines[n]) == kind), len(lines))
        new = [EDUCATION_HEADING["ar" if is_arabic(cv) else "en"], *(l for d in missing for l in entry(d) if l), ""]
        lines[before:before] = new if before < len(lines) else ["", *new]
    else:
        end = next((n for n in headings if n > education), len(lines))
        # a placeholder-only degree line ("[add your degree] – [add your university]") goes
        section = [line for line in lines[education + 1:end]
                   if not ("[add" in line and not re.sub(r"\[[^\]]*\]|[\W_]", "", line))]
        newest_there = max((int(y) for y in YEAR.findall(" ".join(section))), default=0)
        newer = [l for d in missing if last_year(d) >= newest_there for l in entry(d) if l]
        older = [l for d in missing if last_year(d) < newest_there for l in entry(d) if l]
        while section and not section[-1].strip():
            section.pop()
        lines[education + 1:end] = newer + section + older + [""]
    for d in missing:
        log.warning("CV: degree missing from the rewrite, added back: %s", d)
    return "\n".join(lines), True


def line_kind(heading: str) -> str:
    """The section kind of a heading line ("EDUCATION" -> "education")."""
    return next((k for k, names in SECTION_KINDS.items() if heading.strip().rstrip(":").upper() in names), "extras")


def condense_old_roles(cv: str) -> tuple[str, bool]:
    """The CV with roles that ended more than 10 years ago cut to their first bullet, and
    whether anything was cut."""
    this_year = datetime.date.today().year
    drop = set()
    for role in experience_roles(cv):
        if role["end"] is not None and this_year - role["end"] > OLD_ROLE_YEARS and len(role["bullets"]) > 1:
            drop.update(role["bullets"][1:])
            log.info("CV: older role %r (ended %s) cut to its first bullet", " | ".join(role["text"]), role["end"])
    if not drop:
        return cv, False
    return "\n".join(line for number, line in enumerate(cv.splitlines()) if number not in drop), True


def dates_advice_not_needed(improvements: str, cv: str) -> list[re.Pattern]:
    """The "Write the start and end months for <role> ..." advice to remove: <role> is not
    a role of the CV whose dates are only a duration (it has real dates, or is not found)."""
    duration_only = [" ".join(role["text"]).lower() for role in experience_roles(cv)
                     if role["start"] is None and DURATION.search(" ".join(role["text"]))]
    patterns = []
    for match in ABOUT_DATES.finditer(improvements):
        role = (match["role"] or match["role_ar"]).strip().lower()
        if not any(role in text for text in duration_only):
            patterns.append(re.compile(re.escape(match.group())))
    return patterns


def add_change(lines: list[str], note: str, language: str, already: re.Pattern = ABOUT_CONDENSED) -> list[str]:
    """Add `note` to "What I changed" unless a note there matches `already` (at most 5
    items: it replaces the last one when full)."""
    start = next((i for i, line in enumerate(lines) if WHAT_I_CHANGED.match(line)), None)
    if start is None:
        log.info("CV analysis: 'What I changed' added with %r", note)
        return lines + ["", CHANGED_LABEL[language], f"- {note}"]
    end = block_end(lines, start)
    if already.search("\n".join(lines[start:end])):
        return lines
    items = [i for i in range(start + 1, end) if ITEM.match(lines[i])]
    if len(items) >= MAX_CHANGES:
        log.info("CV analysis: 'What I changed' full, %r replaced by %r", lines[items[-1]].strip(), note)
        return lines[:items[-1]] + [f"- {note}"] + lines[items[-1] + 1:]
    log.info("CV analysis: change added: %r", note)
    return lines[:end] + [f"- {note}"] + lines[end:]


def spelling_corrected(original: str, cv: str) -> bool:
    """A word of the original CV was really corrected: it is not in the rewritten CV, but a
    close match is ("Univeristy" -> "University"). A word that only gained or lost an ending
    ("languages" -> "language", the Student heading) is not a spelling correction."""
    cv_words = {word.lower() for word in WORD.findall(cv)}
    for word in {word.lower() for word in WORD.findall(original)} - cv_words:
        for match in difflib.get_close_matches(word, cv_words, n=3, cutoff=0.8):
            if not (match.startswith(word) or word.startswith(match)):
                log.info("CV: spelling corrected: %r -> %r", word, match)
                return True
    return False


def check_analysis(analysis: str, cv: str, condensed: bool = False, original: str | None = None,
                   degrees_added: bool = False) -> str:
    """The analysis made to match the CV: strengths and advice the CV does not support are
    removed, missing advice (LinkedIn, a first job) is added, and the rating is computed
    from the CV. `condensed`: older roles were cut (condense_old_roles), noted in "What I
    changed". `original`: the CV as the user sent it, to check "Fixed spelling mistakes."
    (not checked without it). `degrees_added`: the model had dropped degrees
    (restore_degrees), so the Education line must not say it is complete. Every change
    is logged."""
    _, sections = cv_sections(cv)
    language = "ar" if ARABIC_LETTERS.search(analysis) else "en"
    summary = " ".join(real(sections.get("summary", [])))
    role_stated = NO_TARGET_ROLE not in cv and bool(TARGET_ROLE_PHRASE.search(summary))
    skills = [text for _, text in sections.get("skills", [])]
    many_skills = skill_count(sections.get("skills", [])) >= 6
    _, has_job = roles_with_bullets(sections.get("experience", []))
    unsupported = []
    if not PROFILE_LINK.search(cv):
        unsupported.append(ABOUT_LINKS)
    if not any(SKILL_LEVEL.search(s) or SKILL_GROUP.match(s) for s in skills):
        unsupported.append(ABOUT_LEVELS)
    if not numbers_in_bullets(sections):
        unsupported.append(ABOUT_NUMBERS)
    if not many_skills:
        unsupported.append(ABOUT_SKILL_RANGE)
    roles = [role for role in experience_roles(cv) if any(not PLACEHOLDER.match(t) for t in role["text"])]
    if len(roles) < 2:
        unsupported.append(ABOUT_SEVERAL_ROLES)
    spelling_fixed = original is None or spelling_corrected(original, cv)
    not_made = []  # "What I changed" notes the CV does not show
    if "[" not in cv:
        not_made.append(ABOUT_PLACEHOLDERS)
    if not spelling_fixed:
        not_made.append(ABOUT_SPELLING_FIXED)
    if is_arabic(cv) or not has_bullets(sections):  # bullets kept as written, or no bullets at all
        not_made.append(ABOUT_ACTION_VERBS)
    not_needed = []  # advice for something the CV already has
    if NO_DETAILS not in cv:
        not_needed.append(ABOUT_MISSING_BULLETS)  # every role already has its bullets
    if many_skills:
        not_needed.append(ABOUT_MORE_SKILLS)
    if role_stated:
        not_needed.append(ABOUT_TARGET_ROLE)  # the summary already says what they are looking for
    changed = list_text(analysis.splitlines(), WHAT_I_CHANGED)
    if not PERSONAL_DETAILS.search(changed):
        not_needed.append(ABOUT_PERSONAL_DETAILS)  # the CV had none to take out
    if not (FIXED_SPELLING.search(changed) and spelling_fixed):
        not_needed.append(ABOUT_PROOFREAD)  # no spelling mistakes were fixed
    not_needed += dates_advice_not_needed(list_text(analysis.splitlines(), TO_IMPROVE), cv)
    # No job yet: one piece of advice about it, not two. With projects or activities: "Add an
    # internship or part-time job when you can."; with nothing: "Add an internship, part-time
    # job, project or volunteering role."
    # (Arabic has one sentence for both: ADD_FIRST_ROLE["ar"] is ADD_JOB["ar"].)
    has_projects = bool(real(sections.get("projects", [])) or real(sections.get("activities", [])))
    first_role = ABOUT_FIRST_ROLE if language == "en" else ABOUT_JOB  # the advice for a CV with nothing yet
    if not has_job and has_projects:
        not_needed.append(ABOUT_FIRST_ROLE)
    elif not has_job and language == "en":
        not_needed.append(ABOUT_JOB)
    lines = analysis.splitlines()
    lines = remove_items(lines, WHAT_I_CHANGED, not_made, "changes not made to this CV")
    lines = remove_items(lines, STRENGTHS, unsupported, "strengths not supported by the CV")
    lines = remove_items(lines, TO_IMPROVE, not_needed, "advice the CV does not need")
    if condensed:
        lines = add_change(lines, CONDENSED[language], language)
    if not role_stated:
        lines = add_to_improve(lines, ADD_TARGET_ROLE[language], language, ABOUT_TARGET_ROLE)
    if not PROFILE_LINK.search(cv):
        lines = add_to_improve(lines, ADD_LINKEDIN[language], language, ABOUT_LINKEDIN)
    if not has_job and has_projects:
        lines = add_to_improve(lines, ADD_JOB[language], language, ABOUT_JOB)
    elif not has_job:
        lines = add_to_improve(lines, ADD_FIRST_ROLE[language], language, first_role)
    if not many_skills:
        lines = add_to_improve(lines, ADD_MORE_SKILLS[language], language, ABOUT_MORE_SKILLS)
    lines = fill_if_empty(lines, TO_IMPROVE, f"1. {NO_IMPROVEMENTS[language]}")
    lines = fill_if_empty(lines, STRENGTHS, f"- {NO_STRENGTHS[language]}")
    analysis = "\n".join(lines)
    # "Section by section" lines that must match the CV
    analysis = replace_line(analysis, SKILLS_LINE[language], (MANY_SKILLS if many_skills else FEW_SKILLS)[language])
    analysis = replace_line(analysis, SUMMARY_LINE, "Summary: clear, and says what you are looking for." if role_stated
                            else "Summary: describes you, but does not say which role you want.")
    analysis = replace_line(analysis, TARGET_LINE, target_length(cv, language))
    if not has_job:  # not "some roles have no description yet": there is no role
        analysis = replace_line(analysis, EXPERIENCE_LINE[language], NO_JOB_YET[language])
    if degrees_added:
        analysis = replace_line(analysis, EDUCATION_LINE[language], DEGREES_ADDED[language])
    for line in PUBLICATIONS_ADD_MORE.findall(analysis):  # publications are not something to "add more" of
        log.info("CV analysis: line removed: %r", line.strip())
    analysis = PUBLICATIONS_ADD_MORE.sub("", analysis)
    if is_academic(cv) and language == "en" and not EXTRAS_LINE.search(analysis):
        lines = analysis.splitlines()
        if (start := next((n for n, line in enumerate(lines) if SECTION_BY_SECTION.match(line)), None)) is not None:
            lines.insert(block_end(lines, start), EXTRAS_KEEP)
            log.info("CV analysis: line added: %r", EXTRAS_KEEP)
            analysis = "\n".join(lines)

    rating = max(1, min(10, math.floor(rate_cv(cv) + 0.5)))  # rounded half up, 1-10
    verdict = next(v for v in VERDICTS if rating >= v[0])[1 if language == "en" else 2]
    if match := RATING.search(analysis):
        log.info("CV analysis: rating line %r -> %s/10 - %s (computed from the CV)", match.group().strip(), rating, verdict)
        return RATING.sub(lambda m: f"{m['label']}{rating}/10 - {verdict}", analysis, count=1)
    log.info("CV analysis: rating line added: %s/10 - %s", rating, verdict)
    heading, _, rest = analysis.partition("\n")  # no rating line: add one under the heading
    return f"{heading}\n{RATING_LABEL[language]} {rating}/10 - {verdict}\n{rest}".rstrip()


def page_limit(analysis: str) -> int | None:
    """The most pages the Target length line allows (1 page: 1, 1-2 pages and about 2
    pages: 2, 2-3 pages: 3); None for an academic CV or without the line."""
    target = TARGET_LINE.search(analysis)
    value = target.group()[len(target["prefix"]):] if target else ""
    if not target or ACADEMIC.search(value):
        return None
    return next((most for pattern, most in PAGE_LIMITS if pattern.search(value)), None)


def group_long_lists(cv: str) -> tuple[str, bool]:
    """The CV with each extra section of more than 3 items (activities, courses, other
    sections; not certifications, awards or publications) on one line, "; " between items."""
    lines, out, changed = cv.splitlines(), [], False
    number = 0
    while number < len(lines):
        out.append(lines[number])
        heading = lines[number].strip()
        if is_heading(heading) and ":" not in heading and line_kind(heading) in ("activities", "extras") \
                and not KEEP_AS_LIST.search(heading):
            end = next((n for n in range(number + 1, len(lines)) if is_heading(lines[n].strip()) and ":" not in lines[n]),
                       len(lines))
            items = [re.sub(r"^[-•*]\s+", "", line.strip()).rstrip(".;") for line in lines[number + 1:end] if line.strip()]
            if len(items) > 3:
                out += ["; ".join(items), ""] if end < len(lines) else ["; ".join(items)]
                log.info("CV: %s grouped on one line (%d items)", heading, len(items))
                changed = True
                number = end
                continue
        number += 1
    return "\n".join(out), changed


def condense_beyond_three(cv: str) -> tuple[str, bool]:
    """The CV with roles after the 3 newest, and projects after the first 3, cut to their
    first bullet (titles, companies and dates stay)."""
    drop = set()
    for kind in ("experience", "projects"):
        for role in experience_roles(cv, kind)[3:]:
            drop.update(role["bullets"][1:])
            if role["bullets"][1:]:
                log.info("CV: %s %r cut to its first bullet", kind, " | ".join(role["text"]))
    if not drop:
        return cv, False
    return "\n".join(line for number, line in enumerate(cv.splitlines()) if number not in drop), True


def fit_to_length(cv: str, analysis: str) -> tuple[str, str, bytes]:
    """(CV, analysis, PDF) with the CV condensed when its PDF is longer than the Target length
    allows: first long extra lists on one line, then, if still too long, roles after the 3
    newest and projects after the first 3 cut to their first bullet; the PDF is made again
    after each step. Nothing else is removed and the text stays at least 10pt. "What I
    changed" notes each step, and the "still longer" advice follows the final page count."""
    language = "ar" if ARABIC_LETTERS.search(analysis) else "en"
    one_page = is_one_page_target(analysis)
    pdf, limit = cv_pdf(cv, one_page=one_page), page_limit(analysis)
    pages = lambda data: pymupdf.open(stream=data, filetype="pdf").page_count
    notes = []
    for step, note, already in ((group_long_lists, GROUPED, ABOUT_GROUPED), (condense_beyond_three, CONDENSED, ABOUT_CONDENSED)):
        if limit is None or pages(pdf) <= limit:
            break
        cv, changed = step(cv)
        if changed:
            pdf = cv_pdf(cv, one_page=one_page)
            notes.append((note[language], already))
            log.info("CV: %s -> %d page(s) (target at most %d)", step.__name__, pages(pdf), limit)
    lines = analysis.splitlines()
    for note, already in notes:
        lines = add_change(lines, note, language, already)
    return cv, check_length("\n".join(lines), pages(pdf)), pdf


def check_length(analysis: str, pages: int) -> str:
    """The "Your CV is still longer than the target length..." advice only when the PDF
    (`pages`) is longer than the upper limit of the Target length line (1 page: 1, 1-2 pages
    and about 2 pages: 2, 2-3 pages: 3, academic: no limit); added when it is and missing.
    Runs after the PDF is made, so not in check_analysis."""
    language = "ar" if ARABIC_LETTERS.search(analysis) else "en"
    limit = page_limit(analysis)
    too_long = limit is not None and pages > limit
    lines = analysis.splitlines()
    if not too_long:
        lines = remove_items(lines, TO_IMPROVE, [ABOUT_TOO_LONG], f"advice for a long CV ({pages} page(s), limit {limit})")
        lines = fill_if_empty(lines, TO_IMPROVE, f"1. {NO_IMPROVEMENTS[language]}")
    else:
        lines = add_to_improve(lines, TOO_LONG[language], language, ABOUT_TOO_LONG)
    return "\n".join(lines)


def replace_line(analysis: str, pattern: re.Pattern, new: str) -> str:
    """Replace the "Section by section" line matching `pattern` (keeping its "- ") with `new`."""
    def replace(match):
        line = f"{match['prefix']}{new}"
        if line != match.group():
            log.info("CV analysis: %r -> %r", match.group().strip(), new)
        return line
    return pattern.sub(replace, analysis)


def fill_if_empty(lines: list[str], label_pattern: re.Pattern, item: str) -> list[str]:
    """Put `item` under the label `label_pattern` when its list has no item (left empty by
    the removals). Nothing happens when the analysis has no such list."""
    start = next((i for i, line in enumerate(lines) if label_pattern.match(line)), None)
    if start is None or lines[start].partition(":")[2].strip():
        return lines
    end = block_end(lines, start)
    if any(ITEM.match(line) for line in lines[start + 1:end]):
        return lines
    log.info("CV analysis: empty list %r filled with %r", lines[start].strip(), item)
    return lines[:start + 1] + [item] + lines[start + 1:]


def block_end(lines: list[str], start: int) -> int:
    """Index after the last line of the list that starts at the label line `start`."""
    end = start + 1
    while end < len(lines) and not (LABEL.match(lines[end]) and not ITEM.match(lines[end])):
        end += 1
    while end > start + 1 and not lines[end - 1].strip():  # blank lines belong to the next part
        end -= 1
    return end


def list_text(lines: list[str], label_pattern: re.Pattern) -> str:
    """The text of the list under the label `label_pattern` ("" if there is none)."""
    start = next((i for i, line in enumerate(lines) if label_pattern.match(line)), None)
    return "" if start is None else "\n".join(lines[start:block_end(lines, start)])


def remove_items(lines: list[str], label_pattern: re.Pattern, topics: list[re.Pattern], what: str) -> list[str]:
    """Remove the items about any of `topics` from the list under the label `label_pattern`
    ("Strengths:", "Most important to improve:"): "- " / "1." lines, or the text after the
    label. Numbered items are numbered again; an empty list is filled later (fill_if_empty)."""
    start = next((i for i, line in enumerate(lines) if label_pattern.match(line)), None)
    if start is None or not topics:
        return lines
    end = block_end(lines, start)
    label, _, inline = lines[start].partition(":")
    removed = [line for line in lines[start + 1:end] if ITEM.match(line) and any(t.search(line) for t in topics)]
    if inline.strip() and any(t.search(inline) for t in topics):
        removed.append(inline.strip())
        inline = ""
    if not removed:
        return lines
    log.warning("CV analysis: %s removed: %s", what, removed)
    kept, number = [], 0
    for line in lines[start + 1:end]:
        if line in removed:
            continue
        if (item := ITEM.match(line)) and item["number"]:
            number += 1
            line = f"{item['indent']}{number}{item['sep']} {line[item.end():]}"
        kept.append(line)
    return lines[:start] + [f"{label}:{inline}"] + kept + lines[end:]


def add_to_improve(lines: list[str], advice: str, language: str, already: re.Pattern) -> list[str]:
    """Add `advice` to the end of "Most important to improve" unless an item there already
    matches `already` (the list is created if the analysis has none)."""
    start = next((i for i, line in enumerate(lines) if TO_IMPROVE.match(line)), None)
    if start is None:
        log.info("CV analysis: improvements list added with %r", advice)
        return lines + ["", IMPROVE_LABEL[language], f"1. {advice}"]
    end = block_end(lines, start)
    if already.search(" ".join(lines[start:end])):
        return lines
    items = [ITEM.match(line) for line in lines[start + 1:end] if ITEM.match(line)]
    last = items[-1] if items else None
    if last and last["number"]:
        item = f"{last['indent']}{int(last['number']) + 1}{last['sep']} {advice}"
    elif last:
        item = f"{last['indent']}- {advice}"
    else:
        item = f"1. {advice}"
    log.info("CV analysis: advice added: %r", advice)
    return lines[:end] + [item] + lines[end:]


