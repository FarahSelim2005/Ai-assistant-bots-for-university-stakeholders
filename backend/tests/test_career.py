"""Tests for the Internship & Career agent's CV rewrites (no model, search or database used).

Run from the backend folder:
    python -m unittest discover -s tests -v
"""
import unittest
from unittest import mock

import app.agents.base as base
from app.agents import AGENTS
from app.attachments import Attachment
from app.rag.prompts import CAREER_SYSTEM_PROMPT

CV = Attachment("cv.txt", text="Mariam Hassan\nComputer Science student\nPython, SQL")
HISTORY = [{"role": "user", "content": "old question"}, {"role": "assistant", "content": "old CV answer"}]


class CvRewrites(unittest.TestCase):
    def setUp(self):
        self.sent = []
        reply = lambda messages, models, *args, **kwargs: self.sent.append(messages) or "Template: Student\n\nMariam Hassan"
        import app.agents.internship_career as career_module
        self.patches = [mock.patch.object(base, "retrieve_best", return_value=[]),
                        mock.patch.object(base, "chat_with_backup", reply),            # general questions
                        mock.patch.object(career_module, "chat_with_backup", reply)]   # CV rewrites (the CV model)
        self.search = self.patches[0].start()
        for p in self.patches[1:]:
            p.start()
        self.career = AGENTS["internship_career"]

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_rewrite_skips_search_and_history(self):
        for request in ["Please rewrite my CV.", "Use the London template for my CV please.", "ظبطلي الـ CV ده لو سمحت"]:
            self.career.run(request, "student", HISTORY, CV)
            self.assertEqual(self.sent[-1], [
                {"role": "system", "content": f"{CAREER_SYSTEM_PROMPT}\n\nCONTEXT:\n(no matching GIU documents)"
                                              f"\n\nATTACHMENT FROM THE USER (cv.txt):\n{CV.text}"},
                {"role": "user", "content": request},
            ])
        self.search.assert_not_called()

    def test_other_career_questions_still_search(self):
        self.career.run("How do I prepare for an interview?", "student", HISTORY, None)
        self.career.run("Please analyze my CV and suggest improvements.", "student", HISTORY, CV)  # a review
        self.assertTrue(self.search.called)
        self.assertGreater(len(self.sent[-1]), 2)  # history is kept


class CvFiles(unittest.TestCase):
    def test_giu_is_not_written_into_another_universitys_cv(self):
        from app.agents.internship_career import check_university
        answer = "EDUCATION\nGERMAN INTERNATIONAL UNIVERSITY (GIU), 2022 - Present\n- GPA 3.5 at GIU"
        self.assertEqual(check_university(answer, "Cairo University, Computer Science, 2022 - Present"),
                         "EDUCATION\n[add your university], 2022 - Present\n- GPA 3.5 at [add your university]")
        for cv in ["German International University, 2022", "الجامعة الألمانية الدولية"]:  # GIU students keep it
            self.assertEqual(check_university(answer, cv), answer)

    def test_cut_links_are_completed_from_the_pdf_links(self):
        from app.agents.internship_career import complete_links
        cv = "\n".join(["Farah Selim", "github.com/FarahSelim", "",
                        "Links: https://github.com/FarahSelim2005, https://www.linkedin.com/in/farah-selim-81"])
        answer = "github.com/FarahSelim | linkedin.com/in/farah-selim | https://github.com/FarahSelim2005 | github.com/other"
        self.assertEqual(complete_links(answer, cv), "https://github.com/FarahSelim2005 | https://www.linkedin.com/in/farah-selim-81 | "
                                                     "https://github.com/FarahSelim2005 | github.com/other")

    def test_headings_are_not_left_at_a_page_bottom(self):
        from app.documents.cv_file import cv_pdf, render_cv, stranded_headings
        def cv_with(roles):
            lines = ["Template: Student", "", "FARAH SELIM", "CS Student", "", "SUMMARY", "Student.", "", "EXPERIENCE"]
            for i in range(roles):
                lines += [f"ROLE {i}, 2020 - 2021", "Company", "- Built things", "- Led things"]
            return "\n".join(lines + ["", "PROJECTS", "Project A", "- Did A", "", "SKILLS", "- Python"])
        # a CV length whose layout strands a heading ...
        cv = next(cv_with(n) for n in range(5, 20) if stranded_headings(render_cv(cv_with(n), set())))
        self.assertFalse(stranded_headings(cv_pdf(cv)))  # ... and cv_pdf moves it to the next page


ENGLISH_CV = "\n".join([
    "Farah Selim", "Computer Science Student", "Cairo | farah@gmail.com | +20 100 123 4567", "",
    "SUMMARY", "Computer Science student at Cairo University.", "",
    "EDUCATION", "CAIRO UNIVERSITY, 2022 - Present", "B.Sc. Computer Science", "",
    "EXPERIENCE", "SOFTWARE INTERN, Jul 2024 - Sep 2024", "Khatwa, Cairo", "- Built 3 dashboards"])
ARABIC_CV = "\n".join([
    "فرح سليم", "طالبة علوم حاسب", "القاهرة | farah@gmail.com | +20 100 123 4567", "",
    "الملخص", "طالبة علوم حاسب في جامعة القاهرة.", "",
    "الخبرات العملية", "متدربة برمجيات، 2024 - 2025", "شركة خطوة، القاهرة",
    "- بنيت 3 لوحات بيانات باستخدام Python و Power BI", "",
    "المهارات", "- Python (متقدم)"])
