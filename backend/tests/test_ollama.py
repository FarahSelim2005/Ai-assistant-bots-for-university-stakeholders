"""The request sent to the local CV model (Ollama is stubbed: no model is called)."""
import unittest
from unittest import mock

from app import config
from app.llm import client


class RawPromptForCvModel(unittest.TestCase):
    def test_cv_rewrite_is_sent_as_a_raw_prompt_in_the_training_format(self):
        sent = []
        answer = mock.Mock(**{"json.return_value": {"response": "</tool_call>\n\nTemplate: Student\nOmar"}})
        with mock.patch.object(client._ollama, "post", lambda path, json: sent.append((path, json)) or answer):
            text = client.chat_ollama([{"role": "system", "content": "RULES\nCV"},
                                       {"role": "user", "content": "Rewrite my CV."}], "giu-cv", 1500)
        path, body = sent[0]
        self.assertEqual(path, "/api/generate")
        self.assertEqual(body["prompt"], "<|im_start|>system\nRULES\nCV<|im_end|>\n"
                                         "<|im_start|>user\nRewrite my CV.<|im_end|>\n<|im_start|>assistant\n")
        self.assertTrue(body["raw"])
        self.assertEqual(body["options"], {"num_predict": 1500, "num_ctx": config.OLLAMA_FULL_NUM_CTX,
                                           "temperature": 0.1, "stop": ["<|im_end|>"]})
        self.assertEqual(text, "</tool_call>\n\nTemplate: Student\nOmar")  # the agent strips the tag lines

    def test_empty_answer_is_an_error(self):
        answer = mock.Mock(**{"json.return_value": {"response": "  "}})
        with mock.patch.object(client._ollama, "post", return_value=answer), self.assertRaises(client.LLMError):
            client.chat_ollama([{"role": "user", "content": "x"}], "giu-cv", 10)


if __name__ == "__main__":
    unittest.main()
