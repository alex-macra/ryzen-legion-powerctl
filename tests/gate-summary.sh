#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# Ends `make check` and `make check-strict` with the Gate summary block.
#   gate-summary.sh <target> <transcript> <exit-code>       prints the block
#   gate-summary.sh run <target> <command> [<argument>...]  runs the gates, then prints it
# The SKIPPED lines and the result are read from the transcript of the run that just
# finished, never probed again; the commit, the machine and the tool versions are
# probed here. The block is pasted into public pull requests, so it carries no host
# name and no user name, and an absolute path in a line it quotes becomes <path>.

set -Eeuo pipefail

usage() {
    printf 'Usage: gate-summary.sh check|check-strict <transcript> <exit-code>\n' >&2
    printf '       gate-summary.sh run check|check-strict <command> [<argument>...]\n' >&2
    exit 2
}

transcript=''
gates_pid=''

stop_gates() {
    trap '' HUP INT TERM
    if [[ -n "$gates_pid" ]]; then
        kill -s "$1" "$gates_pid" 2>/dev/null || true
        wait "$gates_pid" 2>/dev/null || true
    fi
    exit "$2"
}

# Runs the gates with stdout and stderr copied to a transcript, prints the block from
# it and exits with the gates' own status.
# A make that is told to stop signals only its own child, which is this script, and a
# shell runs no trap while a command is in its foreground. So the gates run in the
# background and this script waits for them: a HUP, INT or TERM that reaches it alone
# goes on to the gates at once, and a run that was cut short gets no block.
# A background command reads /dev/null and may ignore INT and QUIT; the gates must do
# neither, because the suites test what a Ctrl-C does.
run_gates() {
    local target="$1" tee_pid gates_out rc=0
    shift
    transcript="$(mktemp)" || exit 1
    trap 'rm -f "$transcript"' EXIT
    trap 'stop_gates HUP 129' HUP
    trap 'stop_gates INT 130' INT
    trap 'stop_gates TERM 143' TERM
    exec {gates_out}> >(exec tee "$transcript")
    tee_pid="${!:-}"
    ( trap - INT QUIT; exec "$@" ) <&0 >&"$gates_out" 2>&1 {gates_out}>&- &
    gates_pid=$!
    exec {gates_out}>&-
    wait "$gates_pid" || rc=$?
    gates_pid=''
    [[ -z "$tee_pid" ]] || wait "$tee_pid" 2>/dev/null || true
    "$BASH" "${BASH_SOURCE[0]}" "$target" "$transcript" "$rc" ||
        printf 'tests/gate-summary.sh failed, so this run has no Gate summary.\n' >&2
    exit "$rc"
}

if [[ "${1:-}" == run ]]; then
    (( $# >= 3 )) || usage
    [[ "$2" == check || "$2" == check-strict ]] || usage
    run_gates "${@:2}"
fi

(( $# == 3 )) || usage
target="$1" transcript="$2" status="$3"
[[ "$target" == check || "$target" == check-strict ]] || usage
[[ -f "$transcript" && -r "$transcript" ]] || usage
[[ "$status" =~ ^[0-9]+$ ]] || usage

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
DMI_ROOT="${GATE_SUMMARY_DMI_ROOT:-/sys/class/dmi/id}"

one_line() {
    local LC_ALL=C value="${1%%$'\n'*}"
    printf '%s' "${value//[[:cntrl:]]/}"
}

# A path starts at a slash that nothing a path is made of precedes, so `and/or` and
# `tests/test.sh` stay. It runs to the next blank, through any quote or bracket on the
# way, and only the closing punctuation at its very end is kept.
hide_paths() {
    local closers="]\"'\`)>}|,.;:"
    LC_ALL=C sed -E \
        "s#(^|[^[:alnum:]_.~/-])/([^[:space:]]*[^${closers}[:space:]])?([${closers}]*)#\\1<path>\\3#g" <<<"$1"
}

# A checkout whose HEAD is inherited from an enclosing repository is not this tree's
# commit, and the variables git exports to a hook or to `rebase --exec` would point
# every probe at another repository.
git_here() {
    local var
    local -a scrubbed=(env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE)
    for var in $(git rev-parse --local-env-vars 2>/dev/null); do
        scrubbed+=(-u "$var")
    done
    "${scrubbed[@]}" git -C "$ROOT_DIR" "$@" 2>/dev/null
}

commit_label() {
    local head changes
    if command -v git >/dev/null 2>&1 &&
        [[ "$(git_here rev-parse --show-toplevel)" == "$ROOT_DIR" ]] &&
        head="$(git_here rev-parse --short=12 HEAD)" && [[ -n "$head" ]]; then
        changes="$(git_here status --porcelain)" || changes=unreadable
        [[ -z "$changes" ]] || head+='-dirty'
        printf '%s' "$head"
    else
        printf 'not a git checkout'
    fi
}

dmi_field() {
    local LC_ALL=C value
    value="$(cat "$DMI_ROOT/$1" 2>/dev/null || true)"
    value="$(one_line "$value")"
    case "${value,,}" in
        ''|'to be filled by o.e.m.'|'default string'|'none'|'not applicable'| \
        'system product name'|'not specified'|'o.e.m.'|'invalid') return 1 ;;
    esac
    printf '%s' "$value"
}

# On Lenovo firmware product_name is the machine-type code, so it comes last.
machine_label() {
    local os='' release vendor model hardware
    for release in /etc/os-release /usr/lib/os-release; do
        [[ -r "$release" ]] || continue
        os="$(sed -n 's/^PRETTY_NAME=//p' "$release" | head -n 1)"
        os="${os#[\"\']}"
        os="${os%[\"\']}"
        break
    done
    vendor="$(dmi_field sys_vendor || true)"
    model="$(dmi_field product_version || dmi_field product_family || dmi_field product_name || true)"
    hardware="$vendor${vendor:+${model:+ }}$model"
    printf '%s; %s; %s' "$(one_line "${os:-unknown OS}")" "$(one_line "$(uname -srm)")" \
        "${hardware:-unknown}"
}

tools_label() {
    local -a tools=("bash ${BASH_VERSION%%(*}")
    local version
    if command -v python3 >/dev/null 2>&1; then
        version="$(python3 --version 2>&1 || true)"
        tools+=("python ${version#Python }")
    fi
    if command -v shellcheck >/dev/null 2>&1; then
        tools+=("shellcheck $(shellcheck --version 2>/dev/null | sed -n 's/^version: //p' || true)")
    fi
    if command -v ruff >/dev/null 2>&1; then
        version="$(ruff --version 2>/dev/null || true)"
        tools+=("ruff ${version#ruff }")
    fi
    if command -v fish >/dev/null 2>&1; then
        version="$(fish --version 2>/dev/null || true)"
        tools+=("fish ${version##* }")
    fi
    if version="$(python3 -I -c 'import PySide6; print(PySide6.__version__)' 2>/dev/null)"; then
        tools+=("PySide6 $version")
    fi
    local tool joined=''
    for tool in "${tools[@]}"; do
        joined+="${joined:+, }$(one_line "$tool")"
    done
    printf '%s' "$joined"
}

# Every marker is a whole line in the shape the Makefile, unittest or a bash suite
# prints it. Test titles and warnings that only mention a skip must add nothing.
readonly RE_FISH='^fish not installed; .* skipped\.$'
readonly RE_NOT_RUN='^([A-Za-z0-9_.+-]+) not installed; (the )?(.+) DID NOT RUN\.( .*)?$'
readonly RE_SUITE='^  \((.*skipped.*)\)$'
readonly RE_TITLE='^(Test [A-Za-z0-9]+): '
readonly RE_RAN='^Ran ([0-9]+) tests? in [0-9.]+s$'
readonly RE_STATUS='^(OK|FAILED) \((.*)\)$'
readonly RE_SKIP_COUNT='(^|, )skipped=([0-9]+)(,|$)'
readonly RE_REASON="\\.\\.\\. skipped ['\"](.*)['\"]\$"

skips=()
reasons=()
ran='' runs=0 title='a suite case'

unittest_tier() {
    case "$runs" in
        1) printf 'GUI tests' ;;
        2) printf 'end-to-end tests' ;;
        *) printf 'tests in unittest run %s' "$runs" ;;
    esac
}

