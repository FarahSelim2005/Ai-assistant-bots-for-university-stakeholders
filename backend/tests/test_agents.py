"""Configured assistants (app/agents/configured.py) and the registry (app/agents/__init__.py).
No database or model: GIU's assistants come from tests/giu_agents.py, and agents_of() is
replaced where a test needs the database's answer.

Run from the backend folder:
    python -m unittest discover -s tests -v
"""
import unittest
import uuid
from datetime import datetime, timezone
from unittest import mock

import app.agents as registry
from app import config
from app.agents import GIU_TENANT, agent_from_template, find_agent, giu_agent_from_code
from app.agents.configured import AgentSettings, ConfiguredAgent
from app.agents.internship_career import CvAgent
from app.rag.prompts import ADVISING_SYSTEM_PROMPT, CAREER_SYSTEM_PROMPT, HR_SYSTEM_PROMPT, LABS_SYSTEM_PROMPT
from app.rag.retriever import RetrievedChunk
from tests import giu_agents


class GiuAssistants(unittest.TestCase):
    """GIU's four assistants behave as the four fixed agent classes did."""

    def test_same_prompts_models_and_rules(self):
        expected = {"graduation_advising": (ADVISING_SYSTEM_PROMPT, ("student", "staff"), False, 400),
                    "hr_policies": (HR_SYSTEM_PROMPT, ("staff",), False, 400),
                    "internship_career": (CAREER_SYSTEM_PROMPT, ("student", "staff"), True, 1500),
                    "labs_research": (LABS_SYSTEM_PROMPT, ("student", "staff"), False, 400)}
        for key, agent in giu_agents.AGENTS.items():
            prompt, users, advice, tokens = expected[key]
            self.assertEqual((agent.system_prompt, agent.allowed_user_types, agent.answers_without_documents,
                              agent.max_answer_tokens, agent.full_local_prompt), (prompt, users, advice, tokens, False), key)
            self.assertEqual((agent.model, agent.backup_models, agent.vision_model, agent.vision_backup_models),
                             (config.LABS_MODEL, config.LABS_BACKUP_MODELS, config.VISION_MODEL, config.VISION_BACKUP_MODELS))
            self.assertTrue(agent.fallback_message.startswith("Sorry, I don't have information about that."))
        self.assertIsInstance(giu_agents.AGENTS["internship_career"], CvAgent)  # the cv skill: CV rewrites
        self.assertNotIsInstance(giu_agents.AGENTS["labs_research"], CvAgent)

    def test_name_is_the_id_for_retrieval(self):
        labs = giu_agents.AGENTS["labs_research"]
        self.assertEqual((labs.name, labs.display_name), ("a0000000-0000-4000-8000-000000000004", "Labs & Research Assistant"))


class Settings(unittest.TestCase):
    def test_own_threshold_and_models(self):
        chunks = [RetrievedChunk("a", "a.md", 0.50), RetrievedChunk("b", "b.md", 0.40)]
        default = agent_from_template("labs_research")
        strict = agent_from_template("labs_research", similarity_threshold=0.45, model="x/model", backup_models=("y/b",))
        with mock.patch.object(config, "SIMILARITY_THRESHOLD", 0.48):
            self.assertEqual([c.source for c in default.validate(chunks)], ["a.md"])
        self.assertEqual([c.source for c in strict.validate(chunks)], ["a.md"])
        self.assertEqual([c.source for c in agent_from_template("labs_research", similarity_threshold=0.3).validate(chunks)],
                         ["a.md", "b.md"])
        self.assertEqual((strict.model, strict.backup_models), ("x/model", ["y/b"]))

    def test_rows_become_settings(self):
        agent_id, tenant_id = uuid.uuid4(), uuid.uuid4()
        row = (agent_id, tenant_id, None, "Library Helper", "", "", "Books", ["student"], "docs", "Help.", "Sorry.", "",
               "", "", ["Where is the library?"], ["files"], 400, None, [], None, 1, True, [0.5, 0.5],
               "composed", "library_helper", datetime.now(timezone.utc))
        settings = AgentSettings.from_row(row)
        self.assertEqual((settings.audiences, settings.examples, settings.skills, settings.description_embedding),
                         (("student",), ("Where is the library?",), ("files",), (0.5, 0.5)))
        agent = registry.make_agent(settings, GIU_TENANT)
        self.assertIs(type(agent), ConfiguredAgent)
        with self.assertRaisesRegex(ValueError, "Library Helper is not available for 'staff'"):
            agent.check_rules("hi", "staff")


class Registry(unittest.TestCase):
    def test_find_by_id_or_template_key(self):
        with giu_agents.active():
            tenant = giu_agents.GIU.id
            self.assertEqual(find_agent(tenant, "hr_policies").display_name, "HR & Policies Assistant")
            self.assertEqual(find_agent(tenant, giu_agents.ID["hr_policies"]).display_name, "HR & Policies Assistant")
            self.assertIsNone(find_agent(tenant, "orientation"))
            self.assertIsNone(find_agent(uuid.uuid4(), "hr_policies"))  # another university has none

    def test_giu_folders_are_its_old_names(self):
        self.assertEqual({key: agent.settings.folder for key, agent in giu_agents.AGENTS.items()},
                         {key: key for key in giu_agents.AGENTS})

    def test_cache_reloads_only_when_rows_change(self):
        tenant = uuid.uuid4()
        row = (tenant, "x", "X University", "active", "X", False, False, None, "#000000", "#000000", "#000000", "", [])
        stamps = [(*row, 1, "t1"), (*row, 1, "t1"), (*row, 1, "t2")]
        loads = []

        class Conn:
            def __enter__(self): return self
            def __exit__(self, *exc): return False

            def execute(self, sql, params):
                result = mock.Mock()
                if "count(a.id)" in sql:
                    result.fetchone.return_value = stamps.pop(0)
                else:
                    loads.append(sql)
                    result.fetchall.return_value = []
                return result

        with mock.patch.object(registry, "get_connection", lambda tenant_id: Conn()):
            for _ in range(3):
                registry.agents_of(tenant)
        self.assertEqual(len(loads), 2)  # first call, and after the stamp changed
        registry._cache.pop(tenant, None)


if __name__ == "__main__":
    unittest.main()
