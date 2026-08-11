#!/usr/bin/env python3
"""
Extract the load-bearing semantics of OPA/Rego policies without a model.

A Rego policy is read by an AI step later in the pipeline, but the facts that
most often INVERT a Rego -> Terraform Policy conversion are lexical, so they are
read here in plain code and handed to that step as pinned facts instead of being
left to inference.

For every `<name>.rego` found, this writes `<name>.source_semantics.md` beside
it. Step 1 embeds that file verbatim into requirement.txt and marks it
authoritative, so the generation step applies the same facts.

What is extracted, and why each one matters:

  * Rule polarity. A decision rule (`rule contains x if { }` in v1,
    `rule[x] { }` in v0, or deny/violation/warn) matches the VIOLATING state,
    so the target policy's PASS condition is the NEGATION of the rule body.
    An `allow` rule is the inverse. Reading the body as the pass condition
    inverts the whole policy - this is the single most common conversion bug.
  * `object.get(after, "k", D)` provider defaults. D is load-bearing and maps
    onto the target's `core::try(attrs.k, D)`, so it is captured, not just flagged.
  * `== null` present-null checks. Terraform plan JSON emits an unset optional
    as null, so this is a required-attribute test: both an absent attribute and
    a present-null one must be treated as the violation.
  * `count(x) == 0` emptiness checks.
  * Cross-resource scope (more than one `.type ==`), which needs a
    `core::getresources` lookup rather than a per-resource attribute check.
  * Aggregation via `data.terraform.<pkg>`, where the scope is the union of the
    delegated packages and this file names no resource type of its own.
  * Terraform CONFIG metadata (`plan.configuration`, `constant_value`,
    `references`), which describes how a value was authored rather than what it
    evaluates to - an expressiveness gap to declare, not a translation to get right.
  * The package name and the `# METADATA` enforcement level, which the policy
    set definition and step 0 need.

Usage:
    python3 rego_semantics.py <directory> [--quiet]

Arguments:
    directory: directory containing .rego policies (searched recursively)
    --quiet:   only report errors

Exit codes:
    0  semantics written for every policy found (or no policy found)
    1  the directory does not exist
"""

import os
import re
import sys
from pathlib import Path

# Rule declarations. A v1 set rule emits members via `contains ... if`; a v0
# partial rule via `name[...] { }`. Both describe the VIOLATING state.
V1_SET_RULE = re.compile(r"(?m)^\s*(\w+)\s+contains\b[^\n{]*\bif\b\s*\{")
V0_PARTIAL_RULE = re.compile(r"(?m)^\s*(\w+)\s*\[[^\]]*\]\s*\{")
ALLOW_RULE = re.compile(r"(?m)^\s*(allow)\b")
DENY_RULE = re.compile(r"(?m)^\s*(deny|violation|warn)\b")
V1_MARKER = re.compile(r"\bcontains\b|\bif\s*\{")

# `object.get(<obj>, "<key>", <default>)` - the provider default applied when
# the key is absent. Defaults seen in practice are literals (false, "", [],
# numbers, strings), so a non-nested capture is enough.
OBJECT_GET = re.compile(r'object\.get\s*\(\s*[^,]+?\s*,\s*"([^"]+)"\s*,\s*([^)]+?)\s*\)')
# `<attr-ref> == null` - a present-but-null check (an absent key is undefined).
NULL_CMP = re.compile(r'([\w.\[\]"]+)\s*==\s*null')
# `object.get(o, "<key>", null) == null` - the absent-OR-null idiom. The left
# side is a call, so NULL_CMP cannot see it, but it checks presence of <key>.
OBJECT_GET_NULL = re.compile(r'object\.get\s*\(\s*[^,]+?\s*,\s*"([^"]+)"\s*,[^)]*\)\s*==\s*null')
COUNT_ZERO = re.compile(r"count\s*\(\s*([^)]*?)\s*\)\s*==\s*0")
TYPE_EQ = re.compile(r'\.type\s*==\s*"([^"]+)"')
# A reference to ANOTHER policy package's decision (the aggregator idiom).
DATA_REF = re.compile(r"\bdata\.terraform\.(\w+)")
PACKAGE_DECL = re.compile(r"(?m)^\s*package\s+terraform\.([\w.]+)")
METADATA_MARKER = re.compile(r"#\s*METADATA")
# `#  enforcement_level: <value>` inside a METADATA comment block.
METADATA_ENFORCEMENT = re.compile(r"(?m)^\s*#\s*enforcement_level\s*:\s*(\S+)")
CONFIG_META = re.compile(r"plan\.configuration|\.expressions\.|\bconstant_value\b|\breferences\b")

