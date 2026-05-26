import argparse
import os
from typing import Optional

from app.scraper import load_env_vars, run_scraper


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Scrape CourseFinder.ai and download results for one or more search terms.'
    )
    parser.add_argument(
        '-e',
        '--email',
        help='Email address to use for login. Falls back to SCRAPER_EMAIL in .env.',
    )
    parser.add_argument(
        '-p',
        '--password',
        help='Password to use for login. Falls back to SCRAPER_PASSWORD in .env.',
    )
    parser.add_argument(
        '-s',
        '--search',
        nargs='+',
        required=True,
        help='Search query or list of search queries.',
    )
    parser.add_argument(
        '--headless',
        action=argparse.BooleanOptionalAction,
        default=None,
        help='Run browser in headless mode, or use HEADLESS from .env if unset.',
    )
    args = parser.parse_args()

    load_env_vars()
    email = args.email or os.getenv('SCRAPER_EMAIL')
    password = args.password or os.getenv('SCRAPER_PASSWORD')

    if not email or not password:
        parser.error(
            'Missing credentials. Provide --email and --password, or set SCRAPER_EMAIL and SCRAPER_PASSWORD in .env.'
        )

    results = run_scraper(email, password, args.search, headless=args.headless)

    for item in results:
        status = 'SUCCESS' if item['success'] else 'FAILED'
        print(
            f'[{status}] query="{item["query"]}" '
            f'filename="{item["filename"]}" error="{item["error"]}"'
        )


if __name__ == '__main__':
    main()