unittest_reason() {
    local reason joined=''
    for reason in "${reasons[@]}"; do
        joined+="${joined:+; }$reason"
    done
    hide_paths "${joined:-the transcript gives no reason}"
}

add_reason() {
    local known
    for known in "${reasons[@]}"; do
        [[ "$known" != "$1" ]] || return 0
    done
    reasons+=("$1")
}

while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    if [[ -n "$ran" ]]; then
        [[ -n "$line" ]] || continue
        if [[ "$line" =~ $RE_STATUS && "${BASH_REMATCH[2]}" =~ $RE_SKIP_COUNT ]]; then
            skips+=("${BASH_REMATCH[2]} of $ran $(unittest_tier) - $(unittest_reason)")
        fi
        ran=''
        reasons=()
        [[ ! "$line" =~ $RE_STATUS ]] || continue
    fi
    if [[ "$line" =~ $RE_RAN ]]; then
        ran="${BASH_REMATCH[1]}"
        runs=$(( runs + 1 ))
    elif [[ "$line" =~ $RE_TITLE ]]; then
        title="${BASH_REMATCH[1]}"
    elif [[ "$line" =~ $RE_FISH ]]; then
        skips+=('fish completion syntax - fish not installed')
    elif [[ "$line" =~ $RE_NOT_RUN ]]; then
        skips+=("${BASH_REMATCH[3]} - ${BASH_REMATCH[1]} not installed")
    elif [[ "$line" =~ $RE_SUITE ]]; then
        skips+=("$title - $(hide_paths "(${BASH_REMATCH[1]})")")
    elif [[ "$line" =~ $RE_REASON ]]; then
        add_reason "${BASH_REMATCH[1]}"
    fi
done < "$transcript"

[[ "$target" != check ]] || skips+=('end-to-end tier - not part of make check')

printf '\n== Gate summary ==\n'
printf 'target:  make %s\n' "$target"
printf 'commit:  %s\n' "$(commit_label)"
printf 'machine: %s\n' "$(machine_label)"
printf 'tools:   %s\n' "$(tools_label)"
if (( ${#skips[@]} == 0 )); then
    printf 'SKIPPED: none\n'
else
    printf 'SKIPPED: %s\n' "${skips[@]}"
fi
if (( 10#$status != 0 )); then
    printf 'result:  FAILED (exit %s)\n' "$status"
elif (( ${#skips[@]} == 0 )); then
    printf 'result:  PASSED - nothing skipped\n'
elif (( ${#skips[@]} == 1 )); then
    printf 'result:  PASSED WITH 1 SKIP - not a full pass\n'
else
    printf 'result:  PASSED WITH %s SKIPS - not a full pass\n' "${#skips[@]}"
fi
