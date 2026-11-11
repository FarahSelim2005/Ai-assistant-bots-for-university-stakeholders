"""Which of a university's assistants a question is sent to. Embeddings are stubbed: no API
request is made, and GIU's four assistants come from tests/giu_agents.py (no database)."""
import unittest
from unittest.mock import patch

import numpy as np

from app.agents import directory
from app.agents.directory import closest_agent, suggest_agent
from tests import giu_agents

ID = giu_agents.ID


def scores_for(key: str) -> np.ndarray:
    """Description scores where `key` clearly wins (in the assistants' order)."""
    return np.array([0.8 if agent.settings.template_key == key else 0.4 for agent in giu_agents.AGENTS.values()])


class SuggestAgentTest(unittest.TestCase):
    def setUp(self):
        giu_agents.activate(self)

    def scores(self, key):
        return patch.object(directory, "description_scores", return_value=scores_for(key))

    def test_staff_get_a_working_link_to_career(self):
        # "How to prepare for an interview" asked to HR by a staff member
        with self.scores("internship_career"):
            link = suggest_agent("how to prepare for an interview", ID["hr_policies"], "staff")
        self.assertEqual((link.agent, link.url), (ID["internship_career"], f"/?agent={ID['internship_career']}"))
        self.assertEqual(link.name, "Internship & Career Assistant")
        self.assertTrue(link.available)

    def test_students_are_told_about_hr_without_a_button(self):
        with self.scores("hr_policies"):
            link = suggest_agent("how many days of annual leave do I get", ID["internship_career"], "student")
        self.assertEqual(link.agent, ID["hr_policies"])
        self.assertFalse(link.available)

    def test_no_link_to_the_current_agent(self):
        with self.scores("hr_policies"):
            self.assertIsNone(suggest_agent("how many days of annual leave", ID["hr_policies"], "staff"))

    def test_closest_agent_is_an_id(self):
        with self.scores("labs_research"):
            self.assertEqual(closest_agent("where is the gym?"), ID["labs_research"])

    def test_hidden_assistants_are_never_suggested(self):
        hidden = giu_agents.giu_agent_from_code("hr_policies", agent_id=giu_agents.AGENTS["hr_policies"].id, live=False)
        agents = [hidden if a.settings.template_key == "hr_policies" else a for a in giu_agents.AGENTS.values()]
        with patch.object(directory, "directory_agents", return_value=[a for a in agents if a.live]), \
             patch.object(directory, "description_scores", return_value=np.array([0.4, 0.8, 0.4])):
            link = suggest_agent("how to prepare for an interview", ID["labs_research"], "staff")
        self.assertEqual(link.agent, ID["internship_career"])  # the 2nd of the 3 live ones, not HR

    def test_one_assistant_suggests_nothing(self):
        with patch.object(directory, "directory_agents", return_value=[giu_agents.AGENTS["labs_research"]]):
            self.assertIsNone(suggest_agent("anything", ID["labs_research"], "student"))


class DescriptionVectors(unittest.TestCase):
    def test_stored_embeddings_are_used_and_new_ones_saved(self):
        stored = giu_agents.giu_agent_from_code("labs_research", description_embedding=(1.0, 0.0))
        new = giu_agents.giu_agent_from_code("hr_policies", description="Something new to embed")
        saved = []
        with patch.object(directory, "embed_texts", return_value=[[0.0, 1.0]]) as embed, \
             patch.object(directory, "save_embeddings", lambda agents: saved.extend(a.display_name for a in agents)):
            vectors = directory.description_vectors([stored, new])
            directory.description_vectors([stored, new])  # the new vector is now known: no second request
        np.testing.assert_array_equal(vectors, [[1.0, 0.0], [0.0, 1.0]])
        embed.assert_called_once_with(["Something new to embed"])
        self.assertEqual(saved, ["HR & Policies Assistant"])
        directory._vectors_by_text.pop("Something new to embed", None)


if __name__ == "__main__":
    unittest.main()
