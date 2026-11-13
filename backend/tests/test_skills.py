"""Skills and prompts built from parts (step 2b). No database, model or embedding service:
assistants are made from app/agents/templates.py, and the chat route's database and agents
are replaced by stand-ins.

Run from the backend folder:
    python -m unittest discover -s tests -v
"""
import base64
import unittest
import uuid
from unittest import mock

import app.agents.base as base
from app import tenants
from app.agents import agent_from_template, giu_agent_from_code
from app.agents.base import AgentResponse
from app.agents.internship_career import CvAgent
from app.agents.templates import TEMPLATES
from app.attachments import Attachment
from app.llm import client
from app.rag.prompts import CAREER_SYSTEM_PROMPT, LABS_SYSTEM_PROMPT, build_messages
from app.routers import chat, documents
from app.schemas import ChatRequest

DEMO = tenants.Tenant(uuid.UUID(int=2), "demo", "Demo University", short_name="DU")
WITH_CV_AND_MAP = tenants.Tenant(uuid.UUID(int=3), "other", "Other University", short_name="OU",
                                 has_cv_model=True, campus_map=True)


class ComposedPrompts(unittest.TestCase):
    def test_other_universities_never_see_giu(self):
        for t in TEMPLATES:
            agent = agent_from_template(t["key"], DEMO)
            texts = [agent.system_prompt, agent.fallback_message, agent.fallback_message_ar,
                     build_messages(agent.system_prompt, "q", [], university=agent.university)[0]["content"]]
            for text in texts:
                self.assertNotIn("GIU", text, t["key"])
                self.assertNotIn("German International", text, t["key"])
                self.assertNotIn("{university}", text, t["key"])
            self.assertIn(f"You are the {t['name']} of Demo University (DU).", agent.system_prompt)
            self.assertIn("(no matching DU documents)", texts[3])

    def test_answer_modes(self):
        docs = agent_from_template("labs_research", DEMO).system_prompt
        advice = agent_from_template("internship_career", DEMO).system_prompt
        self.assertIn("Answer ONLY using the information in the CONTEXT", docs)
        self.assertIn('start such parts with "General advice:"', advice)
        self.assertNotIn("Answer ONLY using", advice)

    def test_skills_add_their_rules(self):
        everything = agent_from_template("labs_research", WITH_CV_AND_MAP).system_prompt
        nothing = agent_from_template("labs_research", DEMO, skills=()).system_prompt
        self.assertIn("room codes in Latin letters", everything)       # map skill + campus map
        self.assertIn("An attachment comes from the user", everything)  # files / images
        self.assertNotIn("room codes", nothing)
        self.assertNotIn("attachment", nothing)
        self.assertNotIn("room codes", agent_from_template("labs_research", DEMO).system_prompt)  # no campus map

    def test_complete_prompts_are_used_as_written(self):
        mine = agent_from_template("labs_research", DEMO, prompt_mode="complete", instructions="Only this, at {university}.")
        self.assertEqual(mine.system_prompt, "Only this, at DU.")

    def test_giu_is_unchanged(self):
        self.assertEqual(giu_agent_from_code("labs_research").system_prompt, LABS_SYSTEM_PROMPT)
        self.assertEqual(giu_agent_from_code("internship_career").system_prompt, CAREER_SYSTEM_PROMPT)
        self.assertEqual(build_messages("X", "q", [])[0]["content"].split("\n")[3], "(no matching GIU documents)")


class Skills(unittest.TestCase):
    def test_cv_skill_at_every_university(self):
        self.assertIsInstance(agent_from_template("internship_career", DEMO), CvAgent)  # no trained CV model needed
        self.assertTrue(agent_from_template("internship_career", DEMO).rewrites_cvs)
        self.assertIsInstance(agent_from_template("internship_career", WITH_CV_AND_MAP), CvAgent)
        self.assertIsInstance(giu_agent_from_code("internship_career"), CvAgent)
        self.assertNotIsInstance(giu_agent_from_code("internship_career", skills=("files",)), CvAgent)

    def test_map_only_with_the_skill_and_a_campus_map(self):
        self.assertTrue(giu_agent_from_code("labs_research").campus_map)
        self.assertFalse(agent_from_template("labs_research", DEMO).campus_map)            # no campus map
        self.assertFalse(giu_agent_from_code("labs_research", skills=("files",)).campus_map)  # no map skill

    def run_agent(self, agent, question):
        """agent.run with retrieval and the model replaced: (response, the system prompt sent)."""
        sent = []
        reply = lambda messages, models, *args, **kwargs: sent.append(messages) or "It is room M005 in building M."
        with mock.patch.object(base, "retrieve_best", return_value=[]), mock.patch.object(base, "chat_with_backup", reply), \
             mock.patch.object(base, "suggest_agent", return_value=None), \
             mock.patch.object(base.BaseAgent, "owner_by_documents", return_value=None):
            response = agent.run(question, "student")
        return response, (sent[0][0]["content"] if sent else "")

    def test_campus_code_runs_only_with_the_map(self):
        giu, sent = self.run_agent(giu_agent_from_code("internship_career"), "Where is M005?")
        self.assertIn("Room numbering rules", giu.sources)       # GIU: the room's facts from the numbering rules
        self.assertEqual([l.room for l in giu.locations], ["M005"])
        demo, sent = self.run_agent(agent_from_template("internship_career", DEMO), "Where is M005?")
        self.assertEqual((demo.sources, demo.locations, demo.places, demo.buildings), ([], [], [], []))
        self.assertNotIn("building M", sent)  # no GIU campus facts in another university's prompt

    def test_attachments_need_their_skill(self):
        text_only = agent_from_template("labs_research", DEMO, skills=("files",))
        nothing = agent_from_template("labs_research", DEMO, skills=())
        picture = Attachment("photo.png", image_urls=["data:image/png;base64,AA"])
        document = Attachment("notes.txt", text="Some notes")
        with self.assertRaisesRegex(ValueError, "does not read pictures"):
            text_only.check_rules("what is this?", "student", picture)
        text_only.check_rules("what is this?", "student", document)  # allowed
        with self.assertRaisesRegex(ValueError, "does not read files"):
            nothing.check_rules("what is this?", "student", document)

    def test_local_model_prompt_has_the_university(self):
        self.assertTrue(client.local_system_prompt().startswith("You are a GIU university assistant."))  # no tenant
        with tenants.using(DEMO):
            self.assertTrue(client.local_system_prompt().startswith("You are a DU university assistant."))


