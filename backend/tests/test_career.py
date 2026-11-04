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
        # The analysis has numbers that are not in the CV ("6/10", "2 projects"): they stay
        import app.agents.internship_career as career_module
        answer = f"Template: Student\n{ENGLISH_CV}\n- Led 87 people\n\n{ENGLISH_ANALYSIS}"
        attachment = Attachment("cv.txt", text=ENGLISH_CV)
        with mock.patch.object(career_module, "chat_with_backup", return_value=answer):
            result = AGENTS["internship_career"].generate("fix my cv", [], [], attachment)
        self.assertIn("- Led [add the number] people", result)  # invented in the CV: replaced
        self.assertTrue(result.endswith(ENGLISH_ANALYSIS))

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
