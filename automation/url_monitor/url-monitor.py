from datetime import datetime
from time import perf_counter

import requests


def check_url(url: str):
    start = perf_counter()

    try:
        response = requests.get(
            url,
            timeout=10,
            headers={
                "User-Agent": "URL-Monitor/1.0"
            },
        )

        elapsed = perf_counter() - start

        return {
            "online": True,
            "status_code": response.status_code,
            "response_time": elapsed,
        }

    except requests.RequestException:
        return {
            "online": False,
            "status_code": None,
            "response_time": None,
        }


def main():
    print("=== URL Monitor ===\n")

    url = input("Target URL: ").strip()

    if not url.startswith(("http://", "https://")):
        print("Error: URL must start with http:// or https://")
        return

    result = check_url(url)

    print("\nMonitor Result")
    print("--------------")

    if result["online"]:
        print("Status     : ONLINE")
        print(f"HTTP Code  : {result['status_code']}")
        print(f"Response   : {result['response_time']:.2f}s")
    else:
        print("Status     : OFFLINE")
        print("HTTP Code  : -")
        print("Response   : -")

    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Checked at : {checked_at}")


if __name__ == "__main__":
    main()