ENGLISH_ANALYSIS = "CV ANALYSIS\nRating: 6/10 - a good start\nWhat I changed:\n- Reordered sections\nMost important to improve:\n1. Add 2 projects"
ARABIC_ANALYSIS = "تحليل الـ CV\nالتقييم: 6/10 - بداية كويسة\nما غيرته:\n- رتبت الأقسام"


class CvAnalysis(unittest.TestCase):
    """CV model v6: the CV, then the CV ANALYSIS. Stubbed answers, no model is called."""

    def test_answer_is_split_at_the_analysis(self):
        from app.documents.cv_file import split_cv
        for cv, analysis in [(ENGLISH_CV, ENGLISH_ANALYSIS), (ARABIC_CV, ARABIC_ANALYSIS)]:
            self.assertEqual(split_cv(f"Template: Student\n{cv}\n\n{analysis}"), (f"Template: Student\n{cv}", analysis))
        self.assertEqual(split_cv("Template: Student\nOmar\n\nWhat I changed:\n- x")[1], "What I changed:\n- x")  # older models

    def test_checks_only_change_the_cv(self):
        # The analysis has numbers that are not in the CV ("2 projects"): they stay (its rating
        # is computed again from the CV, see AnalysisCheck)
        import app.agents.internship_career as career_module
        answer = f"Template: Student\n{ENGLISH_CV}\n- Led 87 people\n\n{ENGLISH_ANALYSIS}"
        attachment = Attachment("cv.txt", text=ENGLISH_CV)
        with mock.patch.object(career_module, "chat_with_backup", return_value=answer):
            result = AGENTS["internship_career"].generate("fix my cv", [], [], attachment)
        self.assertIn("- Led [add the number] people", result)  # invented in the CV: replaced
        self.assertTrue(result.endswith("Most important to improve:\n1. Add 2 projects"
                                        "\n2. Say in your summary which role or internship you are looking for."
                                        "\n3. Add a link to your LinkedIn profile."
                                        "\n4. Add more skills that match the jobs you want."))  # no skills section

    def test_pdf_has_the_cv_and_the_chat_has_the_analysis(self):
        import pymupdf
        from app.agents.base import AgentResponse
        from app.routers.chat import cv_files
        for cv, analysis in [(ENGLISH_CV, ENGLISH_ANALYSIS), (ARABIC_CV, ARABIC_ANALYSIS)]:
            outcome = cv_files(AgentResponse(answer=f"Template: Student\n{cv}\n\n{analysis}", sources=[]), "cv.pdf")
            self.assertEqual(outcome.response.answer, analysis)
            text = pymupdf.open(stream=outcome.files[0][0], filetype="pdf")[0].get_text()
            self.assertIn("farah@gmail.com", text)
            self.assertNotIn("6/10", text)  # the analysis is not in the PDF
        no_analysis = cv_files(AgentResponse(answer=f"Template: Student\n{ENGLISH_CV}", sources=[]), "cv.pdf")
        self.assertEqual(no_analysis.response.answer, "Here is your restructured CV.")

    def test_arabic_cv_is_right_to_left(self):
        import io
        import pymupdf
        from docx import Document
        from app.documents.cv_file import blocks, cv_docx, cv_pdf
        kinds = dict((text, kind) for kind, text in blocks(ARABIC_CV))
        self.assertEqual(kinds["الخبرات العملية"], "heading")
        self.assertEqual(kinds["متدربة برمجيات، 2024 - 2025"], "entry")
        self.assertEqual(kinds["شركة خطوة، القاهرة"], "text")
        import unicodedata
        import app.documents.cv_file as cv_file
        page = pymupdf.open(stream=cv_pdf(ARABIC_CV), filetype="pdf")[0]
        text = unicodedata.normalize("NFKC", page.get_text())  # Arabic letter forms -> letters
        for words in ["فرح سليم", "الخبرات العملية", "شركة خطوة"]:
            self.assertIn(words, text)  # selectable text that reads back correctly (with Tahoma)
        self.assertGreater(page.search_for("farah@gmail.com")[0].x1, page.rect.width / 2)  # on the right
        with mock.patch.object(cv_file, "SYSTEM_FONTS", cv_file.Path("no-such-folder")):  # no Tahoma
            fallback = pymupdf.open(stream=cv_pdf(ARABIC_CV), filetype="pdf")[0]
        self.assertTrue(any("Arabic" in font[3] for font in fallback.get_fonts()))  # MuPDF's own Arabic font
        english = pymupdf.open(stream=cv_pdf(ENGLISH_CV), filetype="pdf")[0]
        self.assertLess(english.search_for("farah@gmail.com")[0].x0, english.rect.width / 2)
        document = Document(io.BytesIO(cv_docx(ARABIC_CV)))
        self.assertTrue(all(p._p.pPr.find(f"{{{p._p.nsmap['w']}}}bidi") is not None for p in document.paragraphs))

    def test_pdf_is_readable_and_ats_friendly(self):
        import pymupdf
        from app.documents.cv_file import cv_pdf
        page = pymupdf.open(stream=cv_pdf(ENGLISH_CV), filetype="pdf")[0]
        self.assertFalse(page.get_images())  # real text, no pictures
        sizes = {round(span["size"], 1): span["text"] for block in page.get_text("dict")["blocks"]
                 for line in block["lines"] for span in line["spans"]}
        self.assertIn(10.5, sizes)                            # body text 10.5pt
        self.assertIn(13.0, sizes)                            # section headings 13pt
        self.assertIn("EXPERIENCE", page.get_text())


