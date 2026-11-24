## Summary

## Testing

Paste the `Gate summary` block that `make check-strict` ends with, as printed. If it
refuses to run here, paste the one from `make check`: each `SKIPPED:` line in it is
something that did not run on that machine, not a pass.

```text
```

- [ ] Existing profiles remain data-only and are not sourced
- [ ] No timer or resident daemon was added by default
- [ ] New low-level behavior is opt-in and documented

## Hardware impact

Describe any new hardware writes, guardrails, rollback behavior, and tested laptop/CPU combinations.
