"""Build a human-review packet for Numa's fixed synthetic oracle cases.

No provider client is constructed here: this command never triggers paid research.
"""

import argparse
import json
from pathlib import Path

from app.research.oracle_product_review import build_product_review_packet


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON path. Without it, print the packet to stdout.",
    )
    args = parser.parse_args()
    rendered = json.dumps(build_product_review_packet(), ensure_ascii=False, indent=2) + "\n"
    if args.output is None:
        print(rendered, end="")
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
