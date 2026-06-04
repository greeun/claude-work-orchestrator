#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cwo_gc as gc_mod
import dispatch as dispatch_mod
import integrate as integrate_mod
import runner as runner_mod
import web as web_mod
from backlog import Backlog
from config import load_config
from lease import LeaseTable
from lock import project_lock


def _root(args) -> Path:
    return Path(args.root).resolve()


def cmd_init(args):
    root = _root(args)
    Backlog(root).init()
    if getattr(args, "auto_redispatch", False):
        cfg_path = root / "backlog" / "config.json"
        data = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
        data["auto_redispatch"] = True
        cfg_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    if (root / ".git").exists() and not (root / ".gitignore").exists():
        print(
            "warning: no .gitignore in this git repo. "
            "Ensure build/test artifacts (e.g. __pycache__/, *.pyc) are gitignored — "
            "otherwise the integration gate's test_command can pollute the tree "
            "and make integrate's merge fail."
        )
    print(f"initialized backlog at {root / 'backlog'}")


def cmd_add(args):
    root = _root(args)
    with project_lock(root):
        tid = Backlog(root).add(
            args.title, type=args.type, source=args.source, priority=args.priority
        )
    print(tid)


def cmd_classify(args):
    root = _root(args)
    with project_lock(root):
        Backlog(root).classify(
            args.id, touches=args.touches or [],
            depends_on=args.depends_on or [], auto=args.auto,
        )
    print(f"{args.id} -> ready")


def cmd_list(args):
    for t in Backlog(_root(args)).list(args.status):
        dep = f" deps={t['depends_on']}" if t["depends_on"] else ""
        print(f"{t['id']} [{t['status']}] {t['title']} touches={t['touches']}{dep}")


def cmd_leases(args):
    for l in LeaseTable(_root(args)).active():
        print(f"{l['task']} touches={l['touches']} wt={l['worktree']}")


def cmd_check(args):
    root = _root(args)
    bl, lt, cfg = Backlog(root), LeaseTable(root), load_config(root)
    ok, reason = dispatch_mod.can_dispatch(bl, lt, cfg, bl.get(args.id))
    print(f"{'OK' if ok else 'NO'}: {reason}")
    sys.exit(0 if ok else 1)


def cmd_dispatch(args):
    root = _root(args)
    with project_lock(root):
        wt = dispatch_mod.dispatch(root, args.id)
    print(f"{args.id} -> active @ {wt}")


def cmd_dispatch_auto(args):
    root = _root(args)
    with project_lock(root):
        ids = dispatch_mod.dispatch_auto(root)
    print("dispatched: " + (", ".join(ids) if ids else "(none)"))


def _should_redispatch(root, flag) -> bool:
    if flag is not None:
        return flag
    return load_config(root).auto_redispatch


def cmd_integrate(args):
    root = _root(args)
    with project_lock(root):
        res = integrate_mod.integrate(root, args.id)
        if res.get("ok") and _should_redispatch(root, args.redispatch):
            res["redispatched"] = dispatch_mod.dispatch_auto(root)
    print(json.dumps(res, ensure_ascii=False))
    sys.exit(0 if res.get("ok") else 1)


def cmd_gc(args):
    root = _root(args)
    with project_lock(root):
        rec = gc_mod.gc(root)
        if _should_redispatch(root, args.redispatch):
            ids = dispatch_mod.dispatch_auto(root)
        else:
            ids = None
    print("reclaimed: " + (", ".join(r["task"] for r in rec) if rec else "(none)"))
    if ids is not None:
        print("redispatched: " + (", ".join(ids) if ids else "(none)"))


def cmd_heartbeat(args):
    root = _root(args)
    with project_lock(root):
        LeaseTable(root).heartbeat(args.id)
    print(f"{args.id} heartbeat updated")


def cmd_loop_status(args):
    print(json.dumps(dispatch_mod.loop_status(_root(args)), ensure_ascii=False, indent=2))


def cmd_run(args):
    root = _root(args)
    executor = runner_mod.command_executor(args.executor) if args.executor else None
    try:
        summary = runner_mod.run_loop(
            root, executor, max_iters=args.max_iters, dry_run=args.dry_run, log=print)
    except ValueError as e:
        print(f"error: {e}")
        sys.exit(2)
    print(json.dumps(summary, ensure_ascii=False))


def cmd_serve(args):
    web_mod.serve(_root(args), host=args.host, port=args.port)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cwo", description="Claude Work Orchestrator")
    p.add_argument("--root", default=".", help="project root containing backlog/")
    sub = p.add_subparsers(dest="cmd", required=True)

    init_p = sub.add_parser("init")
    init_p.add_argument("--auto-redispatch", dest="auto_redispatch", action="store_true")
    init_p.set_defaults(func=cmd_init)

    a = sub.add_parser("add")
    a.add_argument("title")
    a.add_argument("--type", default="feature")
    a.add_argument("--source", default="human")
    a.add_argument("--priority", default="medium")
    a.set_defaults(func=cmd_add)

    c = sub.add_parser("classify")
    c.add_argument("id")
    c.add_argument("--touches", nargs="*")
    c.add_argument("--depends-on", dest="depends_on", nargs="*")
    c.add_argument("--auto", action="store_true")
    c.set_defaults(func=cmd_classify)

    ls = sub.add_parser("list")
    ls.add_argument("--status")
    ls.set_defaults(func=cmd_list)

    sub.add_parser("leases").set_defaults(func=cmd_leases)

    ch = sub.add_parser("check")
    ch.add_argument("id")
    ch.set_defaults(func=cmd_check)

    d = sub.add_parser("dispatch")
    d.add_argument("id")
    d.set_defaults(func=cmd_dispatch)

    sub.add_parser("dispatch-auto").set_defaults(func=cmd_dispatch_auto)

    i = sub.add_parser("integrate")
    i.add_argument("id")
    i.add_argument("--redispatch", action=argparse.BooleanOptionalAction, default=None)
    i.set_defaults(func=cmd_integrate)

    gc_p = sub.add_parser("gc")
    gc_p.add_argument("--redispatch", action=argparse.BooleanOptionalAction, default=None)
    gc_p.set_defaults(func=cmd_gc)

    hb = sub.add_parser("heartbeat")
    hb.add_argument("id")
    hb.set_defaults(func=cmd_heartbeat)

    sub.add_parser("loop-status").set_defaults(func=cmd_loop_status)

    rn = sub.add_parser("run")
    rn.add_argument("--executor", help="shell template; prompt via $CWO_PROMPT env. e.g. 'claude -p \"$CWO_PROMPT\"'")
    rn.add_argument("--max-iters", dest="max_iters", type=int, default=50)
    rn.add_argument("--dry-run", dest="dry_run", action="store_true")
    rn.set_defaults(func=cmd_run)

    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8787)
    sv.set_defaults(func=cmd_serve)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
