from html.parser import HTMLParser
from pathlib import Path
import unittest


class _BenchmarkMetricsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_benchmark = False
        self.capture: str | None = None
        self.current_label = ""
        self.metrics: dict[str, str] = {}
        self.definition_counts: list[int] = []
        self.current_definition_count: int | None = None
        self.protocol_label = ""
        self.scope_note = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "section" and attributes.get("id") == "benchmark":
            self.in_benchmark = True
        elif self.in_benchmark and tag == "div" and "metric-row" in (attributes.get("class") or "").split():
            self.current_definition_count = 0
        elif self.in_benchmark and tag == "dd" and self.current_definition_count is not None:
            self.current_definition_count += 1
            self.capture = "dd" if self.current_definition_count == 1 else None
        elif self.in_benchmark and tag == "dt":
            self.capture = tag
        elif self.in_benchmark and tag == "small":
            self.capture = "protocol"
        elif self.in_benchmark and tag == "p" and "benchmark-method" in (attributes.get("class") or "").split():
            self.capture = "scope"

    def handle_endtag(self, tag: str) -> None:
        if self.in_benchmark and tag == "section":
            self.in_benchmark = False
        elif self.in_benchmark and tag == "div" and self.current_definition_count is not None:
            self.definition_counts.append(self.current_definition_count)
            self.current_definition_count = None
        elif self.in_benchmark and tag in {"dt", "dd"}:
            self.capture = None
        elif self.in_benchmark and tag in {"small", "p"}:
            self.capture = None

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text or not self.in_benchmark:
            return
        if self.capture == "dt":
            self.current_label = text
        elif self.capture == "dd" and self.current_label:
            self.metrics[self.current_label] = text
        elif self.capture == "protocol":
            self.protocol_label = text
        elif self.capture == "scope":
            self.scope_note = text


class PagesTests(unittest.TestCase):
    def test_comparative_metrics_remain_explicitly_unmeasured(self) -> None:
        parser = _BenchmarkMetricsParser()
        parser.feed(Path("docs/index.html").read_text(encoding="utf-8"))

        self.assertEqual(
            {
                "Token delta": "Not measured",
                "Wall-clock delta": "Not measured",
                "Acceptance quality": "Not measured",
            },
            parser.metrics,
        )
        self.assertEqual([2, 2, 2], parser.definition_counts)
        self.assertEqual("Schedule, not outcome.", parser.protocol_label)
        self.assertIn("Codex-only", parser.scope_note)
        self.assertIn("future work", parser.scope_note)


if __name__ == "__main__":
    unittest.main()
