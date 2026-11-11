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


class ErrorReasons(unittest.TestCase):
    """describe() never fails, whatever error format the server sends (a crash there once
    broke the Ollama warm-up at start-up)."""

    def reason(self, status: int, body: bytes) -> str:
        import httpx
        response = httpx.Response(status, content=body, request=httpx.Request("POST", "http://x/api/chat"))
        return client.describe(httpx.HTTPStatusError("failed", request=response.request, response=response))

    def test_every_error_format(self):
        self.assertEqual(self.reason(404, b'{"error": "model gemma3:1b not found"}'), "404 model gemma3:1b not found")  # Ollama
        self.assertEqual(self.reason(429, b'{"error": {"message": "Rate limit exceeded"}}'), "429 Rate limit exceeded")  # OpenRouter
        self.assertEqual(self.reason(502, b"<html>Bad gateway</html>"), "502 <html>Bad gateway</html>")
        self.assertEqual(self.reason(500, b'["unexpected"]'), "500 ['unexpected']")
        self.assertEqual(self.reason(503, b"{}"), "503")

    def test_warm_up_logs_instead_of_crashing(self):
        import httpx
        response = httpx.Response(404, json={"error": "model 'gemma3:1b' not found"},
                                  request=httpx.Request("POST", "http://localhost:11434/api/chat"))
        with mock.patch.object(client._ollama, "post", return_value=response), self.assertLogs("uvicorn.error", "WARNING") as logs:
            client.warm_up_ollama()
        self.assertIn("404 model 'gemma3:1b' not found", logs.output[0])


if __name__ == "__main__":
    unittest.main()