# The closed enforcement vocabulary. Anything else is not interpreted.
ENFORCEMENT_LEVELS = ("advisory", "mandatory")
DEFAULT_ENFORCEMENT = "advisory"

SEMANTICS_SUFFIX = ".source_semantics.md"

# Path segments that say WHERE a value is read or HOW it was reached, neither of
# which is the attribute's own name.
PATH_WRAPPERS = ("change", "after", "before", "values", "config", "expressions")
PATH_ROOTS = ("r", "res", "rc", "plan", "input", "resource")


def attribute_of(path: str):
    """The attribute name a `change.after.<...>` path refers to, or None."""
    cleaned = path.strip().strip('"')
    segments = [s for s in re.split(r"[.\[\]]", cleaned) if s and not s.isdigit()]
    while segments and (segments[0] in PATH_ROOTS or segments[0] in PATH_WRAPPERS):
        segments.pop(0)
    while segments and segments[-1] in PATH_WRAPPERS:
        segments.pop()
    return segments[-1] if segments else None


def own_package(text: str):
    """The last dotted segment of this file's own `package terraform.<name>`."""
    match = PACKAGE_DECL.search(text)
    if not match:
        return None
    return match.group(1).split(".")[-1]


def full_package(text: str):
    """The full `terraform.<...>` package path, used to match policies.hcl queries."""
    match = PACKAGE_DECL.search(text)
    if not match:
        return None
    return "terraform." + match.group(1)


def classify_rules(text: str):
    """(violation_rule_names, allow_rule_names), deduplicated in source order."""
    violation = []
    allow = []

    def add(bucket, name):
        if name not in bucket:
            bucket.append(name)

    for match in V1_SET_RULE.finditer(text):
        add(violation, match.group(1))
    for match in V0_PARTIAL_RULE.finditer(text):
        add(violation, match.group(1))
    for match in DENY_RULE.finditer(text):
        add(violation, match.group(1))
    for match in ALLOW_RULE.finditer(text):
        add(allow, match.group(1))
    # Keep the polarity buckets disjoint.
    violation = [name for name in violation if name not in allow]
    return violation, allow


def read_enforcement(text: str):
    """(level, raw_value) from a `# METADATA` block, or (None, raw) when unusable.

    Only `advisory` and `mandatory` are interpreted. An unknown or misspelled
    value is NOT guessed at: the caller falls back to the default and reports a
    warning, so the input error stays visible instead of being silently fixed.
    """
    match = METADATA_ENFORCEMENT.search(text)
    if not match:
        return None, None
    raw = match.group(1).strip().strip('"').strip("'")
    if raw.lower() in ENFORCEMENT_LEVELS:
        return raw.lower(), raw
    return None, raw


class Delegation:
    """A delegated package whose source was found beside the aggregator."""

    def __init__(self, package: str, resource_types: list, source: str):
        self.package = package
        self.resource_types = resource_types
        self.source = source


