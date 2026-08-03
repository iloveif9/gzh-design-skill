#!/usr/bin/env python3
"""validate_gzh_html.py 的轻量结构回归测试。"""

import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).with_name("validate_gzh_html.py")
SPEC = importlib.util.spec_from_file_location("validate_gzh_html", MODULE_PATH)
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


class StructureCheckerTest(unittest.TestCase):
    def structure_errors(self, html):
        errors, _, _ = validator.validate(html)
        return [error for error in errors
                if error.startswith("HTML 标签结构错误")]

    def test_valid_nested_html(self):
        html = '<section><p><span leaf="">正文</span></p></section>'
        self.assertFalse(self.structure_errors(html))

    def test_void_and_self_closing_tags_do_not_enter_stack(self):
        html = ('<section><br><img src="x"><svg><path /></svg>'
                '<span leaf="">正文</span></section>')
        self.assertFalse(self.structure_errors(html))

    def test_comments_entities_and_multiple_roots_are_allowed(self):
        html = ('<!-- <section>伪标签</section> -->'
                '<section><span leaf="">&lt;section&gt;</span></section>'
                '<p><span leaf="">第二个根</span></p>')
        self.assertFalse(self.structure_errors(html))

    def test_unclosed_section_reports_opening_and_eof_lines(self):
        errors = self.structure_errors('<section>\n<span leaf="">正文</span>')
        self.assertEqual(len(errors), 1)
        self.assertIn(
            "未闭合标签 <section>：第 1 行开启，至 EOF 第 2 行仍未关闭",
            errors[0],
        )

    def test_mismatched_close_is_an_error(self):
        errors = self.structure_errors(
            '<section><p><span leaf="">正文</span></section>')
        self.assertEqual(len(errors), 1)
        self.assertIn("错序结束标签 </section>", errors[0])
        self.assertIn("应先关闭 <p>", errors[0])

    def test_orphan_close_is_an_error(self):
        errors = self.structure_errors(
            '<section><span leaf="">正文</span></section></article>')
        self.assertEqual(len(errors), 1)
        self.assertIn("孤立结束标签 </article>：第 1 行", errors[0])

    def test_chapter_padding_nesting_pattern_is_detected(self):
        html = """<section style="padding:20px"><span leaf="">第一章</span>
<section style="padding:20px"><span leaf="">第二章</span>
<section style="padding:20px"><span leaf="">第三章</span>"""
        errors = self.structure_errors(html)
        self.assertEqual(len(errors), 1)
        self.assertIn("HTML 标签结构错误 ×3", errors[0])
        self.assertEqual(errors[0].count("未闭合标签 <section>"), 3)

    def test_void_end_tag_is_an_error(self):
        errors = self.structure_errors(
            '<section><span leaf="">正文</span></br></section>')
        self.assertEqual(len(errors), 1)
        self.assertIn("void 标签不能有结束标签", errors[0])

    def test_non_void_html_tag_cannot_self_close(self):
        errors = self.structure_errors('<section />')
        self.assertEqual(len(errors), 1)
        self.assertIn("非法自闭合标签 <section />", errors[0])

    def test_optional_html_end_tags_must_be_explicit_for_gzh_output(self):
        errors = self.structure_errors(
            '<section><p><span leaf="">第一段</span>'
            '<p><span leaf="">第二段</span></p></section>')
        self.assertEqual(len(errors), 1)
        self.assertIn("错序结束标签 </section>", errors[0])


if __name__ == "__main__":
    unittest.main()
