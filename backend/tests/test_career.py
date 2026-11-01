"""Tests for the Internship & Career agent's CV rewrites (no model, search or database used).

Run from the backend folder:
    python -m unittest discover -s tests -v
"""
import unittest
from unittest import mock

import app.agents.base as base
from app.agents import AGENTS
from app.attachments import Attachment
from app.rag.prompts import ARABIC_LETTERS, CAREER_SYSTEM_PROMPT, ENGLISH_ONLY

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
                                              f"\n\nATTACHMENT FROM THE USER (cv.txt):\n{CV.text}"
                                              + ("" if ARABIC_LETTERS.search(request) else ENGLISH_ONLY)},
                {"role": "user", "content": request},
            ])
        self.search.assert_not_called()

    def test_other_career_questions_still_search(self):
        self.career.run("How do I prepare for an interview?", "student", HISTORY, None)
        self.career.run("Please analyze my CV and suggest improvements.", "student", HISTORY, CV)  # a review
        self.assertTrue(self.search.called)
        self.assertGreater(len(self.sent[-1]), 2)  # history is kept


class CvFiles(unittest.TestCase):
    def test_cut_links_are_completed_from_the_pdf_links(self):
        from app.agents.internship_career import complete_links
        cv = "\n".join(["Farah Selim", "github.com/FarahSelim", "",
                        "Links: https://github.com/FarahSelim2005, https://www.linkedin.com/in/farah-selim-81"])
        answer = "github.com/FarahSelim | linkedin.com/in/farah-selim | https://github.com/FarahSelim2005 | github.com/other"
        self.assertEqual(complete_links(answer, cv), "https://github.com/FarahSelim2005 | https://www.linkedin.com/in/farah-selim-81 | "
                                                     "https://github.com/FarahSelim2005 | github.com/other")

    def test_headings_are_not_left_at_a_page_bottom(self):
        from app.documents.cv_file import cv_pdf, render_cv, stranded_headings
        lines = ["Template: Student", "", "FARAH SELIM", "CS Student", "", "SUMMARY", "Student.", "", "EXPERIENCE"]
        for i in range(9):
            lines += [f"ROLE {i}, 2020 - 2021", "Company", "- Built things", "- Led things"]
        cv = "\n".join(lines + ["", "PROJECTS", "Project A", "- Did A", "", "SKILLS", "- Python"])
        self.assertTrue(stranded_headings(render_cv(cv, set())))   # this layout strands a heading ...
        self.assertFalse(stranded_headings(cv_pdf(cv)))             # ... and cv_pdf moves it to the next page


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
