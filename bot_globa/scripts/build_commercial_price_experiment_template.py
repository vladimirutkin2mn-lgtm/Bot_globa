"""Build the disabled Numa commercial-price experiment template.

This command does not read runtime billing settings, create a checkout or enable an experiment.
"""

import argparse
import json
from pathlib import Path

from app.research.commercial_price_experiment import build_commercial_price_experiment_template


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON path. Without it, print the template to stdout.",
    )
    args = parser.parse_args()
    rendered = (
        json.dumps(build_commercial_price_experiment_template(), ensure_ascii=False, indent=2)
        + "\n"
    )
    if args.output is None:
        print(rendered, end="")
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
