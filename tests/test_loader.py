"""Loading the data folder: every file is read or the load is refused. Nothing is skipped without a word.

python3 -m unittest discover -s tests   (standard library only)
"""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "source"))
os.environ.setdefault("MODEL_PROVIDER", "mock")

from loader import load  # noqa: E402
from rfp import answer as engine  # noqa: E402
from rfp import store  # noqa: E402

DATA = os.path.join(ROOT, "data")


class LoadFolder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def put(self, name, src=None, data=b"PK\x03\x04 not text"):
        path = os.path.join(self.tmp, name)
        if src:
            shutil.copy(os.path.join(DATA, src), path)
        else:
            open(path, "wb").write(data)

    def test_sample_data_still_loads(self):
        self.assertTrue(store.all_clauses(load()))

    def test_amendment_saved_as_word_stops_the_load(self):
        # Before this check the .docx was skipped and the answer was the superseded $20,000, with no warning.
        self.put("rfp_sample.txt", "rfp_sample.txt")
        self.put("rfp_sample_amendment_1.docx")
        with self.assertRaises(store.UnreadableDocument) as e:
            engine.answer(load(self.tmp), "What is the bid deposit?")
        self.assertIn("rfp_sample_amendment_1.docx", str(e.exception))

    def test_every_unread_file_is_named(self):
        self.put("rfp_sample.txt", "rfp_sample.txt")
        for name in ("addendum.pdf", "notes.md", "scan.png"):
            self.put(name)
        with self.assertRaises(store.UnreadableDocument) as e:
            load(self.tmp)
        for name in ("addendum.pdf", "notes.md", "scan.png"):
            self.assertIn(name, str(e.exception))

    def test_subfolder_stops_the_load(self):
        self.put("rfp_sample.txt", "rfp_sample.txt")
        os.mkdir(os.path.join(self.tmp, "amendments"))
        with self.assertRaises(store.UnreadableDocument) as e:
            load(self.tmp)
        self.assertIn("amendments", str(e.exception))

    def test_hidden_files_are_not_documents(self):
        self.put("rfp_sample.txt", "rfp_sample.txt")
        self.put(".DS_Store")
        self.assertTrue(store.all_clauses(load(self.tmp)))


if __name__ == "__main__":
    unittest.main()
