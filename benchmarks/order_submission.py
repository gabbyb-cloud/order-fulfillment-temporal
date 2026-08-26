import os
import statistics
import time

import httpx
from dotenv import load_dotenv


REQUESTS = 25
URL = "http://127.0.0.1:8000/orders"


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * p))
    return ordered[index]


def main() -> None:
    load_dotenv()

    api_key = os.environ["ORDER_API_KEY"]

    headers = {"X-API-Key": api_key}
    payload = {
        "customer_name": "Benchmark User",
        "item": "Mechanical Keyboard",
        "quantity": 1,
        "amount_cents": 12999,
    }

    latencies_ms: list[float] = []
    successful = 0

    with httpx.Client(timeout=10.0) as client:
        for i in range(REQUESTS):
            start = time.perf_counter()

            response = client.post(
                URL,
                headers=headers,
                json=payload,
            )

            elapsed_ms = (time.perf_counter() - start) * 1000

            if response.status_code == 201:
                successful += 1
                latencies_ms.append(elapsed_ms)

            print(
                f"Request {i + 1:02}/{REQUESTS}: "
                f"{response.status_code} "
                f"{elapsed_ms:.2f} ms"
            )

    if not latencies_ms:
        raise SystemExit("No successful requests; benchmark cannot continue.")

    print()
    print("Benchmark results")
    print("-----------------")
    print(f"Requests:   {REQUESTS}")
    print(f"Successful: {successful}")
    print(f"Average:    {statistics.mean(latencies_ms):.2f} ms")
    print(f"p50:        {statistics.median(latencies_ms):.2f} ms")
    print(f"p95:        {percentile(latencies_ms, 0.95):.2f} ms")
    print(f"Min:        {min(latencies_ms):.2f} ms")
    print(f"Max:        {max(latencies_ms):.2f} ms")


if __name__ == "__main__":
    main()