NO_LINKEDIN_CV = "\n".join([
    "Template: Student", "Omar Khalil", "Business Student", "Cairo | omar@gmail.com | +20 111 222 3333", "",
    "SUMMARY", "Business student at Cairo University.", "[add the role or internship you are looking for]", "",
    "EDUCATION", "CAIRO UNIVERSITY, 2021 - 2025", "B.Com. Business Administration", "",
    "EXPERIENCE", "SALES INTERN, Jul 2024 - Sep 2024", "Khatwa, Cairo", "- Helped customers in the store",
    "CASHIER, 2 years", "Store, Cairo", "- [add details about what you did]", "",
    "SKILLS", "- Excel", "- Communication", "- Teamwork", "", "LANGUAGE", "- Arabic - Native"])
OVERPRAISING_ANALYSIS = "\n".join([
    "CV ANALYSIS", "Rating: 8/10 - Strong CV", "Target length: 1 page", "What I changed:", "- Reordered sections",
    "Strengths:", "- Clear contact details with LinkedIn and GitHub links", "- Skills listed with levels",
    "- Experience bullets show measurable results", "- Clear education section with dates",
    "Most important to improve:", "1. Add details to your cashier role", "2. Say in your summary which role or internship you are looking for.",
    "Section by section:", "- Summary: short"])


