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
        self.assertTrue(result.endswith("Most important to improve:\n1. Add 2 projects\n2. Add a link to your LinkedIn profile."))

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
    "Most important to improve:", "1. Add details to your cashier role", "2. State the role you are looking for",
    "Section by section:", "- Summary: short"])


class AnalysisCheck(unittest.TestCase):
    """The CV ANALYSIS is corrected against the CV it describes (no model is called)."""

    def test_cv_without_linkedin(self):
        from app.documents.cv_analysis import check_analysis
        self.assertEqual(check_analysis(OVERPRAISING_ANALYSIS, NO_LINKEDIN_CV), "\n".join([
            "CV ANALYSIS", "Rating: 5/10 - Needs work", "Target length: 1 page", "What I changed:", "- Reordered sections",
            "Strengths:", "- Clear education section with dates",  # links, levels and numbers: not in the CV
            "Most important to improve:", "1. Add details to your cashier role", "2. State the role you are looking for",
            "3. Add a link to your LinkedIn profile.",
            "Section by section:", "- Summary: short"]))

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
        self.assertEqual(checked, analysis.replace("9/10 - ممتاز", "7/10 - CV كويس بس فيه شوية حاجات ناقصة"))


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
            "looking for.\n", "looking for.\n4. Add a link to your LinkedIn profile.\n"))

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
            .replace("- [add details about what you did]", "- Served customers")
        analysis = "\n".join(["CV ANALYSIS", "Rating: 9/10 - Strong CV", "Strengths:",
                              "- You list a good range of skills.",          # only 3 skills
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
        self.assertIn("2. ضيف لينك الـ LinkedIn بتاعك.", checked)

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
            "2. ضيف تدريب أو شغل part-time لما تقدر.",
            "تحليل كل جزء:", "- الخبرات: لسه مفيش تدريب أو شغل."])


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
