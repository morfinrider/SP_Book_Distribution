import re

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

APP_URL = "https://sjpbooks26.streamlit.app"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            print("Opening SJP Books app...")
            page.goto(
                APP_URL,
                wait_until="domcontentloaded",
                timeout=120000,
            )

            wake_button = page.get_by_role(
                "button",
                name=re.compile(
                    r"yes, get this app back up",
                    re.IGNORECASE,
                ),
            )

            try:
                wake_button.wait_for(
                    state="visible",
                    timeout=20000,
                )
            except PlaywrightTimeoutError:
                print("No visible wake-up button detected.")
            else:
                print("Sleeping app detected. Clicking wake-up...")
                wake_button.click(timeout=30000)

                wake_button.wait_for(
                    state="hidden",
                    timeout=120000,
                )

                print("Wake-up button disappeared.")

            # Allow the app to initialise
            page.wait_for_timeout(15000)

            print("Final URL:", page.url)
            print("Page title:", page.title())
            print("Automation completed.")

        finally:
            browser.close()


if __name__ == "__main__":
    main()
