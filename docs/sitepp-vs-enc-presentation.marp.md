---
marp: true
title: site.pp vs enCompass ENC
description: Why moving classification from site.pp to enCompass ENC improves determinism and operations
author: Platform Team
paginate: true
theme: default
---

# site.pp vs enCompass ENC

## From implicit logic to explicit classification

- Context: Puppet node classification in multi-branch control-repo workflows
- Goal: reduce drift, ambiguity, and operational overhead

<!--
site.pp vs enCompass ENC:
This talk is about reducing operational risk, not replacing Puppet.
We compare manifest-side classification in `site.pp` with ENC-driven classification in enCompass.
-->

---

# Why this discussion now

- Branch-heavy control-repo workflows are costly to maintain
- Cherry-picking classification fixes across branches is error-prone
- Classification intent is often implicit in manifest order and regexes
- We need stronger predictability and auditability

<!--
Why this discussion now:
Set the tone around engineering pain and reliability.
Emphasize that current pain scales with number of environments and teams.
-->

---

# Current model: `site.pp` classification

What works well:

- Native Puppet language and workflow
- No additional service dependency
- Full code-level expressiveness

Where it hurts:

- Rule-order fragility and hidden precedence
- Hard to delegate safely to non-Puppet specialists
- Review noise mixed with unrelated manifest changes

<!--
Current model: site.pp classification:
Be balanced: acknowledge what `site.pp` does well.
Then move to where it breaks under growth and team distribution.
-->

---

# Pain Point 1: Cherry-pick Tax

In branch-based environments, classification updates often require:

- repeated cherry-picks
- conflict resolution per branch
- manual consistency checks

Effects:

- drift between environments
- delayed fixes
- higher change fatigue

<!--
Pain Point 1: Cherry-pick Tax:
Use one real incident if possible: "fix in prod not in preprod" or vice versa.
Frame this as avoidable operational toil.
-->

---

# Pain Point 2: Ambiguous matching behavior

In `site.pp`, it is difficult to answer with confidence:

- does host X match multiple regex paths?
- which rule effectively wins after ordering effects?
- did a broad matcher shadow a specific intent?

Result: hard-to-debug behavior drift.

<!--
Pain Point 2: Ambiguous matching behavior:
This is the key technical reliability argument.
If needed, mention broad early matcher overshadowing specific rules.
-->

---

# Pain Point 3: Low day-2 visibility

Typical gaps in manifest-only workflows:

- no first-class view of unclassified hosts
- no built-in detection of orphan groups/hosts
- weak visibility of feature-branch usage footprint

Operationally, drift is discovered late.

<!--
Pain Point 3: Low day-2 visibility:
This connects architecture to on-call and maintenance outcomes.
Highlight that observability of classification itself is a feature.
-->

---

# ENC model (enCompass)

Classification becomes explicit data plus deterministic resolution.

Resolution order:

1. Exact host entry in `hosts.yaml`
2. First matching selector in `groups.yaml` order
3. `default` group

Benefits:

- deterministic and explainable outcomes
- clear ownership boundaries
- easier controlled delegation via UI/API

<!--
ENC model (enCompass):
Keep this crisp: explicit data beats implicit execution path.
-->

---

# Guardrails that reduce ambiguity

enCompass validation blocks problematic definitions before persistence:

- duplicate selectors across groups
- overlapping selectors (prefix and `/regex/` cases)

Outcome:

- fewer shadowing surprises
- safer edits during normal operations

<!--
Guardrails that reduce ambiguity:
This is where we move from "best effort" to "policy enforcement".
Mention that prevention is cheaper than troubleshooting.
-->

---

# Operational advantages

Built-in views improve day-2 operations:

- Spring Cleaning: orphan hosts/groups and cleanup candidates
- Unclassified Hosts: nodes resolving to `default`
- Feature Branches inventory: where non-predefined envs are used

Outcome:

- faster drift detection
- clearer cleanup workflows

<!--
Operational advantages:
Tie each view to a concrete operator workflow.
-->

---

# Tradeoffs and risks

What ENC adds:

- extra component lifecycle (deploy, monitor, auth)
- availability and fallback planning
- migration discipline (avoid split-brain ownership)

Mitigations:

- run enCapsule for HA read-only endpoints
- keep fallback strategy documented
- reduce broad catch-all logic in `site.pp`

<!--
Tradeoffs and risks:
Show credibility by presenting risks honestly.
This slide builds trust with skeptics.
-->

---

# Migration path (low-risk)

1. Start with minimal ENC (`default` profile only)
2. Pilot on a small, representative node subset
3. Add host/group rules incrementally
4. Keep `site.pp` minimal while migrating
5. Define ownership boundaries (ENC vs manifest)
6. Add rollback/fallback procedures and runbooks

Success criteria:

- lower change lead time
- fewer classification incidents
- reduced branch drift

<!--
Migration path (low-risk):
Stress incremental migration and measurable outcomes.
-->

---

# Decision framing

Option A: Stay manifest-centric

- lower platform footprint
- continued ambiguity and branch-cherry-pick overhead

Option B: ENC-centric classification (recommended)

- stronger determinism and guardrails
- better auditability and operations
- small but manageable platform overhead

Recommendation:

- adopt ENC as source of truth for classification intent
- keep `site.pp` lean and non-competing

<!--
Decision framing:
End with a clear recommendation and why.
-->

---

# Appendix: Q&A prompts

- How do we handle ENC outage scenarios?
- Which teams can edit classification and with what approval flow?
- What is the rollback plan for incorrect selector changes?
- How do we measure migration success over 30/60/90 days?

PDF and notes generated with [Marp](https://marp.app):

- npx --yes @marp-team/marp-cli sitepp-vs-enc-presentation.marp.md --pdf
- npx --yes @marp-team/marp-cli --notes sitepp-vs-enc-presentation.marp.md

<!--
Appendix: Q&A prompts:
Use these prompts to drive next steps after the presentation.
-->
