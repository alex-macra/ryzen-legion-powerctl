# SPDX-License-Identifier: MIT

import harness
from harness import E2ETest, Session, labelled_by


class AccessibilityTreeTest(E2ETest):
    @classmethod
    def setUpClass(cls):
        cls.session = Session().__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.session.__exit__(None, None, None)

    def test_every_interactive_node_announces_something(self):
        unnamed = []
        for node in self.session.nodes():
            role = node.getRoleName()
            if role not in harness.INTERACTIVE_ROLES:
                continue
            parent = node.parent
            if parent is not None and parent.getRoleName() == "combo box":
                continue
            if not (node.name or labelled_by(node)):
                unnamed.append(f"{role} (parent: {parent.getRoleName() if parent else None})")
        if unnamed:
            self.fail_with_tree(
                self.session,
                "these reach a screen reader with no name and no label: " + ", ".join(unnamed),
            )

    def test_the_installed_launcher_ran_the_installed_cli(self):
        rows = [node.name for node in self.session.nodes() if node.getRoleName() == "list item"]
        self.assertTrue(rows, "the profile list is empty; the launcher found no CLI to poll")
        joined = " ".join(rows)
        self.assertIn("balanced-plus", joined)
        self.assertIn("quiet", joined)

    def test_the_row_text_the_delegate_never_paints_reaches_the_bus(self):
        rows = [node.name for node in self.session.nodes() if node.getRoleName() == "list item"]
        running = [row for row in rows if "running now" in row]
        self.assertTrue(running, f"no row announces which profile is running: {rows}")
        boot = [row for row in rows if "boot profile" in row]
        self.assertTrue(boot, f"no row announces which profile boots: {rows}")
        self.assertIn("balanced-plus", running[0])
        self.assertIn("W", running[0], f"the row does not say its power envelope: {running[0]!r}")
