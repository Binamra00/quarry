"""
Reading `#N` out of free text.

TWO KINDS OF REFERENCE, AND THEY ARE NOT THE SAME EVIDENCE

    `Fixes #500` asserts that this change resolves issue 500. A bare `#500` says only that
    somebody mentioned it -- it may be context, a duplicate, a cross-reference, or an argument
    against. Both are evidence; they are not evidence of the same strength.

    The previous notebook treated them inconsistently: pull request bodies used closing
    references and fell back to mentions only when there were none, while commit messages used
    the union of both, undifferentiated. Two strictnesses inside one chain, and downstream
    could not see which had applied.

    So neither is discarded and neither is merged. Every reference is returned with its kind
    attached, and the decision about which to trust belongs to whatever consumes the links.
"""

import re
from typing import Dict

# `#123`, but not `foo#123` and not the `#123` inside a URL path. The lookbehind rejects a
# preceding word character or slash, which is what distinguishes an issue reference from a
# fragment in `github.com/owner/repo/pull/123`.
GH_REF = re.compile(r'(?<![\w/])#(\d+)\b')

# GitHub's own closing keywords. `[\s:]*` allows "Fixes: #12" and "Fixes#12" alongside the
# ordinary spacing.
CLOSE_REF = re.compile(r'\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b[\s:]*#(\d+)', re.I)

CLOSES = "closes"
MENTIONS = "mentions"


def references(text: str) -> Dict[int, str]:
    """
    Every issue or pull request number in `text`, mapped to how it was referenced.

    A number that appears both ways -- `Fixes #12 ... see also #12` -- is reported as `closes`.
    The stronger claim was made; the weaker one adds nothing.

    Returns {} for empty or None text, so callers need no guard.
    """
    closes = {int(n) for n in CLOSE_REF.findall(text or "")}
    out = {n: MENTIONS for n in (int(n) for n in GH_REF.findall(text or ""))}
    out.update({n: CLOSES for n in closes})
    return out
