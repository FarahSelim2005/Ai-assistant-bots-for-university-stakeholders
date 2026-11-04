"""Check the CV model's CV ANALYSIS against the CV it wrote (CV model v6).

The model sometimes praises things the CV does not have (links, skill levels, numbers), gives
advice the CV does not need, and its rating is not always consistent. After each rewrite the
analysis is corrected in code:
- strengths the CV does not support are removed;
- advice it does not need is removed: "Add 2-3 bullets about ..." when every role has its
  bullets, "Add more skills ..." when it lists 6 or more skills (and "Skills: a short list;
  add more." becomes "Skills: a good range.");
- missing advice is added: a LinkedIn link, and a first internship or job when there is none;
- the rating is computed again with a fixed rubric (rate_cv).
"""
import logging
import math
import re

from app.documents.cv_file import ARABIC_LETTERS, blocks

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
YEAR = re.compile(r"\d{4}")

# Lines of the analysis
RATING = re.compile(r"^(?P<label>[^\n:]{0,40}:\s*)\d+(?:\.\d+)?\s*/\s*10\b.*$", re.MULTILINE)
STRENGTHS = re.compile(r"^\W*(?:strengths|نقاط القوة|نقط القوة|المميزات|مميزات)", re.IGNORECASE)
TO_IMPROVE = re.compile(r"^\W*(?:most important to improve|أهم)", re.IGNORECASE)
LABEL = re.compile(r"^[^\s\-•*\d][^:\n]{0,50}:")            # "Section by section:", "Rating: ..."
ITEM = re.compile(r"^(?P<indent>\s*)(?:(?P<number>\d+)(?P<sep>[.)])|[-•*])\s*")
# What a strength is about
ABOUT_LINKS = re.compile(r"linkedin|github|لينكد|جيت ?هاب|\blinks?\b|روابط|لينكات", re.IGNORECASE)
ABOUT_LEVELS = re.compile(r"\blevels?\b|مستو[ىي]|مستويات", re.IGNORECASE)
ABOUT_NUMBERS = re.compile(r"measurable|quantif|numbers|metrics|أرقام|ارقام|قابلة للقياس|ملموسة", re.IGNORECASE)
ABOUT_LINKEDIN = re.compile(r"linkedin|لينكد", re.IGNORECASE)
# What an improvement is about
ABOUT_MISSING_BULLETS = re.compile(r"(?:add|ضيف)\s+2\s*[-–]\s*3\s+bullets", re.IGNORECASE)  # "Add 2-3 bullets about ..."
ABOUT_MORE_SKILLS = re.compile(r"add more skills that match the jobs you want", re.IGNORECASE)
ABOUT_JOB = re.compile(r"internship or part-time job|تدريب أو شغل part-time", re.IGNORECASE)
SHORT_SKILLS = re.compile(r"^(?P<prefix>[^\w\n]*)Skills: a short list; add more\.?[ \t]*$", re.MULTILINE | re.IGNORECASE)
ADD_JOB = {"en": "Add an internship or part-time job when you can; until then, your projects carry your CV.",
           "ar": "ضيف تدريب أو شغل part-time لما تقدر، ولحد ساعتها المشاريع هي اللي شايلة الـ CV."}
ADD_LINKEDIN = {"en": "Add a link to your LinkedIn profile.", "ar": "ضيف لينك بروفايل الـ LinkedIn بتاعك."}
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
        count += len([skill for skill in re.split(r"[,·;|]", text) if skill.strip()])
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


def check_analysis(analysis: str, cv: str) -> str:
    """The analysis made to match the CV: strengths and advice the CV does not support are
    removed, missing advice (LinkedIn, a first job) is added, and the rating is computed
    from the CV."""
    _, sections = cv_sections(cv)
    language = "ar" if ARABIC_LETTERS.search(analysis) else "en"
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
    not_needed = []  # advice for something the CV already has
    if NO_DETAILS not in cv:
        not_needed.append(ABOUT_MISSING_BULLETS)  # every role already has its bullets
    if many_skills:
        not_needed.append(ABOUT_MORE_SKILLS)
    lines = analysis.splitlines()
    lines = remove_items(lines, STRENGTHS, unsupported, "strengths not supported by the CV")
    lines = remove_items(lines, TO_IMPROVE, not_needed, "advice the CV does not need")
    if not PROFILE_LINK.search(cv):
        lines = add_to_improve(lines, ADD_LINKEDIN[language], language, ABOUT_LINKEDIN)
    if not has_job:
        lines = add_to_improve(lines, ADD_JOB[language], language, ABOUT_JOB)
    analysis = "\n".join(lines)
    if many_skills:  # "Section by section": the skills line said the list was short
        analysis = SHORT_SKILLS.sub(lambda m: f"{m['prefix']}Skills: a good range.", analysis)

    rating = max(0, min(10, math.floor(rate_cv(cv) + 0.5)))  # rounded half up
    verdict = next(v for v in VERDICTS if rating >= v[0])[1 if language == "en" else 2]
    log.info("CV analysis: rating %s/10 computed from the CV", rating)
    if RATING.search(analysis):
        return RATING.sub(lambda m: f"{m['label']}{rating}/10 - {verdict}", analysis, count=1)
    heading, _, rest = analysis.partition("\n")  # no rating line: add one under the heading
    return f"{heading}\n{RATING_LABEL[language]} {rating}/10 - {verdict}\n{rest}".rstrip()


def block_end(lines: list[str], start: int) -> int:
    """Index after the last line of the list that starts at the label line `start`."""
    end = start + 1
    while end < len(lines) and not (LABEL.match(lines[end]) and not ITEM.match(lines[end])):
        end += 1
    while end > start + 1 and not lines[end - 1].strip():  # blank lines belong to the next part
        end -= 1
    return end


def remove_items(lines: list[str], label_pattern: re.Pattern, topics: list[re.Pattern], what: str) -> list[str]:
    """Remove the items about any of `topics` from the list under the label `label_pattern`
    ("Strengths:", "Most important to improve:"): "- " / "1." lines, or the text after the
    label. Numbered items are numbered again; the label goes too when no item is left."""
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
    heading = [f"{label}:{inline}"] if inline.strip() or any(ITEM.match(line) for line in kept) else []
    return lines[:start] + heading + kept + lines[end:]


def add_to_improve(lines: list[str], advice: str, language: str, already: re.Pattern) -> list[str]:
    """Add `advice` to the end of "Most important to improve" unless an item there already
    matches `already` (the list is created if the analysis has none)."""
    start = next((i for i, line in enumerate(lines) if TO_IMPROVE.match(line)), None)
    if start is None:
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
    return lines[:end] + [item] + lines[end:]


