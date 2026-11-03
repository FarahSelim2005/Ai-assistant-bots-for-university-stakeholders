"""Which agent a question is sent to. Embeddings are stubbed: no API request is made."""
import unittest
from unittest.mock import patch

import numpy as np

from app.agents.directory import AGENT_DIRECTORY, suggest_agent


def scores_for(key: str) -> np.ndarray:
    """Description scores where `key` clearly wins."""
    return np.array([0.8 if a.key == key else 0.4 for a in AGENT_DIRECTORY])


class SuggestAgentTest(unittest.TestCase):
    def test_staff_are_told_about_career_without_a_button(self):
        # "How to prepare for an interview" asked to HR by a staff member
        with patch("app.agents.directory.description_scores", return_value=scores_for("internship_career")):
            link = suggest_agent("how to prepare for an interview", "hr_policies", "staff")
        self.assertEqual(link.agent, "internship_career")
        self.assertFalse(link.available)

    def test_students_get_a_working_link(self):
        with patch("app.agents.directory.description_scores", return_value=scores_for("internship_career")):
            link = suggest_agent("how to prepare for an interview", "labs_research", "student")
        self.assertTrue(link.available)

    def test_no_link_to_the_current_agent(self):
        with patch("app.agents.directory.description_scores", return_value=scores_for("hr_policies")):
            self.assertIsNone(suggest_agent("how many days of annual leave", "hr_policies", "staff"))


if __name__ == "__main__":
    unittest.main()
