"""Several files sent with one message are read as one attachment."""
import unittest

from app import config
from app.attachments import Attachment, combine_attachments
from app.routers.chat import sent_files
from app.schemas import AttachmentIn, ChatRequest

FILE = AttachmentIn(filename="a.txt", data_base64="aGk=")


class SeveralFiles(unittest.TestCase):
    def test_texts_and_pictures_are_combined(self):
        combined = combine_attachments([Attachment("cv.pdf", text="My CV"), Attachment("job.txt", text="The job"),
                                        Attachment("photo.png", image_urls=["data:image/png;base64,AA"])])
        self.assertEqual(combined.filename, "cv.pdf, job.txt, photo.png")
        self.assertEqual(combined.text, "--- File: cv.pdf ---\nMy CV\n\n--- File: job.txt ---\nThe job")
        self.assertEqual(combined.image_urls, ["data:image/png;base64,AA"])

    def test_long_texts_share_the_limit(self):
        long = "x" * config.MAX_ATTACHMENT_CHARS
        combined = combine_attachments([Attachment(name, text=long) for name in "abcd"])
        self.assertLessEqual(len(combined.text), 2 * config.MAX_ATTACHMENT_CHARS + 200)

    def test_one_file_is_unchanged(self):
        single = Attachment("cv.pdf", text="My CV")
        self.assertIs(combine_attachments([single]), single)

    def test_old_and_new_request_fields(self):
        self.assertEqual(sent_files(ChatRequest(conversation_id=1, query="q", attachment=FILE)), [FILE])
        self.assertEqual(len(sent_files(ChatRequest(conversation_id=1, query="q", attachments=[FILE, FILE]))), 2)
        self.assertEqual(sent_files(ChatRequest(conversation_id=1, query="q")), [])
        with self.assertRaises(ValueError):  # at most MAX_FILES
            ChatRequest(conversation_id=1, query="q", attachments=[FILE] * 6)


if __name__ == "__main__":
    unittest.main()