class Semantics:
    """Facts read off one Rego source without a model."""

    def __init__(self):
        self.syntax = "unknown"
        self.package = None
        self.violation_rules = []
        self.allow_rules = []
        self.object_get_defaults = []   # list of (attribute, default)
        self.null_checks = []
        self.count_zero_checks = []
        self.resource_types = []
        self.aggregated_packages = []
        self.delegations = []
        self.config_metadata = False
        self.enforcement_level = None
        self.enforcement_raw = None

    # -- statements to pin for the reading step -----------------------------

    def notes(self):
        out = []
        if self.violation_rules:
            names = ", ".join("`%s`" % n for n in self.violation_rules)
            out.append(
                "The decision rule (%s) builds a SET of violations: its body matches the "
                "VIOLATING state and emits a member when it holds, so a resource FAILS when "
                "the body is true. The target policy's PASS condition is the NEGATION of the "
                "rule body - do not copy the rule condition as the enforce condition." % names
            )
        if self.allow_rules:
            names = ", ".join("`%s`" % n for n in self.allow_rules)
            out.append(
                "An `allow`-style rule (%s) states the REQUIRED-PASS condition directly: its "
                "body is the compliant state, not the violation." % names
            )
        seen = set()
        for attribute, default in self.object_get_defaults:
            key = (attribute, default)
            if key in seen:
                continue
            seen.add(key)
            name = attribute or "<attr>"
            out.append(
                '`object.get(..., "%s", %s)` applies the provider default `%s` to `%s` when it '
                "is absent. Mirror this in the target with `core::try(attrs.%s, %s)` so the same "
                "default is applied on both sides." % (name, default, default, name, name, default)
            )
        if self.null_checks:
            attrs = ", ".join("`%s`" % a for a in self.null_checks)
            out.append(
                "A `== null` check (%s) is a REQUIRED-PRESENT test in the violation body: the "
                "source flags the attribute when it reads as null. Terraform plan JSON emits an "
                "UNSET optional as null, so 'attribute not defined' reaches the policy as null - "
                "there is no separate absent case to pass through. In the target, treat BOTH an "
                "ABSENT attribute AND a present-null one as the violating state: read it with a "
                "`null` default (`core::try(attrs.<attr>, null)`) and enforce that the result is "
                "non-null. Do NOT give `core::try` a non-null default here - that would turn an "
                "absent attribute into that default and let it pass as compliant, inverting the "
                "check." % attrs
            )
            out.append(
                "For each required-present attribute the EMPTY form is the violating state too: "
                'an empty string ("") for a string-typed attribute (Terraform surfaces an unset '
                "optional string as \"\" as readily as null) and an empty collection for a "
                "list/map/set. Enforce non-EMPTY, not merely non-null, and the test suite MUST "
                "include a case that sets the attribute to its empty form and asserts it FAILS - "
                "a suite that omits the empty case cannot tell a required-present policy from one "
                "that accepts an empty value."
            )
            out.append("Required-present attributes: %s." % attrs)
        if self.count_zero_checks:
            out.append(
                "A `count(...) == 0` check tests an empty or absent list; preserve the emptiness "
                "semantics rather than turning it into a per-element check."
            )
        if len(self.resource_types) > 1:
            out.append(
                "The policy correlates more than one resource type, so the target needs a "
                "cross-resource lookup (`core::getresources`) rather than a per-resource "
                "attribute check."
            )
        if self.aggregated_packages:
            out.append(
                "This policy AGGREGATES other policy packages (it references `data.terraform.<pkg>` "
                "for: %s). Its scope is the UNION of those packages' scopes, and this file itself "
                "names no resource type with a direct `.type ==` check. These are INDEPENDENT "
                "per-resource checks combined by OR, not a correlation across resources: emit one "
                "target resource_policy per delegated resource type (each enforcing the NEGATION of "
                "that package's violation predicate) rather than a single cross-resource lookup. "
                "Enumerate EVERY delegated resource type - do not leave the related resources empty "
                "just because this file names no resource type directly."
                % ", ".join(self.aggregated_packages)
            )
            resolved = dict((d.package, d) for d in self.delegations)
            for package in self.aggregated_packages:
                delegation = resolved.get(package)
                if delegation is None:
                    continue
                types = ", ".join(delegation.resource_types) or "an unnamed type"
                out.append(
                    "The delegated package `%s` is RESOLVED: its source was found beside this "
                    "policy (it targets %s) and is reproduced verbatim below. Reproduce its EXACT "
                    "predicate, including any literal value it compares against - a literal such as "
                    "a specific `acl` string is load-bearing and must carry across unchanged; do NOT "
                    "substitute a general notion inferred from the package name."
                    % (package, types)
                )
            unresolved = [p for p in self.aggregated_packages if p not in resolved]
            if unresolved:
                out.append(
                    "The delegated package(s) %s could NOT be resolved (no matching source beside "
                    "this policy). Infer the resource type(s) each targets from its name and "
                    "purpose; the concrete predicate cannot be recovered here and is approximated - "
                    "see the declared limitation."
                    % ", ".join("`%s`" % p for p in unresolved)
                )
        return out

    def limitations(self):
        out = []
        if self.config_metadata:
            out.append(
                "The source reads Terraform CONFIG metadata (`plan.configuration` / "
                "`constant_value` / `references`), which describes how a value was written rather "
                "than what it evaluates to. A planned end state cannot distinguish 'attribute "
                "absent from the configuration' from 'attribute present but empty', so that "
                "distinction cannot be enforced. Declare it with a `# LIMITATION:` block instead "
                "of approximating it."
            )
        resolved = set(d.package for d in self.delegations)
        unresolved = [p for p in self.aggregated_packages if p not in resolved]
        if unresolved:
            out.append(
                "This policy delegates to package(s) %s whose source is not present in the input. "
                "Their concrete predicates - including any non-standard literal values - cannot be "
                "read and are approximated from the package name, so the generated target may "
                "diverge on the exact values each delegated check uses."
                % ", ".join("`%s`" % p for p in unresolved)
            )
        return out

    def warnings(self):
        """Input problems worth surfacing to the operator (not fatal)."""
        out = []
        if self.enforcement_raw is not None and self.enforcement_level is None:
            out.append(
                "The `# METADATA` block declares enforcement_level `%s`, which is not one of "
                "`advisory` / `mandatory`. It is NOT interpreted; the default `%s` applies unless "
                "the policy set definition states a level."
                % (self.enforcement_raw, DEFAULT_ENFORCEMENT)
            )
        if not self.violation_rules and not self.allow_rules:
            out.append(
                "No decision rule was recognised in this file. Read the polarity from the source "
                "directly and state it explicitly in the requirement."
            )
        return out

    def render(self):
        """The document the reading step reads alongside the source."""
        lines = ["# Source semantics read from the policy (deterministic)", ""]
        lines += [
            "These statements were extracted from the source text, not inferred. Treat them as",
            "AUTHORITATIVE over any reading suggested by the policy's name or by a first",
            "impression of the code.",
            "",
        ]
        facts = []
        if self.syntax != "unknown":
            facts.append("Rego syntax: **%s**" % self.syntax)
        if self.package:
            facts.append("Package: `%s`" % self.package)
        if self.enforcement_level:
            facts.append("Declared enforcement level (METADATA): `%s`" % self.enforcement_level)
        if facts:
            lines += ["- %s" % f for f in facts] + [""]

        notes = self.notes()
        if notes:
            lines += ["## Facts that decide the conversion", ""]
            lines += ["- %s" % n for n in notes]
            lines.append("")

        limits = self.limitations()
        if limits:
            lines += ["## Known expressiveness gaps - declare, do not approximate", ""]
            lines += ["- %s" % n for n in limits]
            lines.append("")

        warns = self.warnings()
        if warns:
            lines += ["## Warnings about the input", ""]
            lines += ["- %s" % n for n in warns]
            lines.append("")

        if self.delegations:
            lines += [
                "## Referenced policy package sources",
                "",
                "The source of each resolved delegated package is reproduced verbatim so its exact",
                "predicate - including any literal value it compares against - carries across",
                "rather than being guessed from the package name:",
                "",
            ]
            for delegation in self.delegations:
                types = ", ".join(delegation.resource_types) or "unnamed type"
                lines += [
                    "### data.terraform.%s (%s)" % (delegation.package, types),
                    "",
                    "```rego",
                    delegation.source.strip(),
                    "```",
                    "",
                ]

        if self.resource_types:
            lines += ["## Resource types queried by the source", ""]
            lines += ["- %s" % t for t in self.resource_types]
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"


