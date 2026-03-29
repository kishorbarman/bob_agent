import unittest

from media_utils import detect_document_type


class MediaUtilsTests(unittest.TestCase):
    def test_detect_document_type(self):
        self.assertEqual(detect_document_type("application/pdf", "file.bin"), "pdf")
        self.assertEqual(detect_document_type("", "report.pdf"), "pdf")
        self.assertEqual(detect_document_type("image/png", "x"), "image")
        self.assertEqual(detect_document_type("text/plain", "x"), "text")
        self.assertEqual(detect_document_type("application/zip", "x.zip"), "unsupported")


if __name__ == "__main__":
    unittest.main()
