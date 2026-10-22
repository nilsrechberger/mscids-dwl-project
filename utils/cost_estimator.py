"""Cost calculator utility"""

import argparse

from utils import costs


def calc_costs(month: int = 12) -> None:
    """Prints the cost estimation for the given month since the first load.

    Args:
        month: Month to estimate, starting at 1. Storage accumulates.

    Returns:
        None
    """
    lambda_, s3, dwh = costs.LAMBDA, costs.s3(month), costs.dwh(month)
    print(
        f"Month {month}, {costs.GB_PER_MONTH * month:.0f} GB stored\n"
        f"Lambda: ~{lambda_:.2f} USD\n"
        f"S3: ~{s3:.2f} USD\n"
        f"DWH: ~{dwh:.2f} USD\n"
        f"Total: ~{lambda_ + s3 + dwh:.2f} USD/month"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cost calculator utility")
    parser.add_argument("--month", type=int, default=12, help="Month to estimate")
    calc_costs(parser.parse_args().month)
