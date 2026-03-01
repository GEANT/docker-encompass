# site.pp vs enCompass ENC

This note compares two classification approaches:

- Puppet manifest-side classification in `site.pp`
- External Node Classifier (ENC) via enCompass

## TL;DR

- If you need central, auditable, runtime-editable classification, ENC is usually better.
- If you keep logic in `site.pp`, ordering mistakes can silently override intended rules.

## Comparison

### `site.pp` (manifest-side classification)

Advantages:

- Native Puppet workflow, no extra service required
- Full Puppet language expressiveness in one place
- Works even without ENC infrastructure

Drawbacks:

- Rule ordering can be dangerous (top-level broad match can shadow later rules)
- Harder to delegate safely to non-Puppet specialists
- Less structured audit trail for classification-only changes
- Git review noise mixed with unrelated Puppet code changes

### enCompass ENC (external classification)

Advantages:

- Classification is explicit and data-driven (hosts/groups/default)
- Safer matching model with deterministic resolution order
- UI/API for controlled changes and easier delegation
- Cleaner operational audit trail for classification updates

Drawbacks:

- Additional component to operate (service, auth, availability)
- Requires integration and migration discipline
- Classification split from manifest code can require stronger documentation

## Important pitfall in `site.pp`

In `site.pp`, a broad early matcher (catch-all style logic) can effectively override or bypass intended specific rules below, depending on how code is structured.

This is a common source of hard-to-debug behavior drift.

## Ordering in OpenVox/Puppet

For OpenVox/Puppet compilation, `site.pp` is evaluated first and ENC classification is applied after.

Practical implication:

- broad catch-all rules in `site.pp` can still interfere with an ENC-first operating model.
- during migration, remove or narrow catch-all logic so ENC remains the effective source of classification intent.

## How enCompass ENC resolves nodes

In this implementation, resolution is deterministic:

1. Exact host entry in `hosts.yaml`
2. First matching selector in `groups.yaml` order
3. `default` group

This reduces ambiguity compared with open-ended manifest branching.

## Duplicate and overlap validation

enCompass validates group host selectors at save time to prevent ambiguous matches:

- Exact duplicate selectors are not allowed across groups.
- Overlapping selectors (plain prefixes and `/regex/` patterns) are detected.
- Conflicting definitions are rejected with a validation error before they are persisted.

This guardrail helps keep classification deterministic and avoids accidental rule shadowing.

## Operational visibility advantages

Compared to plain `site.pp` workflows, enCompass provides built-in operational views:

- Spring Cleaning: highlights orphan hosts/groups and cleanup candidates.
- Unclassified Hosts: detects nodes that currently resolve to the `default` profile.
- Feature Branches inventory: lists non-predefined environments and where they are used (hosts/groups).

These views improve day-2 operations by making drift, leftovers, and custom branch usage explicit.

## Recommended migration approach

1. Start with minimal ENC (`default` only, one profile)
2. Validate on a small node set
3. Add host/group-specific rules gradually
4. Keep `site.pp` minimal to avoid competing classification logic

## Practical guidance

- Prefer one source of truth for classification (ENC or manifest), not both
- If both exist during migration, document ownership boundaries clearly
- Remove or constrain broad catch-all expressions in `site.pp` when enabling ENC
- Keep a fallback strategy for ENC unavailability
