"""The answer language: English questions get English context and an English-only note."""
import unittest

from app.rag.prompts import ENGLISH_ONLY, HR_SYSTEM_PROMPT, build_messages
from app.rag.retriever import RetrievedChunk

CHUNK = RetrievedChunk(
    "## Annual leave (by law) - From the second year: 21 days per year. "
    "بالعربي: من السنة التانية 21 يوم في السنة. "
    "## Maternity leave (by law) 120 days. بالعربي: إجازة الوضع 120 يوم.",
    "hr_policies.md", 0.7)


class AnswerLanguageTest(unittest.TestCase):
    def test_english_question_gets_no_arabic_copy(self):
        system = build_messages(HR_SYSTEM_PROMPT, "How long is annual leave?", [CHUNK])[0]["content"]
        context = system.split("CONTEXT:")[1]
        self.assertNotIn("بالعربي", context)
        self.assertIn("21 days per year", context)
        self.assertIn("## Maternity leave (by law) 120 days.", context)
        self.assertTrue(system.endswith(ENGLISH_ONLY))

    def test_arabic_question_keeps_everything(self):
        system = build_messages(HR_SYSTEM_PROMPT, "الإجازة السنوية كام يوم؟", [CHUNK])[0]["content"]
        self.assertIn("بالعربي: من السنة التانية", system)
        self.assertNotIn(ENGLISH_ONLY, system)


if __name__ == "__main__":
    unittest.main()