class ChatRouting(unittest.TestCase):
    """POST /chat's choice between answering, editing and CV rewriting follows the skills."""

    def answer(self, agent, query, filename=None, content=b"Education\nB.Sc.\n\nExperience\nIntern\n"):
        class Conn:
            def __enter__(self): return self
            def __exit__(self, *exc): return False

            def execute(self, sql, params):
                result = mock.Mock()
                result.fetchone.return_value = ("student", agent.id)
                result.fetchall.return_value = []
                return result

        body = {"conversation_id": 1, "query": query}
        if filename:
            body["attachments"] = [{"filename": filename, "data_base64": base64.b64encode(content).decode()}]
        calls = []
        with tenants.using(agent.tenant), mock.patch.object(chat, "get_connection", lambda tenant_id: Conn()), \
             mock.patch.object(chat.usage, "check_allowance"), mock.patch.object(chat.usage, "check_subscription"), \
             mock.patch.object(chat, "load_agent", return_value=agent), \
             mock.patch.object(chat, "restructure_cv", lambda *args: calls.append("cv rewrite") or chat.Outcome(AgentResponse("", []))), \
             mock.patch.object(chat, "edit", lambda *args, **kwargs: calls.append("editor") or chat.Outcome(AgentResponse("", []))), \
             mock.patch.object(type(agent), "run", lambda self, *args: calls.append("answer") or AgentResponse("", [])):
            chat.answer_question(ChatRequest(**body))
        return calls

    def test_cv_rewrite_at_every_university(self):
        self.assertEqual(self.answer(giu_agent_from_code("internship_career"), "fix my cv", "cv.txt"), ["cv rewrite"])
        self.assertEqual(self.answer(agent_from_template("internship_career", DEMO), "fix my cv", "cv.txt"), ["cv rewrite"])
        without = agent_from_template("internship_career", DEMO, skills=("files", "images", "editor"))
        self.assertEqual(self.answer(without, "fix my cv", "cv.txt"), ["editor"])  # no "cv" skill: an ordinary edit

    def test_cv_instructions_in_the_universitys_name(self):
        from app.agents.internship_career import cv_instructions
        from app.rag.prompts import CAREER_SYSTEM_PROMPT
        self.assertEqual(cv_instructions(giu_agent_from_code("internship_career").tenant), CAREER_SYSTEM_PROMPT)  # GIU: as trained
        ngu = tenants.Tenant(uuid.uuid4(), "ngu", "New Giza University", short_name="NGU")
        text = cv_instructions(ngu)
        self.assertNotIn("GIU", text)
        self.assertNotIn("German International", text)
        self.assertIn("New Giza University (NGU)", text)
        self.assertIn("NGU CV templates", text)

    def test_editing_only_with_the_editor_skill(self):
        with_editor = agent_from_template("labs_research", DEMO)
        without = agent_from_template("labs_research", DEMO, skills=("files", "images"))
        self.assertEqual(self.answer(with_editor, "translate this file to Arabic", "notes.txt", b"Hello"), ["editor"])
        self.assertEqual(self.answer(without, "translate this file to Arabic", "notes.txt", b"Hello"), ["answer"])

    def test_editing_route_refused_without_the_editor_skill(self):
        without = agent_from_template("labs_research", DEMO, skills=("files",))
        with mock.patch.object(documents, "conversation_assistant", return_value=without), \
             self.assertRaises(documents.HTTPException) as refused:
            documents.require_conversation(1)
        self.assertEqual(refused.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