class AnalysisCheck(unittest.TestCase):
    """The CV ANALYSIS is corrected against the CV it describes (no model is called)."""

    def test_cv_without_linkedin(self):
        from app.documents.cv_analysis import check_analysis
        self.assertEqual(check_analysis(OVERPRAISING_ANALYSIS, NO_LINKEDIN_CV), "\n".join([
            "CV ANALYSIS", "Rating: 5/10 - Needs work", "Target length: 1 page (student / fresh graduate)",
            "What I changed:", "- Reordered sections",
            "Strengths:", "- Clear education section with dates",  # links, levels and numbers: not in the CV
            "Most important to improve:", "1. Add details to your cashier role", "2. Say in your summary which role or internship you are looking for.",
            "3. Add a link to your LinkedIn profile.", "4. Add more skills that match the jobs you want.",  # 3 skills
            "Section by section:", "- Summary: describes you, but does not say which role you want."]))

    def test_rubric(self):
        from app.documents.cv_analysis import rate_cv
        # phone 1, summary 0.5, education dates 1, one role with bullets 1.5, 3 skills 0.5,
        # a language 0.5, minus 0.5 for a role without details
        self.assertEqual(rate_cv(NO_LINKEDIN_CV), 4.5)
        full = NO_LINKEDIN_CV.replace("Cairo | omar@gmail.com", "Cairo | omar@gmail.com | linkedin.com/in/omar") \
            .replace("[add the role or internship you are looking for]", "Looking for a sales internship.") \
            .replace("- [add details about what you did]", "- Served 80 customers a day") \
            .replace("- Teamwork", "- Teamwork\n- SQL\n- Power BI\n- Python") \
            + "\n\nPROJECTS\nShop Dashboard\n- Built a sales dashboard\n\nCERTIFICATIONS\n- Google Data Analytics"
        self.assertEqual(rate_cv(full), 10)

    def test_supported_strengths_stay_and_arabic_verdict(self):
        from app.documents.cv_analysis import check_analysis
        cv = NO_LINKEDIN_CV.replace("Cairo | omar@gmail.com", "Cairo | omar@gmail.com | linkedin.com/in/omar") \
            .replace("- Excel", "- Excel (Advanced)").replace("in the store", "in the store, 40 a day")
        analysis = "\n".join(["تحليل الـ CV", "التقييم: 9/10 - ممتاز", "نقاط القوة:", "- فيه لينك LinkedIn",
                              "- المهارات ليها مستوى", "- أرقام في الخبرات", "أهم حاجات محتاجة تتحسن:", "1. ضيف مشاريع"])
        checked = check_analysis(analysis, cv)
        self.assertEqual(checked, analysis.replace("9/10 - ممتاز", "7/10 - CV كويس بس فيه شوية حاجات ناقصة")
                         + "\n2. اكتب في الملخص الوظيفة أو التدريب اللي بتدور عليه."  # role not stated
                         + "\n3. ضيف مهارات أكتر تناسب الشغل اللي عايزه.")  # 3 skills


    def test_advice_for_a_cv_with_projects_but_no_job(self):
        from app.documents.cv_analysis import check_analysis
        cv = "\n".join([
            "Template: Student", "Nour Adel", "Computer Science Student", "Cairo | nour@gmail.com | github.com/nour", "",
            "SUMMARY", "Computer Science student looking for a software internship.", "",
            "EDUCATION", "CAIRO UNIVERSITY, 2022 - Present", "B.Sc. Computer Science", "",
            "EXPERIENCE", "[add an internship, part-time job, project or volunteering role]", "",
            "PROJECTS", "Chat App, 2024", "- Built a chat app used by 50 students", "",
            "SKILLS", "- Python", "- Java", "- SQL", "- Git", "- React", "- Teamwork"])
        analysis = "\n".join([
            "CV ANALYSIS", "Rating: 3/10 - Needs a lot of work", "Most important to improve:",
            "1. Add 2-3 bullets about what you did as Intern.", "2. Add more skills that match the jobs you want.",
            "3. Add a link to your LinkedIn profile.", "4. Say in your summary which role or internship you are looking for.",
            "Section by section:", "- Summary: missing the target role.", "- Experience: some roles have no description yet.",
            "- Skills: a short list; add more."])
        checked = check_analysis(analysis, cv).splitlines()
        self.assertEqual(checked[2:], [
            "Most important to improve:",
            "1. Add a link to your LinkedIn profile.",  # no "[add details ...]", 6 skills, role stated: the others go
            "2. Add an internship or part-time job when you can.",
            "Section by section:", "- Summary: clear, and says what you are looking for.",
            "- Experience: no internship or job yet.", "- Skills: a good range."])

    def test_advice_the_cv_still_needs_stays(self):
        from app.documents.cv_analysis import check_analysis
        analysis = "\n".join([
            "CV ANALYSIS", "Rating: 5/10 - Needs work", "Most important to improve:",
            "1. Add 2-3 bullets about what you did as Cashier.", "2. Add more skills that match the jobs you want.",
            "3. Say in your summary which role or internship you are looking for.",
            "Section by section:", "- Summary: missing the target role.", "- Experience: some roles have no description yet.",
            "- Skills: a short list; add more."])
        # NO_LINKEDIN_CV has "[add details about what you did]", "[add the role or internship ...]",
        # 3 skills and two jobs: all of this is still true
        self.assertEqual(check_analysis(analysis, NO_LINKEDIN_CV), analysis.replace(
            "looking for.\n", "looking for.\n4. Add a link to your LinkedIn profile.\n").replace(
            "- Summary: missing the target role.", "- Summary: describes you, but does not say which role you want."))

    def test_personal_details_advice_only_when_some_were_removed(self):
        from app.documents.cv_analysis import check_analysis
        advice = {"en": "1. Keep personal details and hobbies out of your CV.",
                  "ar": "1. خلي البيانات الشخصية والهوايات برا الـ CV."}
        for language, changed, removed_note, improve in [
                ("en", "What I changed:", "- Removed personal details / hobbies", "Most important to improve:"),
                ("ar", "ما غيرته:", "- شيلت البيانات الشخصية والهوايات", "أهم حاجات محتاجة تتحسن:")]:
            for notes, kept in [(["- Reordered sections", removed_note], True), (["- Reordered sections"], False)]:
                analysis = "\n".join([changed, *notes, improve, advice[language], "2. Add numbers."])
                checked = check_analysis(analysis, NO_LINKEDIN_CV)
                self.assertEqual(advice[language] in checked, kept, (language, notes))
                if not kept:
                    self.assertIn("\n1. Add numbers.", checked)  # numbered again

    def test_empty_lists_get_a_general_line(self):
        from app.documents.cv_analysis import check_analysis
        cv = NO_LINKEDIN_CV.replace("Cairo | omar@gmail.com", "Cairo | omar@gmail.com | linkedin.com/in/omar") \
            .replace("- [add details about what you did]", "- Served customers") \
            .replace("- Teamwork", "- Teamwork\n- SQL\n- Word\n- Sales") \
            .replace("[add the role or internship you are looking for]", "Looking for a sales internship.")  # role stated
        analysis = "\n".join(["CV ANALYSIS", "Rating: 9/10 - Strong CV", "Strengths:",
                              "- Your skills are well organized and show your level.",  # no levels or groups
                              "Most important to improve:", "1. Add 2-3 bullets about what you did as Cashier."])
        self.assertEqual(check_analysis(analysis, cv).splitlines()[2:], [
            "Strengths:", "- You have a clear starting point: your education and skills.",
            "Most important to improve:", "1. Tailor your summary and skills to each job you apply for."])

    def test_arabic_cv_notes_and_strengths(self):
        from app.documents.cv_analysis import check_analysis
        analysis = "\n".join(["تحليل الـ CV", "التقييم: 9/10 - ممتاز", "ما غيرته:",
                              "- كتبت كل bullet يبدأ بـ action verb.", "- رتبت الأقسام.",
                              "نقاط القوة:", "- المهارات متنظمة وموضح مستواها.", "- التعليم واضح.",
                              "أهم حاجات محتاجة تتحسن:", "1. ضيف أرقام."])
        checked = check_analysis(analysis, ARABIC_CV.replace("- Python (متقدم)", "- Python")).splitlines()
        self.assertEqual(checked[2:6], ["ما غيرته:", "- رتبت الأقسام.", "نقاط القوة:", "- التعليم واضح."])
        self.assertTrue(any(line.endswith("ضيف لينك الـ LinkedIn بتاعك.") for line in checked))

    def test_model_tags_and_lowest_rating(self):
        from app.documents.cv_analysis import check_analysis, strip_model_tags
        self.assertEqual(strip_model_tags("<think>\n</think>\n\n</tool_call>\nTemplate: Student\nOmar"),
                         "Template: Student\nOmar")
        self.assertEqual(strip_model_tags("Template: Student\nOmar"), "Template: Student\nOmar")
        self.assertIn("Rating: 1/10 - Needs a lot of work",
                      check_analysis("CV ANALYSIS\nRating: 5/10 - ok", "Template: Student\nOmar"))

    def test_arabic_advice_for_a_cv_without_a_job(self):
        from app.documents.cv_analysis import check_analysis
        cv = "\n".join(["Template: Student", "نور عادل", "القاهرة | nour@gmail.com | linkedin.com/in/nour", "",
                        "الخبرات العملية", "[add an internship, part-time job, project or volunteering role]", "",
                        "المشاريع", "تطبيق شات، 2024", "- بنيت تطبيق شات"])
        analysis = "\n".join(["تحليل الـ CV", "التقييم: 4/10 - محتاج شغل", "أهم حاجات محتاجة تتحسن:",
                              "1. ضيف 2-3 bullets عن اللي عملته في التدريب.", "2. ضيف أرقام للمشاريع.",
                              "3. اكتب في الملخص الوظيفة أو التدريب اللي بتدور عليه.",
                              "تحليل كل جزء:", "- الخبرات: فيه أدوار لسه مالهاش وصف."])
        self.assertEqual(check_analysis(analysis, cv).splitlines()[2:], [
            "أهم حاجات محتاجة تتحسن:", "1. ضيف أرقام للمشاريع.",
            "2. اكتب في الملخص الوظيفة أو التدريب اللي بتدور عليه.",  # no summary
            "3. ضيف تدريب أو شغل part-time لما تقدر.",
            "4. ضيف مهارات أكتر تناسب الشغل اللي عايزه.",  # no skills section
            "تحليل كل جزء:", "- الخبرات: لسه مفيش تدريب أو شغل."])

    def test_target_length_from_the_cv(self):
        import datetime
        from app.documents.cv_analysis import check_analysis, target_length
        def london(*dates):  # a London CV with one role per date line
            roles = [f"{d}\nEngineer - Company, Cairo\n- Built things" for d in dates]
            return "Template: London\nOmar, Engineer\n\nEXPERIENCE\n" + "\n".join(roles)
        year = datetime.date.today().year
        self.assertEqual(target_length(london("Mar 2021 - Present", "Sep 2013 - May 2015"), "en"),
                         "2-3 pages (more than 10 years of experience)" if year - 2013 > 10 else "about 2 pages (5-10 years of experience)")
        self.assertEqual(target_length(london("Jan 2018 - Dec 2024"), "en"), "about 2 pages (5-10 years of experience)")
        self.assertEqual(target_length(london("Aug 2021 - Dec 2024"), "en"), "1-2 pages (1-5 years of experience)")
        self.assertEqual(target_length(london("Jun 2024 - Sep 2024"), "en"), "1 page (student / fresh graduate)")
        # the template does not matter: a worker in the Student template still gets pages by years
        self.assertEqual(target_length(london("Jan 2018 - Dec 2024").replace("London", "Student"), "en"),
                         "about 2 pages (5-10 years of experience)")
        # internships are not full-time work
        internships = london("Jun 2022 - Sep 2022", "Jun 2024 - Sep 2024").replace("Engineer - Company", "Software Intern - Company")
        self.assertEqual(target_length(internships, "en"), "1 page (student / fresh graduate)")
        self.assertEqual(target_length(london("Jan 2018 - Dec 2024"), "ar"), "حوالي صفحتين (من 5 لـ 10 سنين خبرة)")
        checked = check_analysis("CV ANALYSIS\nRating: 5/10\nTarget length: 1 page", london("Jan 2018 - Dec 2024"))
        self.assertIn("\nTarget length: about 2 pages (5-10 years of experience)\n", checked)

    def test_role_line_keeps_only_the_job_title(self):
        from app.documents.cv_analysis import clean_role_line
        student = "Template: Student\nRana Gamal\nMarketing Specialist, Jan 2023 - Present\nGiza | rana@example.com\n\nSUMMARY\nx"
        self.assertEqual(clean_role_line(student).splitlines()[2], "Marketing Specialist")
        for role in ["Marketing Specialist - Bright Future Company", "Marketing Specialist (Jan 2023 - Present)",
                     "Marketing Specialist at Bright Future", "Marketing Specialist | Bright Future"]:
            self.assertEqual(clean_role_line(student.replace("Marketing Specialist, Jan 2023 - Present", role)).splitlines()[2],
                             "Marketing Specialist")
        kept = student.replace("Marketing Specialist, Jan 2023 - Present", "Computer Science Student")
        self.assertEqual(clean_role_line(kept), kept)                                   # already only a title
        no_role = "Template: Student\nRana Gamal\nGiza | rana@example.com | +20 100 000 5521\n\nSUMMARY\nx"
        self.assertEqual(clean_role_line(no_role), no_role)                             # contact line, not a role
        london = "Template: London\nHesham, Engineering Manager, Mar 2021 - Present\nCairo | h@example.com"
        self.assertEqual(clean_role_line(london).splitlines()[1], "Hesham, Engineering Manager")
        arabic = "Template: Student\nفرح سليم\nطالبة علوم حاسب، 2022 - 2026\nالقاهرة | farah@gmail.com"
        self.assertEqual(clean_role_line(arabic).splitlines()[2], "طالبة علوم حاسب")

    def test_older_roles_keep_their_first_bullet(self):
        from app.documents.cv_analysis import check_analysis, condense_old_roles
        cv = "\n".join(["Template: London", "Hesham, Manager", "", "EXPERIENCE",
                        "Mar 2021 - Present", "Engineering Manager - Nilebyte", "- Led a team of 9", "- Hired 5 engineers",
                        "Sep 2013 - May 2015", "Junior Developer - Lotus Group", "- Maintained an HR system",
                        "- Built monthly reports", "- Fixed bugs", "", "EDUCATION", "2008 - 2012", "B.Sc. - Ain Shams"])
        condensed, changed = condense_old_roles(cv)
        self.assertTrue(changed)
        self.assertIn("- Hired 5 engineers", condensed)              # a current role keeps all its bullets
        self.assertIn("- Maintained an HR system", condensed)        # an old role keeps its first bullet ...
        self.assertNotIn("- Built monthly reports", condensed)       # ... only
        self.assertEqual(condense_old_roles(condensed), (condensed, False))
        note = "Condensed older roles and extra projects to their main point to keep the CV focused."
        self.assertIn(f"- {note}", check_analysis("What I changed:\n- Reordered sections.", condensed, condensed=True))
        full = "What I changed:\n" + "\n".join(f"- Change {n}." for n in range(1, 6))
        checked = check_analysis(full, condensed, condensed=True)
        self.assertIn(f"- Change 4.\n- {note}", checked)              # at most 5: it takes the last place
        self.assertNotIn("Change 5", checked)

    def test_proofread_advice_only_after_spelling_fixes(self):
        from app.documents.cv_analysis import check_analysis
        advice = "1. Proofread your CV carefully; it had spelling mistakes."
        for changed, kept in [("- Fixed spelling mistakes.", True), ("- Reordered sections.", False)]:
            checked = check_analysis(f"What I changed:\n{changed}\nMost important to improve:\n{advice}", NO_LINKEDIN_CV)
            self.assertEqual(advice in checked, kept)

    def test_dates_advice_only_for_a_role_with_only_a_duration(self):
        from app.documents.cv_analysis import check_analysis
        # NO_LINKEDIN_CV: "SALES INTERN, Jul 2024 - Sep 2024" and "CASHIER, 2 years"
        advice = ["1. Write the start and end months for Cashier instead of only the duration.",
                  "2. Write the start and end months for Sales Intern instead of only the duration.",
                  "3. Write the start and end months for Barista instead of only the duration."]
        checked = check_analysis("Most important to improve:\n" + "\n".join(advice), NO_LINKEDIN_CV)
        self.assertIn(advice[0], checked)                          # only a duration: kept
        self.assertNotIn("Sales Intern", checked)                  # real dates: removed
        self.assertNotIn("Barista", checked)                       # not in the CV: removed
        arabic_cv = ARABIC_CV.replace("متدربة برمجيات، 2024 - 2025", "متدربة برمجيات، 6 شهور")
        arabic = "أهم حاجات محتاجة تتحسن:\n1. اكتب شهر البداية والنهاية لـ متدربة برمجيات بدل المدة بس."
        self.assertIn("1. اكتب شهر البداية والنهاية لـ متدربة برمجيات", check_analysis(arabic, arabic_cv))
        self.assertNotIn("اكتب شهر البداية", check_analysis(arabic, ARABIC_CV))  # it has years

    def test_changes_the_cv_does_not_show_are_removed(self):
        from app.documents.cv_analysis import check_analysis
        analysis = "\n".join(["What I changed:", "- Reordered sections.", "- Added [placeholders] for missing information; fill them in.",
                              "- Fixed spelling mistakes.", "Most important to improve:",
                              "1. Proofread your CV carefully; it had spelling mistakes."])
        no_placeholders = NO_LINKEDIN_CV.replace("- [add details about what you did]", "- Served customers") \
            .replace("[add the role or internship you are looking for]", "Looking for a sales internship.")
        checked = check_analysis(analysis, no_placeholders, original=no_placeholders.replace("Communication", "Comunication"))
        self.assertNotIn("placeholders", checked)                     # no "[" in the CV
        self.assertIn("Fixed spelling mistakes.", checked)            # "Comunication" -> "Communication"
        self.assertIn("Proofread", checked)
        checked = check_analysis(analysis, no_placeholders, original=no_placeholders)  # nothing corrected
        self.assertNotIn("Fixed spelling", checked)
        self.assertNotIn("Proofread", checked)
        self.assertIn("placeholders", check_analysis(analysis, NO_LINKEDIN_CV, original=NO_LINKEDIN_CV))  # has "["
        arabic = "تحليل الـ CV\nما غيرته:\n- حطيت [placeholders] للمعلومات الناقصة.\n- صلحت الأخطاء الإملائية.\n- رتبت الأقسام."
        checked = check_analysis(arabic, ARABIC_CV, original=ARABIC_CV)  # no "[", nothing corrected
        self.assertNotIn("placeholders", checked)
        self.assertNotIn("صلحت الأخطاء الإملائية", checked)
        self.assertIn("ما غيرته:\n- رتبت الأقسام.", checked)

    def test_experience_in_more_than_one_role_needs_two_roles(self):
        from app.documents.cv_analysis import check_analysis
        strengths = "Strengths:\n- You have practical experience in more than one role.\n- Clear dates."
        self.assertIn("more than one role", check_analysis(strengths, NO_LINKEDIN_CV))          # 2 roles
        one_role = ENGLISH_CV                                                                    # 1 role
        self.assertNotIn("more than one role", check_analysis(strengths, one_role))
        arabic = "نقاط القوة:\n- عندك خبرة عملية في أكتر من مكان.\n- التعليم واضح."
        self.assertNotIn("أكتر من مكان", check_analysis(arabic, ARABIC_CV))                       # 1 role

    def test_arabic_skills_sentences_follow_the_count(self):
        from app.documents.cv_analysis import check_analysis
        analysis = "نقاط القوة:\n- عندك مجموعة مهارات كويسة.\n- التعليم واضح.\nتحليل كل جزء:\n- المهارات: مجموعة كويسة."
        few = check_analysis(analysis, ARABIC_CV)                       # 1 skill
        self.assertNotIn("مجموعة مهارات كويسة", few)
        self.assertIn("- المهارات: قليلة، ضيف أكتر.", few)
        many = ARABIC_CV.replace("- Python (متقدم)", "- Python\n- SQL\n- Excel\n- Power BI\n- العمل الجماعي\n- التواصل")
        checked = check_analysis(analysis, many)                       # 6 skills
        self.assertIn("عندك مجموعة مهارات كويسة", checked)
        self.assertIn("- المهارات: مجموعة كويسة.", checked)

    def test_summary_line_follows_the_summary(self):
        from app.documents.cv_analysis import check_analysis
        analysis = "Most important to improve:\n1. Add numbers.\nSection by section:\n- Summary: clear, and says what you are looking for."
        stated = NO_LINKEDIN_CV.replace("[add the role or internship you are looking for]", "Looking for a senior marketing role.")
        self.assertIn("- Summary: clear, and says what you are looking for.", check_analysis(analysis, stated))
        self.assertNotIn("Say in your summary", check_analysis(analysis, stated))
        not_stated = NO_LINKEDIN_CV.replace("[add the role or internship you are looking for]", "Manager with 12 years of experience.")
        checked = check_analysis(analysis, not_stated)
        self.assertIn("- Summary: describes you, but does not say which role you want.", checked)
        self.assertIn("2. Say in your summary which role or internship you are looking for.", checked)

    def test_one_piece_of_advice_for_a_first_job(self):
        from app.documents.cv_analysis import check_analysis
        both = ["Most important to improve:",
                "1. Add an internship, part-time job, project or volunteering role; this is the biggest gap.",
                "2. Add an internship or part-time job when you can."]
        nothing_yet = "\n".join(["Template: Student", "Youssef Adel", "Cairo | +20 111 000 2233", "",
                                 "EXPERIENCE", "[add an internship, part-time job, project or volunteering role]"])
        checked = check_analysis("\n".join(both), nothing_yet).splitlines()
        self.assertIn(both[1], checked)  # no projects: the first one stays ...
        self.assertNotIn(both[2], checked)
        with_project = nothing_yet + "\n\nPROJECTS\nChat App\n- Built a chat app"
        checked = check_analysis("\n".join(both), with_project).splitlines()
        self.assertIn("1. Add an internship or part-time job when you can.", checked)  # ... projects: the second one
        self.assertFalse(any("volunteering role" in line for line in checked))
        # only the second one, no projects: replaced by the first one
        checked = check_analysis("\n".join([both[0], "1. Add an internship or part-time job when you can."]), nothing_yet)
        self.assertIn("Add an internship, part-time job, project or volunteering role.", checked)
        self.assertNotIn("when you can", checked)

    def test_skills_line_and_advice_follow_the_count(self):
        from app.documents.cv_analysis import check_analysis
        analysis = "\n".join(["Most important to improve:", "1. Add numbers.", "Section by section:", "- Skills: a good range."])
        checked = check_analysis(analysis, NO_LINKEDIN_CV)  # 3 skills
        self.assertIn("- Skills: a short list; add more.", checked)
        self.assertIn("Add more skills that match the jobs you want.", checked)
        six = NO_LINKEDIN_CV.replace("- Teamwork", "- Teamwork\n- SQL\n- Word\n- Sales")
        checked = check_analysis(analysis.replace("a good range.", "a short list; add more.")
                                 .replace("1. Add numbers.", "1. Add numbers.\n2. Add more skills that match the jobs you want."), six)
        self.assertIn("- Skills: a good range.", checked)
        self.assertNotIn("Add more skills", checked)
        arabic = check_analysis("أهم حاجات محتاجة تتحسن:\n1. ضيف أرقام.\nتحليل كل جزء:\n- المهارات: كويسة.", ARABIC_CV)
        self.assertIn("- المهارات: قليلة، ضيف أكتر.", arabic)

    def test_no_action_verb_note_without_bullets(self):
        from app.documents.cv_analysis import check_analysis
        analysis = "What I changed:\n- Reordered your sections.\n- Rewrote your bullets to start with action verbs."
        no_bullets = "Template: Student\nYoussef Adel\n\nEDUCATION\nHELWAN UNIVERSITY, 2024 - Present\n\nSKILLS\n- Python"
        self.assertNotIn("action verbs", check_analysis(analysis, no_bullets))
        self.assertIn("action verbs", check_analysis(analysis, NO_LINKEDIN_CV))  # has bullets


