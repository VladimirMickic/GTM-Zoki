"""Slice 6 — token rendering. Run test-batch-1 pushed drafts containing literal
{{first_name}} / {{sender_name}} to the real Sheet and HubSpot, because
gtm/output.py substituted a single-brace UPPERCASE vocabulary ({FIRST_NAME})
that no prompt has ever emitted. These tests lock the real one.
"""
from gtm.render import (
    OutreachConfig,
    load_outreach_config,
    pick_reference_customer,
    render_tokens,
    unrendered_tokens,
)
from gtm.schema import Prospect


def test_render_tokens_double_brace_lowercase():
    out = render_tokens("{{first_name}}, saw {{company_name}}'s launch.",
                        {"first_name": "Jane", "company_name": "Red Cat"})
    assert out == "Jane, saw Red Cat's launch."


def test_render_tokens_tolerates_inner_whitespace():
    assert render_tokens("Hi {{ first_name }}", {"first_name": "Jane"}) == "Hi Jane"


def test_render_tokens_leaves_unknown_tokens_alone_for_the_gate_to_catch():
    assert render_tokens("Hi {{nickname}}", {"first_name": "Jane"}) == "Hi {{nickname}}"


def test_render_tokens_leaves_a_token_whose_value_is_empty():
    # An empty value is missing data, not a render — blanking it silently is how a
    # half-filled email ships.
    assert render_tokens("— {{sender_name}}", {"sender_name": ""}) == "— {{sender_name}}"


def test_render_tokens_ignores_the_old_single_brace_vocabulary():
    assert render_tokens("Hi {FIRST_NAME}", {"first_name": "Jane"}) == "Hi {FIRST_NAME}"


def test_unrendered_tokens_lists_survivors():
    assert unrendered_tokens("Hi {{first_name}} — {{sender_name}}") == [
        "{{first_name}}", "{{sender_name}}"
    ]
    assert unrendered_tokens("Hi Jane") == []


def test_load_outreach_config_reads_the_repo_file():
    # 2026-07-29: the sender was filled in so the pushed rows could ship, so this no
    # longer asserts emptiness — it asserts the live file still parses into a usable
    # config. A sender that silently stops parsing blocks every row in every run.
    cfg = load_outreach_config()
    assert cfg.sender_name and "todo" not in cfg.sender_name.lower()
    # 2026-07-31: 3 fictional demo references approved (repo's AeroVault is itself
    # fictional). Assert non-empty and clean rather than a fixed list, so adding or
    # renaming an approved reference doesn't break this test.
    assert cfg.reference_customers
    assert all("todo" not in name.lower() for name in cfg.reference_customers)
    # Singular on purpose — drafts are written around one company name in the slot.
    assert cfg.fallback_reference == "a defense sUAS maker we work with"


def test_load_outreach_config_parses_filled_values(tmp_path):
    path = tmp_path / "outreach.md"
    path.write_text(
        "## Sender\n"
        "- name: Vladimir Mickic\n"
        "- title: Founder, AeroVault Cases\n"
        "- email: v@aerovault.example\n"
        "\n## Approved reference customers\n"
        "- Skyward Robotics\n"
        "- Northwind UAS\n"
        "\n## Fallback reference\n"
        "- fallback: defense sUAS makers we work with\n"
    )
    cfg = load_outreach_config(path)
    assert cfg.sender_name == "Vladimir Mickic"
    assert cfg.sender_title == "Founder, AeroVault Cases"
    assert cfg.reference_customers == ["Skyward Robotics", "Northwind UAS"]


def test_pick_reference_customer_never_returns_the_recipient():
    cfg = OutreachConfig(reference_customers=["Red Cat Holdings", "Northwind UAS"],
                         fallback_reference="defense sUAS makers we work with")
    p = Prospect(company="Red Cat Holdings", website="https://redcatholdings.com")
    assert pick_reference_customer(p, cfg, []) == "Northwind UAS"


def test_pick_reference_customer_never_returns_a_run_mate():
    cfg = OutreachConfig(reference_customers=["Easy Aerial", "Northwind UAS"],
                         fallback_reference="defense sUAS makers we work with")
    p = Prospect(company="Red Cat", website="https://redcatholdings.com")
    assert pick_reference_customer(p, cfg, ["Easy Aerial", "Red Cat"]) == "Northwind UAS"


def test_pick_reference_customer_falls_back_to_the_category_phrase():
    cfg = OutreachConfig(reference_customers=["Easy Aerial"],
                         fallback_reference="defense sUAS makers we work with")
    p = Prospect(company="Red Cat", website="https://redcatholdings.com")
    assert pick_reference_customer(p, cfg, ["Easy Aerial"]) == "defense sUAS makers we work with"


def test_pick_reference_customer_returns_empty_when_nothing_is_configured():
    p = Prospect(company="Red Cat", website="https://redcatholdings.com")
    assert pick_reference_customer(p, OutreachConfig(), []) == ""


