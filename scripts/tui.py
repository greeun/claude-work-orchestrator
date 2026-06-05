from __future__ import annotations

import json

from backlog import Backlog
from cwo_gc import gc
from dispatch import dispatch, dispatch_auto, loop_status
from integrate import integrate
from lease import LeaseTable
from lock import project_lock

_ORDER = {"inbox": 0, "ready": 1, "active": 2, "integrating": 2, "done": 3}


def build_state(root) -> dict:
    return {
        "tasks": Backlog(root).list(),
        "leases": LeaseTable(root).active(),
        "loop": loop_status(root),
    }


def selectable_tasks(state) -> list[dict]:
    return sorted(state["tasks"], key=lambda t: (_ORDER.get(t["status"], 9), t["id"]))


def render(state, selection) -> list[str]:
    loop = state["loop"]
    c = loop["counts"]
    lines = [
        f"cwo watch — inbox {c['inbox']} · ready {c['ready']} · "
        f"active {c['active']} · done {c['done']} · progress={loop['loop_can_progress']}",
        "",
    ]
    blocked = {b["id"]: b["reason"] for b in loop["blocked_auto"]}
    items = selectable_tasks(state)
    for i, t in enumerate(items):
        mark = ">" if i == selection else " "
        auto = " *" if t.get("auto") else ""
        extra = ""
        if t["status"] == "ready" and t["id"] in blocked:
            extra = f"  [blocked: {blocked[t['id']]}]"
        elif t["status"] in ("active", "integrating") and t.get("worktree"):
            extra = f"  wt={t['worktree']}"
        lines.append(
            f"{mark} {t['id']} [{t['status']}]{auto} {t['title']}  "
            f"touches={t['touches']}{extra}"
        )
    lines += [
        "",
        f"leases: {[l['task'] for l in state['leases']]}",
        "",
        "[↑/↓ j/k] select  [d]ispatch  [i]ntegrate  [a]uto  [g]c  [r]efresh  [q] quit",
    ]
    return lines


def handle_key(root, key, state, selection) -> dict:
    items = selectable_tasks(state)
    n = len(items)
    res = {"selection": selection, "quit": False, "message": ""}
    if key == "q":
        res["quit"] = True
        return res
    if key == "down":
        res["selection"] = min(selection + 1, n - 1) if n else 0
        return res
    if key == "up":
        res["selection"] = max(selection - 1, 0)
        return res
    if key == "r":
        return res  # caller re-reads state
    if key == "i":  # integrate self-locks — must NOT wrap in project_lock
        if 0 <= selection < n:
            try:
                res["message"] = json.dumps(integrate(root, items[selection]["id"]),
                                            ensure_ascii=False)
            except Exception as e:
                res["message"] = f"error: {e}"
        return res
    if key in ("a", "g", "d"):
        try:
            with project_lock(root):
                if key == "a":
                    ids = dispatch_auto(root)
                    res["message"] = "dispatched: " + (", ".join(ids) if ids else "(none)")
                elif key == "g":
                    rec = gc(root)
                    res["message"] = "reclaimed: " + (
                        ", ".join(r["task"] for r in rec) if rec else "(none)")
                elif key == "d" and 0 <= selection < n:
                    wt = dispatch(root, items[selection]["id"])
                    res["message"] = f"dispatched @ {wt}"
        except Exception as e:
            res["message"] = f"error: {e}"
    return res


def _translate(ch) -> str:
    import curses
    if ch == curses.KEY_UP:
        return "up"
    if ch == curses.KEY_DOWN:
        return "down"
    if 0 <= ch < 256:
        c = chr(ch)
        if c == "j":
            return "down"
        if c == "k":
            return "up"
        return c
    return ""


def watch(root, refresh_secs: float = 2.0) -> None:
    import curses
    import locale
    locale.setlocale(locale.LC_ALL, "")

    def _loop(stdscr):
        curses.curs_set(0)
        stdscr.timeout(int(refresh_secs * 1000))
        selection, message = 0, ""
        while True:
            state = build_state(root)
            n = len(selectable_tasks(state))
            if selection >= n:
                selection = max(0, n - 1)
            lines = render(state, selection)
            if message:
                lines += ["", message]
            stdscr.erase()
            h, w = stdscr.getmaxyx()
            for i, ln in enumerate(lines[: h - 1]):
                try:
                    stdscr.addnstr(i, 0, ln, w - 1)
                except curses.error:
                    pass
            stdscr.refresh()
            ch = stdscr.getch()
            if ch == -1:
                continue  # timeout: just refresh
            r = handle_key(root, _translate(ch), state, selection)
            selection, message = r["selection"], r["message"]
            if r["quit"]:
                break

    curses.wrapper(_loop)