class PdfLayout(unittest.TestCase):
    @staticmethod
    def cv_with(bullets, extra_line=False):
        lines = ["Template: Student", "Omar Khalil", "Business Student", "Cairo | omar@gmail.com", "",
                 "EXPERIENCE", "SALES INTERN, 2024 - 2025", "Khatwa, Cairo"]
        lines += [f"- Did task number {i}" for i in range(bullets)] + (["Store, Cairo"] if extra_line else [])
        return "\n".join(lines + ["", "REFERENCES", "Available upon request"])

    def test_a_small_section_that_fits_is_not_moved(self):
        import pymupdf
        from app.documents.cv_file import TEXT_AREA, cv_pdf, render_cv

        def place(pdf, text):
            with pymupdf.open(stream=pdf, filetype="pdf") as document:
                return next((n, rect) for n, page in enumerate(document) for rect in page.search_for(text))
        # REFERENCES close to the page bottom with its one line still below it on the same page
        cv = next(cv for n in range(30, 60) for extra in (False, True) if (cv := self.cv_with(n, extra))
                  and (heading := place(render_cv(cv, set()), "REFERENCES"))[1].y1 > TEXT_AREA.y1 - 45
                  and place(render_cv(cv, set()), "Available upon request")[0] == heading[0] == 0)
        self.assertEqual(place(cv_pdf(cv), "REFERENCES")[0], 0)  # still on page 1

    def test_a_heading_stays_with_its_first_line_only(self):
        import pymupdf
        from app.documents.cv_file import cv_pdf, render_cv

        def page_of(pdf, text):
            with pymupdf.open(stream=pdf, filetype="pdf") as document:
                return next(n for n, page in enumerate(document) if page.search_for(text))
        # a two-line section whose heading and first line fit at the bottom of page 1
        cv = next(cv for n in range(30, 70) for extra in (False, True)
                  if (cv := self.cv_with(n, extra).replace("Available upon request", "- Arabic\n- English"))
                  and page_of(pdf := render_cv(cv, set()), "REFERENCES") == page_of(pdf, "Arabic") == 0
                  and page_of(pdf, "English") == 1)
        pdf = cv_pdf(cv)
        self.assertEqual((page_of(pdf, "REFERENCES"), page_of(pdf, "Arabic")), (0, 0))  # not moved as a whole

    def test_one_page_target_tightens_spacing_but_not_text(self):
        import pymupdf
        from app.documents.cv_file import cv_pdf, is_one_page_target, render_cv
        pages = lambda pdf: pymupdf.open(stream=pdf, filetype="pdf").page_count
        # just over one page in the normal layout, one page in the tightest one
        cv = next(cv for n in range(30, 70) if (cv := self.cv_with(n))
                  and pages(render_cv(cv, set())) == 2 and pages(render_cv(cv, set(), 2)) == 1)
        self.assertEqual(pages(cv_pdf(cv)), 2)                 # no 1-page target: normal layout
        tight = pymupdf.open(stream=cv_pdf(cv, one_page=True), filetype="pdf")
        self.assertEqual(tight.page_count, 1)
        self.assertGreaterEqual(min(span["size"] for block in tight[0].get_text("dict")["blocks"]
                                    for line in block["lines"] for span in line["spans"]), 10)
        self.assertTrue(is_one_page_target("Target length: 1 page"))
        self.assertFalse(is_one_page_target("Target length: 1-2 pages"))


