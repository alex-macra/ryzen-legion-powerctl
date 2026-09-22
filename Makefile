# SPDX-License-Identifier: MIT
SHELL_SOURCES := bin/legion-powerctl bin/legion-powerctl-gui install.sh uninstall.sh \
	tools/legion-powerbench \
	tests/test.sh tests/test-branches.sh tests/test-bench.sh tests/test-repair.sh tests/lib.sh \
	tests/fixtures/make-fake-root.sh \
	tests/e2e/run.sh tests/e2e/podman.sh \
	gui/tests/fake-legion-powerctl gui/tests/fixtures/regenerate-doctor.sh \
	gui/tests/fixtures/regenerate-status.sh \
	completions/legion-powerctl.bash

PY_SOURCES := gui tests/e2e

PREFIX ?= /usr
SYSCONFDIR ?= /etc
SYSTEMDUNITDIR ?= $(PREFIX)/lib/systemd/system
DOCDIR ?= $(PREFIX)/share/doc/legion-powerctl
DESTDIR ?=
DISTDIR ?= dist
VERSION := $(shell sed -n 's/^readonly VERSION="\([^"]*\)".*/\1/p' bin/legion-powerctl)

.PHONY: all install install-files install-config uninstall uninstall-files \
	check check-strict lint-py syntax test test-gui test-e2e test-e2e-podman \
	dist dev-gui verify-versions print-shell-sources print-version

print-shell-sources:
	@printf '%s\n' $(SHELL_SOURCES)

print-version:
	@printf '%s\n' '$(VERSION)'

all:
	@printf 'Run make check, make install, or ./install.sh\n'

dev-gui:
	LEGION_POWERCTL_GUI_ROOT="$(CURDIR)/gui" \
	LEGION_POWERCTL_GUI_CLI="$(CURDIR)/bin/legion-powerctl" \
	./bin/legion-powerctl-gui

dist:
	@test -n "$(VERSION)" || { printf 'Could not read VERSION from bin/legion-powerctl\n' >&2; exit 1; }
	mkdir -p "$(DISTDIR)"
	@if git rev-parse --show-toplevel >/dev/null 2>&1; then \
		printf 'Packing committed HEAD with git archive.\n'; \
		test -z "$$(git status --porcelain)" || \
			printf 'WARNING: uncommitted changes are NOT included.\n' >&2; \
		git archive --format=tar.gz --prefix=legion-powerctl-$(VERSION)/ \
			-o "$(DISTDIR)/legion-powerctl-$(VERSION).tar.gz.part" HEAD; \
	else \
		printf 'Not a git checkout; packing the working tree with tar.\n'; \
		tar -czf "$(DISTDIR)/legion-powerctl-$(VERSION).tar.gz.part" \
			--exclude=./.git --exclude=./dist --exclude=./packaging/arch/pkg \
			--exclude=./packaging/arch/src --exclude='*.pkg.tar.zst' \
			--exclude='*.tar.gz' --exclude=./gui/.pytest_cache \
			--exclude=__pycache__ \
			--transform 's,^\.,legion-powerctl-$(VERSION),' .; \
	fi
	@mv "$(DISTDIR)/legion-powerctl-$(VERSION).tar.gz.part" "$(DISTDIR)/legion-powerctl-$(VERSION).tar.gz"
	@printf 'Wrote %s\n' "$(DISTDIR)/legion-powerctl-$(VERSION).tar.gz"