def test_build_render_context_fills_every_draft_token():
    from gtm.render import DRAFT_TOKENS, build_render_context

    p = Prospect(
        company="Red Cat", website="https://redcatholdings.com",
        drone_models=["Black Widow", "Teal 2"],
        best_case_line="AV-Field",
        buying_signals=["Hiring 4 field-ops techs — expanding deployments (linkedin, 2026-07-01)"],
        trigger_phrase="a new field-ops hiring push",
    )
    cfg = OutreachConfig(sender_name="Vladimir Mickic", fallback_reference="a defense sUAS maker we work with")
    ctx = build_render_context(p, first_name="Jeff", config=cfg, run_mates=[])
    assert set(DRAFT_TOKENS) <= set(ctx)
    assert ctx["first_name"] == "Jeff"
    assert ctx["company_name"] == "Red Cat"
    assert ctx["airframe_name"] == "Black Widow"
    assert ctx["case_line"] == "AV-Field"
    assert ctx["sender_name"] == "Vladimir Mickic"
    # The signals stage writes the phrase; render never derives one from a signal line.
    assert ctx["trigger_event"] == "a new field-ops hiring push"


def test_build_render_context_skips_a_stale_signal_for_the_trigger():
    from gtm.render import build_render_context

    p = Prospect(
        company="Red Cat", website="https://redcatholdings.com",
        buying_signals=[
            "FANG cleared Blue UAS — (defensenews, 2025-03-01) [stale]",
            "Hiring 4 field-ops techs — (linkedin, 2026-07-01)",
        ],
        trigger_phrase="a new field-ops hiring push",
    )
    ctx = build_render_context(p, first_name="Jeff", config=OutreachConfig(), run_mates=[])
    assert ctx["trigger_event"] == "a new field-ops hiring push"


def test_build_render_context_leaves_the_trigger_empty_when_every_signal_is_stale():
    from gtm.render import build_render_context

    p = Prospect(
        company="Red Cat", website="https://redcatholdings.com",
        buying_signals=["FANG cleared Blue UAS — (defensenews, 2025-03-01) [stale]"],
    )
    ctx = build_render_context(p, first_name="Jeff", config=OutreachConfig(), run_mates=[])
    assert ctx["trigger_event"] == ""  # no fresh trigger → the token survives → gated


def test_first_name_falls_back_to_there():
    from gtm.render import build_render_context

    p = Prospect(company="Red Cat", website="https://redcatholdings.com")
    ctx = build_render_context(p, first_name="", config=OutreachConfig(), run_mates=[])
    assert ctx["first_name"] == "there"


# --- 2026-07-29: two defects that only showed up in the RENDERED output -------------------

def test_render_capitalizes_a_fill_that_lands_at_a_sentence_start():
    from gtm.render import render_tokens

    ctx = {"reference_customer": "a defense sUAS maker we work with"}
    out = render_tokens("US-made. {{reference_customer}} orders theirs this way.", ctx)
    assert out == "US-made. A defense sUAS maker we work with orders theirs this way."


def test_render_leaves_a_mid_sentence_fill_lowercase():
    from gtm.render import render_tokens

    ctx = {"reference_customer": "a defense sUAS maker we work with"}
    out = render_tokens("Crews at {{reference_customer}} pack from one.", ctx)
    assert out == "Crews at a defense sUAS maker we work with pack from one."


def test_render_capitalizes_at_the_very_start_and_after_a_question_mark():
    from gtm.render import render_tokens

    assert render_tokens("{{first_name}} — hello.", {"first_name": "there"}) == "There — hello."
    assert render_tokens("Worth it? {{x}} thinks so.", {"x": "a maker"}) == "Worth it? A maker thinks so."


def test_render_never_capitalizes_an_unresolved_token():
    from gtm.render import render_tokens

    # The braces have to survive verbatim — output.py greps for them to block the row.
    assert render_tokens("Done. {{reference_customer}} likes it.", {}) == "Done. {{reference_customer}} likes it."


def test_trigger_event_comes_from_trigger_phrase_never_from_a_signal_line():
    from gtm.render import _trigger_event

    # The exact us-drone-19 signal that rendered "Saw Asylon's Awarded an Air Force Phase
    # Three contract to test DroneDog and ground robots networked into a single inspection
    # system — congrats." into the live sheet.
    signal = (
        "Awarded an Air Force Phase Three contract to test DroneDog and ground robots "
        "networked into a single inspection system — real, recent awarded work "
        "(Philadelphia Inquirer, 2026-07-13)"
    )
    p = Prospect(company="Asylon", website="https://asylonrobotics.com", buying_signals=[signal])
    assert _trigger_event(p) == ""  # no phrase written yet — block, don't mangle
    p.trigger_phrase = "Air Force Phase Three award"
    assert _trigger_event(p) == "Air Force Phase Three award"


def test_trigger_phrase_is_withheld_when_every_signal_is_stale_or_undated():
    from gtm.render import _trigger_event

    p = Prospect(
        company="Harris Aerial", website="https://harrisaerial.com",
        buying_signals=["Joined the Blue UAS Cleared List — (instagram) [undated]"],
        trigger_phrase="the Blue UAS listing",
    )
    # A phrase left over from before its signal aged out must not still open an email.
    assert _trigger_event(p) == ""
