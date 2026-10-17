from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from extract import (  # noqa: E402
    ExtractionError,
    _parse_json,
    call_anthropic,
    call_openai,
)


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class ExtractionTests(unittest.TestCase):
    def test_missing_provider_keys_raise_controlled_errors(self):
        with mock.patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": ""},
            clear=False,
        ):
            with self.assertRaisesRegex(ExtractionError, "OPENAI_API_KEY"):
                call_openai("fixture")
            with self.assertRaisesRegex(ExtractionError, "ANTHROPIC_API_KEY"):
                call_anthropic("fixture")

    def test_invalid_model_output_is_not_echoed_in_error(self):
        private_output = "private beneficiary details without JSON"

        with self.assertRaises(ExtractionError) as error:
            _parse_json(private_output)

        self.assertNotIn(private_output, str(error.exception))

    def test_malformed_provider_response_has_controlled_error(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-key"}), \
                mock.patch(
                    "urllib.request.urlopen",
                    return_value=_Response({"choices": []}),
                ):
            with self.assertRaisesRegex(ExtractionError, "response shape"):
                call_openai("fixture")


if __name__ == "__main__":
    unittest.main()