verify-versions:
	@cli="$(VERSION)"; \
	pkg="$$(sed -n 's/^pkgver=//p' packaging/arch/PKGBUILD)"; \
	log="$$(sed -n 's/^## \([0-9][0-9.]*\).*/\1/p' CHANGELOG.md | head -n1)"; \
	gui="$$(sed -n 's/^__version__ = "\([^"]*\)".*/\1/p' gui/legion_powerctl_gui/__init__.py)"; \
	bench="$$(sed -n 's/^readonly VERSION="\([^"]*\)".*/\1/p' tools/legion-powerbench)"; \
	man="$$(sed -n 's/^\.TH .*legion-powerctl \([0-9][0-9.]*\).*/\1/p' man/legion-powerctl.8)"; \
	printf 'CLI %s / PKGBUILD %s / CHANGELOG %s / GUI %s / benchmark %s / man %s\n' "$$cli" "$$pkg" "$$log" "$$gui" "$$bench" "$$man"; \
	test -n "$$cli" && test "$$cli" = "$$pkg" && test "$$cli" = "$$log" && \
		test "$$cli" = "$$gui" && test "$$cli" = "$$bench" && test "$$cli" = "$$man" || \
		{ printf 'Version mismatch across bin/legion-powerctl, PKGBUILD, CHANGELOG.md, the GUI package, legion-powerbench, and the man page\n' >&2; exit 1; }

install: install-files install-config

install-files:
	install -Dm0755 bin/legion-powerctl "$(DESTDIR)$(PREFIX)/bin/legion-powerctl"
	install -Dm0755 tools/legion-powerbench "$(DESTDIR)$(PREFIX)/bin/legion-powerbench"
	install -Dm0644 systemd/legion-powerctl.service "$(DESTDIR)$(SYSTEMDUNITDIR)/legion-powerctl.service"
	install -Dm0644 completions/legion-powerctl.fish "$(DESTDIR)$(PREFIX)/share/fish/vendor_completions.d/legion-powerctl.fish"
	install -Dm0644 completions/legion-powerctl.bash "$(DESTDIR)$(PREFIX)/share/bash-completion/completions/legion-powerctl"
	install -Dm0644 man/legion-powerctl.8 "$(DESTDIR)$(PREFIX)/share/man/man8/legion-powerctl.8"
	install -d -m0755 "$(DESTDIR)$(DOCDIR)/docs"
	install -m0644 README.md LICENSE CHANGELOG.md CONTRIBUTING.md SECURITY.md "$(DESTDIR)$(DOCDIR)/"
	install -m0644 docs/*.md "$(DESTDIR)$(DOCDIR)/docs/"
	install -Dm0755 bin/legion-powerctl-gui "$(DESTDIR)$(PREFIX)/bin/legion-powerctl-gui"
	install -d -m0755 "$(DESTDIR)$(PREFIX)/share/legion-powerctl/gui/legion_powerctl_gui"
	for module in gui/legion_powerctl_gui/*.py; do \
		install -m0644 "$$module" "$(DESTDIR)$(PREFIX)/share/legion-powerctl/gui/legion_powerctl_gui/$${module##*/}"; \
	done
	install -Dm0644 desktop/legion-powerctl.desktop "$(DESTDIR)$(PREFIX)/share/applications/legion-powerctl.desktop"
	install -Dm0644 desktop/legion-powerctl.svg "$(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps/legion-powerctl.svg"
	install -Dm0644 desktop/legion-powerctl-symbolic.svg "$(DESTDIR)$(PREFIX)/share/icons/hicolor/symbolic/apps/legion-powerctl-symbolic.svg"
	install -d -m0755 "$(DESTDIR)$(PREFIX)/share/polkit-1/actions"
	sed 's|/usr/bin/legion-powerctl|$(PREFIX)/bin/legion-powerctl|g' \
		packaging/polkit/io.github.alexmacra.legion-powerctl.policy \
		> "$(DESTDIR)$(PREFIX)/share/polkit-1/actions/io.github.alexmacra.legion-powerctl.policy"
	chmod 0644 "$(DESTDIR)$(PREFIX)/share/polkit-1/actions/io.github.alexmacra.legion-powerctl.policy"

