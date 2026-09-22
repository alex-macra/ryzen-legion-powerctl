# SPDX-License-Identifier: MIT

import ast
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "legion_powerctl_gui"
REPO = PACKAGE.parents[1]

MAX_LINES = 300

LONGER_ALLOWED = {"model.py": 340}


class PackageShapeTest(unittest.TestCase):
    def modules(self):
        return sorted(PACKAGE.glob("*.py"))

    def test_the_package_is_flat(self):
        directories = [
            entry.name
            for entry in PACKAGE.iterdir()
            if entry.is_dir() and entry.name != "__pycache__"
        ]
        self.assertEqual(
            directories, [],
            "the Makefile installs this package by globbing *.py, so anything in a "
            "subdirectory passes the tests and then does not ship",
        )

    def test_the_installer_globs_the_flat_package(self):
        makefile = (REPO / "Makefile").read_text(encoding="utf-8")
        self.assertIn(
            "for module in gui/legion_powerctl_gui/*.py", makefile,
            "the flatness rule above is only worth anything while this is how the "
            "package is installed",
        )

    def test_no_module_is_longer_than_it_can_be_read(self):
        self.assertTrue(self.modules(), "found no modules at all; wrong path?")
        for path in self.modules():
            limit = LONGER_ALLOWED.get(path.name, MAX_LINES)
            length = len(path.read_text(encoding="utf-8").splitlines())
            with self.subTest(module=path.name):
                self.assertLess(
                    length, limit, f"{path.name} is {length} lines, the limit is {limit}"
                )

    def test_only_one_module_builds_a_privileged_command(self):
        call = re.compile(r"(?<![A-Za-z_])privileged_command\(")
        callers = set()
        for path in self.modules():
            source = path.read_text(encoding="utf-8")
            if call.search(source):
                callers.add(path.name)
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.ImportFrom) and any(
                    alias.name == "privileged_command" for alias in node.names
                ):
                    callers.add(path.name)
        self.assertEqual(
            sorted(callers), ["actions.py", "model.py"],
            "model.py defines it and actions.py calls it; a third name here means "
            "the privileged surface is no longer readable in one place",
        )

    def test_every_privileged_subcommand_has_a_polkit_action(self):
        from legion_powerctl_gui import model

        builders = {
            "build_configure_args": lambda: model.build_configure_args(model.Profile(name="x")),
            "build_apply_args": lambda: model.build_apply_args("x"),
            "build_select_args": lambda: model.build_select_args("x"),
            "build_delete_args": lambda: model.build_delete_args("x"),
        }
        source = (PACKAGE / "actions.py").read_text(encoding="utf-8")
        sent = set()
        elevated = 0
        tree = ast.parse(source)
        for node in ast.walk(tree):
            func = getattr(node, "func", None)
            if not isinstance(node, ast.Call):
                continue
            if getattr(func, "attr", "") == "privileged_command":
                elevated += 1
                continue
            if getattr(func, "attr", "") != "_run":
                continue
            argv = node.args[0]
            if isinstance(argv, ast.List):
                sent.add(ast.literal_eval(argv)[0])
            elif isinstance(argv, ast.Call) and getattr(argv.func, "attr", "") in builders:
                sent.add(builders[argv.func.attr]()[0])
            else:
                self.fail(f"cannot tell what subcommand this runs: {ast.dump(argv)}")

        self.assertEqual(
            elevated, 1,
            "privileged_command is called somewhere other than _run, so the walk above "
            "no longer sees every subcommand the GUI can send",
        )
        policy = (REPO / "packaging/polkit/io.github.alexmacra.legion-powerctl.policy")
        pinned = set(re.findall(r"exec\.argv1\">([a-z-]+)<", policy.read_text(encoding="utf-8")))
        self.assertEqual(
            sent, {"configure", "apply", "select", "delete", "enable", "disable", "repair"}
        )
        self.assertLessEqual(
            sent, pinned, f"the GUI runs {sorted(sent - pinned)} through pkexec unpinned"
        )

    def test_repair_requires_fresh_admin_authentication(self):
        policy = ET.parse(REPO / "packaging/polkit/io.github.alexmacra.legion-powerctl.policy")
        action = policy.find(".//action[@id='io.github.alexmacra.legion-powerctl.repair']")
        self.assertIsNotNone(action)
        self.assertEqual(action.find("annotate[@key='org.freedesktop.policykit.exec.argv1']").text,
                         "repair")
        self.assertEqual(action.find("annotate[@key='org.freedesktop.policykit.exec.path']").text,
                         "/usr/bin/legion-powerctl")
        for kind in ("allow_any", "allow_inactive", "allow_active"):
            self.assertEqual(action.find(f"defaults/{kind}").text, "auth_admin")

    def test_no_module_writes_down_a_colour(self):
        colour = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b")
        for path in self.modules():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                    continue
                if not colour.search(node.value):
                    continue
                with self.subTest(module=path.name, line=node.lineno):
                    self.fail(f"{path.name}:{node.lineno} paints {node.value!r}")

    def test_every_exemption_still_names_a_module(self):
        names = {path.name for path in self.modules()}
        for name in LONGER_ALLOWED:
            with self.subTest(module=name):
                self.assertIn(
                    name, names,
                    "an exemption for a module that no longer exists is an exemption "
                    "nobody had to justify",
                )


if __name__ == "__main__":
    unittest.main()
