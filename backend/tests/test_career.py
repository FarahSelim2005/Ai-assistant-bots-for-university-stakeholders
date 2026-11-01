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
        self.patches = [mock.patch.object(base, "chat_with_backup", reply),
                        mock.patch.object(base, "retrieve_best", return_value=[])]
        self.search = self.patches[1].start()
        self.patches[0].start()
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


if __name__ == "__main__":
    unittest.main()
