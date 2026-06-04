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
from backlog import Backlog
from config import load_config
from lease import LeaseTable


def _root(args) -> Path:
    return Path(args.root).resolve()


def cmd_init(args):
    Backlog(_root(args)).init()
    print(f"initialized backlog at {_root(args) / 'backlog'}")


def cmd_add(args):
    tid = Backlog(_root(args)).add(
        args.title, type=args.type, source=args.source, priority=args.priority
    )
    print(tid)


def cmd_classify(args):
    Backlog(_root(args)).classify(
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
    wt = dispatch_mod.dispatch(_root(args), args.id)
    print(f"{args.id} -> active @ {wt}")


def cmd_dispatch_auto(args):
    ids = dispatch_mod.dispatch_auto(_root(args))
    print("dispatched: " + (", ".join(ids) if ids else "(none)"))


def cmd_integrate(args):
    res = integrate_mod.integrate(_root(args), args.id)
    print(json.dumps(res, ensure_ascii=False))
    sys.exit(0 if res.get("ok") else 1)


def cmd_gc(args):
    rec = gc_mod.gc(_root(args))
    print("reclaimed: " + (", ".join(r["task"] for r in rec) if rec else "(none)"))


def cmd_heartbeat(args):
    LeaseTable(_root(args)).heartbeat(args.id)
    print(f"{args.id} heartbeat updated")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cwo", description="Claude Work Orchestrator")
    p.add_argument("--root", default=".", help="project root containing backlog/")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init").set_defaults(func=cmd_init)

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
    i.set_defaults(func=cmd_integrate)

    sub.add_parser("gc").set_defaults(func=cmd_gc)

    hb = sub.add_parser("heartbeat")
    hb.add_argument("id")
    hb.set_defaults(func=cmd_heartbeat)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
