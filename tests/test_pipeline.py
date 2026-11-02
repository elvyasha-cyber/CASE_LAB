import json
import shutil
from pathlib import Path

from case_lab.cli import main
from case_lab.extract import build_extractor, parse_model_json, render_prompt, load_prompt_template
from case_lab.loaders import load_goldens, read_json, read_jsonl
from case_lab.pipeline import run_pipeline
from case_lab.report import compare_to_golden, write_report
from case_lab.report import _first_business


def test_exam_set_files_match(root: Path):
    inbox = {path.stem for path in (root / "data" / "inbox").glob("*.json")}
    cassettes = {path.stem for path in (root / "data" / "cassettes").glob("*.json")}
    golden = {path.stem for path in (root / "data" / "golden").glob("*.json")}
    assert inbox == cassettes == golden
    assert len(inbox) == 10
    for path in (root / "data" / "cassettes").glob("*.json"):
        payload = read_json(path)
        assert payload["model"] == "fixture/simulation"


def test_exam_run_matches_golden_and_never_posts(root: Path, tmp_path: Path):
    result = run_pipeline(root=root, out_dir=tmp_path)
    business = _first_business(result.records)
    mismatches = compare_to_golden(business, load_goldens(root / "data" / "golden"))
    assert mismatches == []

    orders = list((tmp_path / "orders").glob("*.json"))
    assert len(orders) == 3
    for path in orders:
        order = read_json(path)
        assert order["status"] == "draft"
        assert order["posting"] == "forbidden"
        assert order["approval"]["auto_posting"] is False
        assert "body" not in order

    assert not (tmp_path / "orders").joinpath("MSG-004.json").exists()
    escalation = read_json(tmp_path / "escalations" / "ESC-2026-0002.json")
    assert escalation["not_approved"] is True
    assert escalation["commercial_status"] == "preview_not_approved"

    action_blob = "\n".join(
        path.read_text(encoding="utf-8")
        for path in tmp_path.rglob("*")
        if path.is_file() and path.name != "audit.jsonl"
    )
    assert "Количество не указываю" not in action_blob
    audit = read_jsonl(tmp_path / "audit.jsonl")
    by_id = {record["message_id"]: record for record in audit}
    assert "Претензий нет" in by_id["MSG-009"]["input"]["body"]
    assert by_id["MSG-009"]["status"] == "close_no_action"
    assert by_id["MSG-001"]["result"]["escalate"] is False
    assert by_id["MSG-002"]["result"]["escalate"] is True
    assert by_id["MSG-002"]["result"]["next_action"] == "передать менеджеру"

    first = read_json(tmp_path / "orders" / "ORD-2026-0001.json")
    assert first["lines"][0]["price_rub"] == 420
    assert first["total_rub"] == 6100

    text = write_report(tmp_path, root)
    assert "10/10" in text
    assert "115 229" in text


def test_repeat_does_not_create_a_second_order_and_a_changed_letter_is_not_rewritten(root: Path, tmp_path: Path):
    inbox = tmp_path / "inbox"
    shutil.copytree(root / "data" / "inbox", inbox)
    out = tmp_path / "out"
    run_pipeline(root=root, inbox_dir=inbox, out_dir=out)
    run_pipeline(root=root, inbox_dir=inbox, out_dir=out)
    assert len(list((out / "orders").glob("*.json"))) == 3
    second = read_jsonl(out / "audit.jsonl")
    assert sum(record["decision"] == "skip_duplicate" for record in second) == 10

    letter = inbox / "MSG-001.json"
    payload = read_json(letter)
    payload["body"] = payload["body"] + "\nДобавили строку после решения."
    letter.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    run_pipeline(root=root, inbox_dir=inbox, out_dir=out)
    assert len(list((out / "orders").glob("*.json"))) == 3
    decisions = [record["decision"] for record in read_jsonl(out / "audit.jsonl") if record["message_id"] == "MSG-001"]
    assert decisions[0] == "create_draft"
    assert decisions[-1] == "source_changed"


def test_bad_model_output_does_not_abort_the_batch(root: Path, tmp_path: Path, policy):
    inbox = tmp_path / "inbox"
    cassettes = tmp_path / "cassettes"
    inbox.mkdir()
    cassettes.mkdir()
    shutil.copy(root / "data" / "inbox" / "MSG-001.json", inbox / "MSG-001.json")
    shutil.copy(root / "data" / "cassettes" / "MSG-001.json", cassettes / "MSG-001.json")
    (inbox / "MSG-404.json").write_text(
        json.dumps(
            {
                "id": "MSG-404",
                "received_at": "2026-10-26T15:00:00+03:00",
                "from": "zakup@ladoga-office.example",
                "subject": "Пусто",
                "body": "Есть письмо, нет ответа модели.",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (inbox / "MSG-BAD.json").write_text(
        json.dumps(
            {
                "id": "MSG-BAD",
                "received_at": "2026-10-26T15:05:00+03:00",
                "from": "zakup@ladoga-office.example",
                "subject": "Битый ответ",
                "body": "Ответ модели без обязательных полей.",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (cassettes / "MSG-BAD.json").write_text(
        json.dumps({"model": "fixture/simulation", "extraction": {"intent": "order"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (inbox / "MSG-BROKEN.json").write_text("{", encoding="utf-8")

    result = run_pipeline(root=root, inbox_dir=inbox, cassette_dir=cassettes, out_dir=tmp_path / "out")
    by_id = {record["message_id"]: record for record in result.records}
    assert by_id["MSG-001"]["decision"] == "create_draft"
    assert by_id["MSG-404"]["reasons"][0]["code"] == "extractor_unavailable"
    assert by_id["MSG-BAD"]["reasons"][0]["code"] == "schema_invalid"
    assert by_id["MSG-BROKEN"]["reasons"][0]["code"] == "source_invalid"
    assert (tmp_path / "out" / "orders" / "ORD-2026-0001.json").exists()


def test_prompt_is_bound_into_the_audit_and_changes_with_the_letter(root: Path, policy, catalog, registry):
    template = load_prompt_template(policy)
    first = render_prompt(template, _email(root, "MSG-001"), catalog, registry)
    second = render_prompt(template, _email(root, "MSG-009"), catalog, registry)
    assert first[2] != second[2]
    assert "PROMPT_VERSION: order-extract-v4" in template
    assert policy.temperature == 0.2


def test_fenced_json_and_live_mode_without_a_key(policy, monkeypatch):
    payload = parse_model_json('```json\n{"intent": "not_order"}\n```')
    assert payload["intent"] == "not_order"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    try:
        build_extractor(Path("."), policy, mode="live")
    except RuntimeError as exc:
        assert "OPENAI_API_KEY" in str(exc)
    else:
        raise AssertionError("live без ключа не должен запускаться")


def test_cli_demo(root: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CASE_LLM", "replay")
    code = main(["demo", "--out", str(tmp_path / "out")])
    assert code == 0
    assert (tmp_path / "out" / "report.md").exists()
    report = (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    assert "fixture/simulation" in report


def _email(root: Path, message_id: str):
    from case_lab.schemas import InboundEmail

    return InboundEmail.model_validate(read_json(root / "data" / "inbox" / f"{message_id}.json"))
