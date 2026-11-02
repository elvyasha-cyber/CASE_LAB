"""Команды кейса: demo для записи экрана, live/serve — боевой контур с точками подключения."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from case_lab.adapters.base import AdapterNotConfigured
from case_lab.config import get_settings
from case_lab.loaders import load_goldens, project_root, read_jsonl
from case_lab.pipeline import run_pipeline
from case_lab.report import _first_business, compare_to_golden, write_report
from case_lab.runtime import run_live_batch


def main(argv: list[str] | None = None) -> int:
    _utf8_stdout()
    parser = argparse.ArgumentParser(
        prog="case_lab",
        description="Кейс «СеверСнаб»: от письма клиента до черновика заказа или эскалации.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="Запись демо: фикстуры LLM, файловый вход, отчёт.")
    demo.add_argument("--inbox", type=Path, default=None)
    demo.add_argument("--out", type=Path, default=None)

    run_cmd = sub.add_parser("run", help="Прогон ящика без очистки out/ (режим LLM из .env).")
    run_cmd.add_argument("--inbox", type=Path, default=None)
    run_cmd.add_argument("--out", type=Path, default=None)

    live = sub.add_parser("live", help="Боевой контур: .env → вход/LLM/уведомление.")
    live.add_argument("--inbox", type=Path, default=None)
    live.add_argument("--out", type=Path, default=None)

    serve = sub.add_parser("serve", help="HTTP-вход POST /ingest (нужен пакет api).")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    report = sub.add_parser("report", help="Собрать отчёт по уже записанному журналу.")
    report.add_argument("--out", type=Path, default=None)

    args = parser.parse_args(argv)
    root = project_root()
    out_dir = getattr(args, "out", None) or (root / "out")
    inbox = getattr(args, "inbox", None) or (root / "data" / "inbox")

    if args.command == "demo":
        if out_dir.exists():
            shutil.rmtree(out_dir)
        run_pipeline(root=root, inbox_dir=inbox, out_dir=out_dir, mode="replay")
        return _print_report(out_dir, root)

    if args.command == "run":
        settings = get_settings()
        result = run_pipeline(
            root=root,
            inbox_dir=inbox,
            out_dir=out_dir,
            mode=settings.case_llm,
        )
        for record in result.records:
            reasons = ",".join(item["code"] for item in record["reasons"]) or "—"
            print(f"{record['message_id']}  {record['decision']}  {record['action_id'] or '—'}  {reasons}")
        return 0

    if args.command == "live":
        try:
            result = run_live_batch(root=root, inbox_dir=inbox, out_dir=out_dir)
        except AdapterNotConfigured as exc:
            print(str(exc))
            return 2
        for record in result.records:
            reasons = ",".join(item["code"] for item in record["reasons"]) or "—"
            print(f"{record['message_id']}  {record['decision']}  {record['action_id'] or '—'}  {reasons}")
        print("Уведомления менеджеру: out/notifications/ (если CASE_NOTIFY=file).")
        return 0

    if args.command == "serve":
        return _serve(args.host, args.port)

    return _print_report(out_dir, root)


def _print_report(out_dir: Path, root: Path) -> int:
    try:
        text = write_report(out_dir, root)
    except FileNotFoundError as exc:
        print(str(exc))
        return 1
    print(text)
    print(f"Отчёт записан: {out_dir / 'report.md'}")
    business = _first_business(read_jsonl(out_dir / "audit.jsonl"))
    mismatches = compare_to_golden(business, load_goldens(root / "data" / "golden"))
    return 1 if mismatches else 0


def _serve(host: str, port: int) -> int:
    try:
        import uvicorn
    except ImportError:
        print('Для serve установите: python -m pip install -e ".[api]"')
        return 2
    print(f"HTTP-вход: http://{host}:{port}/ingest")
    print(f"Health:    http://{host}:{port}/health")
    uvicorn.run("case_lab.adapters.inbox_http:get_app", factory=True, host=host, port=port)
    return 0


def _utf8_stdout() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(encoding="utf-8")
    except Exception:
        return
