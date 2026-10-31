"""Document editor: edit an uploaded .docx, .xlsx, .pptx, .pdf, .txt or .md file with a
plain-language instruction ("correct the grammar", "translate to Arabic", "convert this
PDF to Word") and return the edited file.

- formats.py: reads each format into numbered text parts and applies edits to exactly
  those parts in the original file, so formatting, tables, images and layout are kept.
- editor.py:  asks the existing chat models which parts to change (JSON only; the model
  never runs code or touches files) and applies the answer.
- storage.py: keeps the current version per conversation for follow-up edits and
  downloads, under random names, and deletes old files.
"""
