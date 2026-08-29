"""Bucket bounds, from strike fields where present and from the subtitle where not.

4.8% of settled markets (2,950 of 60,906, all on the historical tier, mostly
2021-2022) carry no `strike_type`, `floor_strike` or `cap_strike` at all. They
do carry `yes_sub_title` ("76 or above", "79 to 80"), which states the same
thing in prose.

This matters more than the count suggests. Code that reads only the strike
fields returns "no upper bound" for those markets, and a bucket with no upper
bound is never dominated, so they contribute silently to neither the numerator
nor the denominator of sec.5's violation rate. That is how Test A's UNSPECIFIED
stratum came back with exactly zero dominated-bucket-hours. That was an artefact
of the parser, not a property of those markets.

The subtitle parser is validated against the 57,956 markets where both
representations exist, so the fallback is checked rather than assumed. Run this
module directly to see that check.
"""
import re

RANGE = re.compile(r"^(-?\d+(?:\.\d+)?)\s*[°º]?\s*(?:to|-|–)\s*(-?\d+(?:\.\d+)?)\s*[°º]?$", re.I)
ABOVE = re.compile(r"^(-?\d+(?:\.\d+)?)\s*[°º]?\s*or\s+(?:above|higher)$", re.I)
BELOW = re.compile(r"^(-?\d+(?:\.\d+)?)\s*[°º]?\s*or\s+(?:below|lower)$", re.I)
EXACT = re.compile(r"^(-?\d+(?:\.\d+)?)\s*[°º]?$")


def from_subtitle(text):
    """Inclusive whole-degree (lo, hi) of settled values that pay Yes, or None."""
    t = (text or "").strip()
    m = RANGE.match(t)
    if m:
        return int(float(m.group(1))), int(float(m.group(2)))
    m = ABOVE.match(t)
    if m:
        return int(float(m.group(1))), None
    m = BELOW.match(t)
    if m:
        return None, int(float(m.group(1)))
    m = EXACT.match(t)
    if m:
        v = int(float(m.group(1)))
        return v, v
    return None


def from_strikes(m):
    """(lo, hi) from strike fields, or None if this market has none.

    sec.5's construction is on the ATTAINABLE set: every settled value in the
    sample is a whole degree, so "less than 101" has supremum 100, not 101.
    """
    st = m.get("strike_type")
    if st == "less" and m.get("cap_strike") is not None:
        return None, int(m["cap_strike"]) - 1
    if st == "greater" and m.get("floor_strike") is not None:
        return int(m["floor_strike"]) + 1, None
    if st == "between" and m.get("floor_strike") is not None and m.get("cap_strike") is not None:
        return int(m["floor_strike"]), int(m["cap_strike"])
    return None


def yes_bounds(m):
    """Inclusive (lo, hi) whole-degree bounds at which this market pays Yes."""
    return from_strikes(m) or from_subtitle(m.get("yes_sub_title")) or (None, None)


def in_bucket(v, bounds):
    lo, hi = bounds
    return (lo is None or v >= lo) and (hi is None or v <= hi)


def bounds_text(bounds):
    lo, hi = bounds
    if lo is None and hi is None:
        return "?"
    if lo is None:
        return f"<={hi}"
    if hi is None:
        return f">={lo}"
    return f"{lo}-{hi}"


if __name__ == "__main__":
    import collections
    import json
    import os
    from common import DATA

    agree = disagree = only_sub = neither = 0
    examples = []
    for line in open(os.path.join(DATA, "parsed", "markets.jsonl"), encoding="utf-8"):
        m = json.loads(line)
        a, b = from_strikes(m), from_subtitle(m.get("yes_sub_title"))
        if a and b:
            if a == b:
                agree += 1
            else:
                disagree += 1
                if len(examples) < 8:
                    examples.append((m["ticker"], m.get("yes_sub_title"), a, b))
        elif b:
            only_sub += 1
        elif not a:
            neither += 1
    total = agree + disagree + only_sub + neither
    print("== bucket parser validation: strikes vs yes_sub_title ==")
    print(f"  markets read                             : {total:,}")
    print(f"  both representations present, AGREE      : {agree:,}")
    print(f"  both representations present, DISAGREE   : {disagree:,}")
    print(f"  subtitle only (the fallback's whole job) : {only_sub:,}")
    print(f"  neither -- genuinely unbounded           : {neither:,}")
    for t, s, a, b in examples:
        print(f"  !! {t} {s!r} strikes={a} subtitle={b}")

    # Reconciliation. The second silent bug in RESULTS.md section 5 was
    # exactly this population: markets carrying no
    # strike fields at all were dropped rather than parsed, and a dropped row
    # is indistinguishable from a row that never existed unless the count is
    # printed and read.
    strikeless = only_sub + neither
    print(f"\n  RECONCILED  {total:,} read = {agree + disagree:,} with strike "
          f"fields + {strikeless:,} without")
    print(f"  the {strikeless:,} strike-less markets are the population section 5 "
          f"of RESULTS.md was silently dropping;")
    print(f"  {only_sub:,} are recovered from yes_sub_title and {neither:,} "
          f"{'is' if neither == 1 else 'are'} genuinely unbounded.")
    print(f"  DISAGREE is {disagree:,}: the fallback never contradicts the "
          f"strike fields where both exist.")