def resolve_delegations(packages, sibling_sources, this_package):
    """Match each delegated package to a sibling source, when one is present."""
    if not packages or not sibling_sources:
        return []
    by_package = {}
    for source in sibling_sources:
        name = own_package(source or "")
        if name and name != this_package and name not in by_package:
            by_package[name] = source
    resolved = []
    for package in packages:
        source = by_package.get(package)
        if source is None:
            continue
        types = sorted(set(TYPE_EQ.findall(source)))
        resolved.append(Delegation(package, types, source))
    return resolved


def analyze(source: str, sibling_sources=None) -> Semantics:
    """Read one Rego policy's load-bearing semantics. Never raises on junk input."""
    text = source or ""
    result = Semantics()

    result.violation_rules, result.allow_rules = classify_rules(text)
    if V1_MARKER.search(text):
        result.syntax = "v1"
    elif V0_PARTIAL_RULE.search(text):
        result.syntax = "v0"

    result.package = full_package(text)

    # A `null` default is not a provider substitution; it is the absent-or-null
    # idiom, read as a present-null check below.
    for key, default in OBJECT_GET.findall(text):
        if default.strip() == "null":
            continue
        result.object_get_defaults.append((attribute_of(key), default.strip()))

    for left in NULL_CMP.findall(text):
        attribute = attribute_of(left)
        if attribute and attribute not in result.null_checks:
            result.null_checks.append(attribute)
    for key in OBJECT_GET_NULL.findall(text):
        attribute = attribute_of(key) or key
        if attribute and attribute not in result.null_checks:
            result.null_checks.append(attribute)

    result.count_zero_checks = [c.strip() for c in COUNT_ZERO.findall(text)]
    result.resource_types = sorted(set(TYPE_EQ.findall(text)))

    this_package = own_package(text)
    result.aggregated_packages = sorted(
        set(p for p in DATA_REF.findall(text) if p != this_package)
    )
    result.delegations = resolve_delegations(
        result.aggregated_packages, sibling_sources, this_package
    )

    result.config_metadata = bool(CONFIG_META.search(text))
    if METADATA_MARKER.search(text):
        result.enforcement_level, result.enforcement_raw = read_enforcement(text)
    return result


