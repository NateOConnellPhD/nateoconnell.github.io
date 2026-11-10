"""Focused regression checks: identity, incomplete responses, and hidden work."""
import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location("publications", Path(__file__).with_name("update-publications.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
AUTHOR = "https://openalex.org/A123"


def work(number=1, title="An example paper"):
    return {"id": "https://openalex.org/W%d" % number, "title": title,
            "publication_date": "2025-04-10", "cited_by_count": 12,
            "doi": "https://doi.org/10.1234/example", "type": "article",
            "authorships": [{"author": {"id": AUTHOR, "display_name": "Nathaniel S. O’Connell"}}],
            "primary_location": {"source": {"display_name": "Example journal"}}}


class PublicationTests(unittest.TestCase):
    def test_identity_must_agree_across_known_papers(self):
        other = copy.deepcopy(work())
        other["authorships"][0]["author"]["id"] = "https://openalex.org/A999"
        config = {"author_names": ["Nathaniel S. O'Connell"], "identity_dois": ["one", "two", "three"]}
        with patch.object(module, "get_json", side_effect=[{"results": [work()]}, {"results": [other]}, {"results": [work()]}]):
            with self.assertRaisesRegex(ValueError, "verify one author"):
                module.author_id(config)

    def test_incomplete_response_does_not_overwrite_snapshot(self):
        output = Mock()
        responses = [{"meta": {"count": 2}, "results": [work()]}, {"meta": {"count": 2}, "results": []}]
        with patch.object(module, "OUTPUT", output), patch.object(module, "author_id", return_value=AUTHOR), patch.object(module, "get_json", side_effect=responses):
            with self.assertRaisesRegex(ValueError, "Incomplete"):
                module.refresh()
        output.write_text.assert_not_called()

    def test_hidden_lasso_work_is_excluded_and_counts_stay_numeric(self):
        import json
        output = Mock()
        hidden = work(2, "Stability of LASSO Coefficients under Cross-Validation")
        with patch.object(module, "OUTPUT", output), patch.object(module, "author_id", return_value=AUTHOR), patch.object(module, "fetch_works", return_value=[work(), hidden]):
            module.refresh()
        snapshot = json.loads(output.write_text.call_args[0][0])
        self.assertEqual(len(snapshot["items"]), 1)
        self.assertEqual(snapshot["items"][0]["citations"], 12)

    def test_pagination_collects_every_record(self):
        responses = [{"meta": {"count": 2}, "results": [work()]}, {"meta": {"count": 2}, "results": [work(2)]}]
        with patch.object(module, "get_json", side_effect=responses):
            self.assertEqual(len(module.fetch_works(AUTHOR)), 2)

    def test_invalid_citation_count_is_not_silently_zero(self):
        item = work()
        item["cited_by_count"] = None
        with self.assertRaisesRegex(ValueError, "citation count"):
            module.publication(item)


if __name__ == "__main__":
    unittest.main()
