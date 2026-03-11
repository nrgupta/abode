import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent.listingsTool import run_daily_agent
from sheets.google_sheets import sync_to_sheets


async def main():
    print("Running daily apartment search...")
    listings = await run_daily_agent()

    if not listings:
        print("No listings found.")
        return

    await sync_to_sheets(listings)


if __name__ == "__main__":
    asyncio.run(main())