install-config:
	install -Dm0644 config/config.conf "$(DESTDIR)$(SYSCONFDIR)/legion-powerctl/config.conf"
	install -d -m0755 "$(DESTDIR)$(SYSCONFDIR)/legion-powerctl/profiles.d"
	for profile in profiles/*.conf; do \
		install -m0644 "$$profile" "$(DESTDIR)$(SYSCONFDIR)/legion-powerctl/profiles.d/$${profile##*/}"; \
	done

uninstall: uninstall-files
	@printf 'Configuration under %s was preserved.\n' "$(DESTDIR)$(SYSCONFDIR)/legion-powerctl"

uninstall-files:
	rm -f "$(DESTDIR)$(PREFIX)/bin/legion-powerctl"
	rm -f "$(DESTDIR)$(PREFIX)/bin/legion-powerbench"
	rm -f "$(DESTDIR)$(SYSTEMDUNITDIR)/legion-powerctl.service"
	rm -f "$(DESTDIR)$(PREFIX)/share/fish/vendor_completions.d/legion-powerctl.fish"
	rm -f "$(DESTDIR)$(PREFIX)/share/bash-completion/completions/legion-powerctl"
	rm -f "$(DESTDIR)$(PREFIX)/share/man/man8/legion-powerctl.8"
	rm -rf "$(DESTDIR)$(DOCDIR)"
	rm -f "$(DESTDIR)$(PREFIX)/bin/legion-powerctl-gui"
	rm -rf "$(DESTDIR)$(PREFIX)/share/legion-powerctl"
	rm -f "$(DESTDIR)$(PREFIX)/share/applications/legion-powerctl.desktop"
	rm -f "$(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps/legion-powerctl.svg"
	rm -f "$(DESTDIR)$(PREFIX)/share/icons/hicolor/symbolic/apps/legion-powerctl-symbolic.svg"
	rm -f "$(DESTDIR)$(PREFIX)/share/polkit-1/actions/io.github.alexmacra.legion-powerctl.policy"

syntax:
	bash -n $(SHELL_SOURCES)
	@if command -v fish >/dev/null 2>&1; then fish -n completions/legion-powerctl.fish; else printf 'fish not installed; Fish completion syntax check skipped.\n'; fi

test: syntax
	bash tests/test.sh
	bash tests/test-branches.sh
	bash tests/test-bench.sh
	bash tests/test-repair.sh

test-gui:
	PYTHONPATH=gui QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s gui/tests -v

E2E_TIMEOUT ?= 300

test-e2e:
	E2E_TIMEOUT=$(E2E_TIMEOUT) bash tests/e2e/run.sh $(E2E_ARGS)

test-e2e-podman:
	bash tests/e2e/podman.sh $(E2E_ARGS)

lint-py:
	@if command -v ruff >/dev/null 2>&1; then \
		ruff check $(PY_SOURCES); \
	else \
		printf 'ruff not installed; the Python lint DID NOT RUN. Use make check-strict.\n'; \
	fi

check: test test-gui verify-versions lint-py
	@if command -v shellcheck >/dev/null 2>&1; then \
		shellcheck $(SHELL_SOURCES); \
	else \
		printf 'shellcheck not installed; ShellCheck DID NOT RUN. Use make check-strict.\n'; \
	fi

check-strict:
	@missing=''; \
	for tool in shellcheck fish ruff; do \
		command -v $$tool >/dev/null 2>&1 || missing="$$missing $$tool"; \
	done; \
	python3 -I -c 'import PySide6' >/dev/null 2>&1 || missing="$$missing PySide6"; \
	test -z "$$missing" || { \
		printf 'check-strict cannot run; not installed:%s\n' "$$missing" >&2; \
		printf 'Install them, or run `make check` and accept that those gates are skipped.\n' >&2; \
		exit 1; \
	}
	$(MAKE) check
	@# CI runs the end-to-end tier, and this target's whole claim is that a green run
	@# here means what CI will do. tests/e2e/run.sh does its own preflight and names
	@# what is missing, including the container that has all of it.
	$(MAKE) test-e2e
