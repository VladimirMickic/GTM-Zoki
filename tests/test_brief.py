"""S0: per-run brief — single source of truth for a run."""
import json

import pytest
from gtm.brief import Brief, freeze_brief, load_brief, load_frozen

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


def test_freeze_brief_writes_lock_matching_model_dump(tmp_path):
    brief = Brief(run="teal-demo", urls=["https://tealdrones.com"])
    lock_path = freeze_brief(brief, tmp_path)
    assert lock_path == tmp_path / "brief.lock.json"
    assert json.loads(lock_path.read_text()) == brief.model_dump()


def test_freeze_brief_is_idempotent_noop_for_same_brief(tmp_path):
    brief = Brief(run="teal-demo", urls=["https://tealdrones.com"])
    first = freeze_brief(brief, tmp_path)
    before = first.read_text()
    second = freeze_brief(brief, tmp_path)
    assert second == first
    assert second.read_text() == before
    assert load_frozen(tmp_path) == brief


def test_freeze_brief_raises_on_different_content(tmp_path):
    brief = Brief(run="teal-demo", urls=["https://tealdrones.com"])
    freeze_brief(brief, tmp_path)
    changed = Brief(run="teal-demo", urls=["https://tealdrones.com/other"])
    with pytest.raises(ValueError, match="brief already frozen"):
        freeze_brief(changed, tmp_path)
