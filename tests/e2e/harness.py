# SPDX-License-Identifier: MIT

import os
import subprocess
import time
import unittest
from pathlib import Path

import pyatspi

WORK = Path(os.environ["E2E_WORK"])
REPO = Path(os.environ["E2E_REPO"])
TREE = Path(os.environ["E2E_TREE"])
LAUNCHER = TREE / "usr" / "bin" / "legion-powerctl-gui"
CLI = TREE / "usr" / "bin" / "legion-powerctl"
DESKTOP_ENTRY = TREE / "usr" / "share" / "applications" / "legion-powerctl.desktop"

APP_NAME = "legion-powerctl"
WAIT = float(os.environ.get("E2E_WAIT", "20"))

INTERACTIVE_ROLES = frozenset({
    "button", "push button", "toggle button", "check box", "radio button", "slider",
    "spin button", "combo box", "list", "list box", "table", "tree", "entry", "text",
})

BUTTON_ROLES = ("button", "push button")


def x(*args, timeout=15):
    return subprocess.run(
        args, capture_output=True, text=True, timeout=timeout, check=False
    ).stdout


def wait_until(predicate, what, timeout=None):
    deadline = time.monotonic() + (WAIT if timeout is None else timeout)
    last = None
    while time.monotonic() < deadline:
        try:
            last = predicate()
        except Exception as exc:
            last = exc
        else:
            if last:
                return last
        time.sleep(0.05)
    raise AssertionError(f"timed out after {timeout or WAIT}s waiting for {what} (last: {last!r})")


def walk(node):
    yield node
    for child in node:
        if child is not None:
            yield from walk(child)


def labelled_by(node):
    for relation in node.getRelationSet():
        if relation.getRelationType() == pyatspi.RELATION_LABELLED_BY:
            target = relation.getTarget(0)
            if target is not None and target.name:
                return target.name
    return ""


def render(node, depth=0):
    lines = []
    for child in walk(node):
        indent = "  " * depth
        try:
            lines.append(f"{indent}{child.getRoleName():<16} {child.name!r}")
        except Exception as exc:
            lines.append(f"{indent}<unreadable: {exc}>")
    return "\n".join(lines)


class Session:
    def __init__(self, env=None, args=()):
        self.env = dict(os.environ)
        self.env.pop("LEGION_POWERCTL_GUI_CLI", None)
        if env:
            self.env.update(env)
        self.args = list(args)
        self.process = None

    def __enter__(self):
        self._require_bus_empty()
        self.process = subprocess.Popen(
            [str(LAUNCHER), *self.args],
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        self.app = wait_until(self._only_app, f"{APP_NAME} to reach the accessibility bus")
        wait_until(
            lambda: self.find_role("list") is not None,
            "the window to build its profile list",
        )
        return self

    def __exit__(self, *exc):
        if self.process and self.process.poll() is None:
            os.killpg(os.getpgid(self.process.pid), 15)
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(self.process.pid), 9)
                self.process.wait(timeout=10)
        wait_until(lambda: self._apps() == [], "the application to leave the bus")
        return False

    @staticmethod
    def _apps():
        desktop = pyatspi.Registry.getDesktop(0)
        return [app for app in desktop if app is not None and app.name == APP_NAME]

    def _require_bus_empty(self):
        if self._apps():
            raise AssertionError(
                "another legion-powerctl is already on the bus; a leaked session makes "
                "every lookup below ambiguous"
            )

    def _only_app(self):
        apps = self._apps()
        if len(apps) > 1:
            raise AssertionError(f"{len(apps)} applications named {APP_NAME} on the bus")
        return apps[0] if apps else None

    def nodes(self):
        return list(walk(self.app))

    def find_role(self, role):
        for node in self.nodes():
            if node.getRoleName() == role:
                return node
        return None

    def find(self, role=None, name=None):
        roles = (role,) if isinstance(role, str) else role
        for node in self.nodes():
            if roles is not None and node.getRoleName() not in roles:
                continue
            if name is not None and node.name != name:
                continue
            return node
        return None

    def button(self, label):
        for node in self.nodes():
            if node.getRoleName() in BUTTON_ROLES and label in (node.name or ""):
                return node
        return None

    def focused(self):
        for node in self.nodes():
            if not node.getState().contains(pyatspi.STATE_FOCUSED):
                continue
            if self._inside_combo(node):
                continue
            return node
        return None

    @staticmethod
    def _inside_combo(node):
        parent = node.parent
        while parent is not None:
            if parent.getRoleName() == "combo box":
                return True
            parent = parent.parent
        return False

    def do_action(self, node, wanted="click"):
        action = node.queryAction()
        for index in range(action.nActions):
            if action.getName(index).lower() == wanted:
                action.doAction(index)
                return True
        if action.nActions:
            action.doAction(0)
            return True
        return False

    def window_id(self):
        ids = x("xprop", "-root", "_NET_CLIENT_LIST")
        return [part.strip() for part in ids.split("#", 1)[-1].split(",") if part.strip()]

    def output(self):
        if self.process is None:
            return ""
        return self.process.stdout.read() if self.process.stdout else ""


class E2ETest(unittest.TestCase):
    def assertNamed(self, node, message):
        name = node.name or labelled_by(node)
        self.assertTrue(name, f"{message}: {node.getRoleName()} has no name and no label")
        return name

    def fail_with_tree(self, session, message):
        self.fail(f"{message}\n\nAccessibility tree:\n{render(session.app)}")
