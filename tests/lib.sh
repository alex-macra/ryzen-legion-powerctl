#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

assert_eq() {
    local expected="$1" actual="$2" message="$3"
    if [[ "$expected" != "$actual" ]]; then
        printf 'FAIL: %s\nExpected: %s\nActual:   %s\n' "$message" "$expected" "$actual" >&2
        exit 1
    fi
}

assert_contains() {
    local needle="$1" text="$2" message="$3"
    if ! grep -Fq -- "$needle" <<<"$text"; then
        printf 'FAIL: %s\nMissing: %s\nSearched:\n%s\n' "$message" "$needle" "$text" >&2
        exit 1
    fi
}

refute_contains() {
    local needle="$1" text="$2" message="$3"
    if grep -Fq -- "$needle" <<<"$text"; then
        printf 'FAIL: %s\nUnwanted: %s\nSearched:\n%s\n' "$message" "$needle" "$text" >&2
        exit 1
    fi
}

assert_match() {
    local text="$1" glob="$2" message="$3"
    # shellcheck disable=SC2053
    if [[ "$text" != $glob ]]; then
        printf 'FAIL: %s\nWanted pattern: %s\nSearched:\n%s\n' "$message" "$glob" "$text" >&2
        exit 1
    fi
}

assert_fails() {
    local message="$1"
    shift
    local output rc=0
    output="$("$@" 2>&1)" || rc=$?
    if (( rc == 0 )); then
        printf 'FAIL: %s\nThe command succeeded: %s\nOutput:\n%s\n' \
            "$message" "$*" "$output" >&2
        exit 1
    fi
}

assert_exit() {
    local expected="$1" message="$2"
    shift 2
    local output rc=0
    output="$("$@" 2>&1)" || rc=$?
    if [[ "$rc" != "$expected" ]]; then
        printf 'FAIL: %s\nExpected exit: %s\nActual exit:   %s\nCommand: %s\nOutput:\n%s\n' \
            "$message" "$expected" "$rc" "$*" "$output" >&2
        exit 1
    fi
}

assert_file_contains() {
    local needle="$1" file="$2" message="$3"
    if [[ ! -e "$file" ]]; then
        printf 'FAIL: %s\nNo such file: %s\n' "$message" "$file" >&2
        exit 1
    fi
    if ! grep -Fq -- "$needle" "$file"; then
        printf 'FAIL: %s\nMissing: %s\nFile %s:\n' "$message" "$needle" "$file" >&2
        cat "$file" >&2
        exit 1
    fi
}