class PdfAndCvRouting(unittest.TestCase):
    def test_pdf_requests(self):
        from app.documents.editor import is_pdf_request
        for text in ["send it as pdf", "send the cv as a pdf", "can I get it as a PDF?", "حوله بي دي اف", "ابعتهولي pdf"]:
            self.assertTrue(is_pdf_request(text), text)
        for text in ["what is a pdf?", "Is this a PDF?", "fix this"]:
            self.assertFalse(is_pdf_request(text), text)

    def test_cv_known_by_its_content(self):
        from app.routers.chat import looks_like_cv
        self.assertTrue(looks_like_cv(ENGLISH_CV))
        self.assertTrue(looks_like_cv(ARABIC_CV))
        self.assertTrue(looks_like_cv("NOUR ZAKI\n\nS U M M A R Y\nGraduate.\n\nE D U C A T I O N\nBA Psychology"))
        self.assertFalse(looks_like_cv("Meeting notes\nWe discussed the budget and the skills workshop."))

    def test_fix_this_with_a_cv_goes_to_the_cv_model_as_a_training_request(self):
        import app.routers.chat as chat
        from app.agents.base import AgentResponse
        asked = []
        run = lambda question, *args: asked.append(question) or AgentResponse(answer="Sorry.", sources=[])
        with mock.patch.object(AGENTS["internship_career"], "run", run):
            chat.restructure_cv("fix this", "student", [], CV, "01_senior_12_years.txt")
            chat.restructure_cv("Use the Modern template for my CV", "student", [], CV, "cv.txt")
        self.assertEqual(asked, [chat.CV_REQUEST, "Use the Modern template for my CV"])

    def test_cv_file_names(self):
        from app.routers.chat import CV_FILE_NAME
        for name in ["cv1.docx", "Farah_CV.pdf", "resume_2025.docx", "سيرة ذاتية.docx"]:
            self.assertTrue(CV_FILE_NAME.search(name), name)
        self.assertFalse(CV_FILE_NAME.search("annual_report.docx"))

    def test_word_file_as_simple_pdf(self):
        import io
        import pymupdf
        from docx import Document
        from app.documents.formats import document_pdf
        document = Document()
        document.add_heading("Omar Khalil", level=1)
        document.add_paragraph("Administrative Assistant", style="List Bullet")
        table = document.add_table(rows=1, cols=2)
        table.cell(0, 0).text, table.cell(0, 1).text = "Excel", "Advanced"
        out = io.BytesIO()
        document.save(out)
        text = pymupdf.open(stream=document_pdf(".docx", out.getvalue()), filetype="pdf")[0].get_text()
        for expected in ["Omar Khalil", "Administrative Assistant", "Excel", "Advanced"]:
            self.assertIn(expected, text)

    def test_cv_model_only_for_cv_rewrites(self):
        import app.agents.internship_career as career_module
        from app import config
        used = []
        reply = lambda messages, models, *args, **kwargs: used.append(models[0]) or "Template: Student\n\nOmar"
        with mock.patch.object(base, "retrieve_best", return_value=[]), \
             mock.patch.object(base, "chat_with_backup", reply), mock.patch.object(career_module, "chat_with_backup", reply), \
             mock.patch.object(config, "CAREER_MODEL", "ollama/giu-cv"):
            AGENTS["internship_career"].run("What is the difference between the templates?", "student", [], None)
            AGENTS["internship_career"].run("fix my cv", "student", [], CV)
        self.assertNotEqual(used[0], "ollama/giu-cv")   # a general question: the normal models
        self.assertEqual(used[1], "ollama/giu-cv")      # a CV rewrite: the CV model


if __name__ == "__main__":
    unittest.main()