def is_test_file(name: str) -> bool:
    return name.endswith("_test.rego")


def find_policies(directory: Path) -> list:
    """Every .rego policy under `directory`, excluding tests and fixture trees."""
    policies = []
    for path in sorted(directory.rglob("*.rego")):
        parts = path.relative_to(directory).parts
        if is_test_file(path.name) or any(p in ("test", "testdata") for p in parts):
            continue
        policies.append(path)
    return policies


def sibling_sources(policy: Path) -> list:
    """Raw text of the OTHER .rego policies in this policy's own directory."""
    sources = []
    for path in sorted(policy.parent.glob("*.rego")):
        if path == policy or is_test_file(path.name):
            continue
        try:
            sources.append(path.read_text(encoding="utf-8"))
        except OSError:
            continue
    return sources


def write_atomically(target: Path, text: str) -> None:
    """Replace `target` in one step so a concurrent reader never sees it half-written.

    The pipeline runs several stage invocations at once, each re-extracting the
    same policies while other containers read the result, and a plain write
    truncates the file first.
    """
    scratch = target.with_name("%s.%d.tmp" % (target.name, os.getpid()))
    try:
        scratch.write_text(text, encoding="utf-8")
        os.replace(str(scratch), str(target))
    except BaseException:
        try:
            scratch.unlink()
        except OSError:
            pass
        raise


def main(argv) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    quiet = "--quiet" in argv[1:]
    if len(args) != 1:
        print(__doc__, file=sys.stderr)
        return 1

    directory = Path(args[0])
    if not directory.is_dir():
        print("ERROR: not a directory: %s" % directory, file=sys.stderr)
        return 1

    policies = find_policies(directory)
    if not policies:
        if not quiet:
            print("No .rego policies found under %s" % directory)
        return 0

    warned = 0
    for policy in policies:
        try:
            source = policy.read_text(encoding="utf-8")
        except OSError as exc:
            print("ERROR: cannot read %s: %s" % (policy, exc), file=sys.stderr)
            continue
        semantics = analyze(source, sibling_sources(policy))
        target = policy.with_name(policy.stem + SEMANTICS_SUFFIX)
        write_atomically(target, semantics.render())
        warnings = semantics.warnings()
        warned += len(warnings)
        if not quiet:
            summary = []
            if semantics.violation_rules:
                summary.append("violation-set")
            if semantics.allow_rules:
                summary.append("allow")
            if semantics.object_get_defaults:
                summary.append("%d default(s)" % len(semantics.object_get_defaults))
            if semantics.null_checks:
                summary.append("%d required-present" % len(semantics.null_checks))
            if len(semantics.resource_types) > 1:
                summary.append("cross-resource")
            if semantics.aggregated_packages:
                summary.append("aggregator")
            if semantics.config_metadata:
                summary.append("CONFIG-metadata gap")
            print("  %s -> %s [%s]" % (policy.name, target.name, ", ".join(summary) or "plain"))
            for warning in warnings:
                print("    ! %s" % warning)

    if not quiet:
        print("Wrote semantics for %d policies (%d warning(s))" % (len(policies), warned))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
