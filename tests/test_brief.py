"""S0: per-run brief — single source of truth for a run."""
import pytest
from gtm.brief import load_brief

BRIEF = """---
run: teal-demo
urls:
  - https://tealdrones.com
---
Notes for this run.
"""

BRIEF_QUERY = """---
run: drone-search
query: companies that sell drones
max_companies: 3
---
"""

BRIEF_EMPTY = """---
run: nothing
---
"""


def test_loads_url_brief_with_defaults(tmp_path):
    f = tmp_path / "brief.md"
    f.write_text(BRIEF)
    b = load_brief(f)
    assert b.run == "teal-demo"
    assert b.urls == ["https://tealdrones.com"]
    assert b.scraper == "crawl4ai"     # locked default
    assert b.max_companies == 10       # sane default


def test_loads_query_brief(tmp_path):
    f = tmp_path / "brief.md"
    f.write_text(BRIEF_QUERY)
    b = load_brief(f)
    assert b.query == "companies that sell drones"
    assert b.max_companies == 3


def test_rejects_brief_with_no_input(tmp_path):
    f = tmp_path / "brief.md"
    f.write_text(BRIEF_EMPTY)
    with pytest.raises(ValueError, match="urls or query"):
        load_brief(f)
