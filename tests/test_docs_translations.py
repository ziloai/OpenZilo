"""Regression checks for English explanations accidentally copied into Chinese pages."""
import unittest

try:
    from tools.check_docs import shared_english_prose
except ModuleNotFoundError:
    shared_english_prose = None


@unittest.skipUnless(shared_english_prose, "Documentation dependencies are not installed")
class DocumentationTranslationTests(unittest.TestCase):
    def test_copied_paragraph_is_rejected(self):
        text = "The SDK verifies the signature and displays all package metadata before connecting."
        self.assertEqual(shared_english_prose(text, text), [text])

    def test_table_explanations_are_checked(self):
        text = "| API | Description |\n| --- | --- |\n| `inspect()` | Verify a signed firmware package and display its complete metadata offline. |\n"
        self.assertTrue(shared_english_prose(text, text))

    def test_code_examples_and_api_identifiers_are_allowed(self):
        example = '```python\n# These examples intentionally use the same Python syntax in both languages.\nprint("The SDK verifies the signature and displays all package metadata before connecting.")\n```\n\n`inspect_firmware_bundle(bundle, trusted_public_key=key)`\n'
        self.assertEqual(shared_english_prose(example, example), [])

    def test_translated_explanation_is_accepted(self):
        english = "The SDK verifies the signature and displays all package metadata before connecting."
        chinese = "SDK 在连接设备前验证签名，并展示固件包的完整元数据。"
        self.assertEqual(shared_english_prose(chinese, english), [])
