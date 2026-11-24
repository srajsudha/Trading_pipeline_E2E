"""Extract Trading 212 datasets and land raw JSON pages in a UC volume."""
import argparse
import io
import json
import logging
import time
import uuid
from datetime import datetime, timezone

from databricks.sdk import WorkspaceClient

from trading_pipeline_e2e.trading212.client import Trading212Client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("trading212.extract")

# dataset -> (endpoint, paginated?)
DATASETS = {
    "account_summary": ("/equity/account/summary", False),
    "positions":       ("/equity/positions", False),
    "orders":          ("/equity/history/orders", True),
    "dividends":       ("/equity/history/dividends", True),
    "transactions":    ("/equity/history/transactions", True),
}


def land(w: WorkspaceClient, base: str, dataset: str, run_id: str, page_no: int, endpoint: str, payload) -> str:
    now = datetime.now(timezone.utc)
    path = f"{base}/{dataset}/ingest_date={now:%Y-%m-%d}/{dataset}_{now:%Y%m%dT%H%M%SZ}_{run_id}_{page_no:05d}.json"
    envelope = {
        "_meta": {"source": "trading212", "dataset": dataset, "endpoint": endpoint,
                  "run_id": run_id, "page": page_no, "extracted_at": now.isoformat()},
        "data": payload,
    }
    w.files.upload(path, io.BytesIO(json.dumps(envelope).encode()), overwrite=True)
    return path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--catalog", required=True)
    p.add_argument("--schema", required=True)
    p.add_argument("--volume", default="landing")
    p.add_argument("--account", default="invest_account")
    p.add_argument("--env", default="live", choices=["live", "demo"])
    p.add_argument("--secret-scope", default="trading212")
    p.add_argument("--datasets", default=",".join(DATASETS))
    args = p.parse_args()

    w = WorkspaceClient()  # local: uses DATABRICKS_CONFIG_PROFILE; job: automatic auth
    client = Trading212Client(
        api_key=w.dbutils.secrets.get(args.secret_scope, f"api_key_{args.account}"),
        api_secret=w.dbutils.secrets.get(args.secret_scope, "api_secret"),  # rename to api_secret_<account> if you aligned the names
        env=args.env,
    )
    base = f"/Volumes/{args.catalog}/{args.schema}/{args.volume}/trading212/{args.account}"
    run_id = uuid.uuid4().hex[:8]

    for dataset in [d.strip() for d in args.datasets.split(",")]:
        endpoint, paginated = DATASETS[dataset]
        pages = client.paginate(endpoint) if paginated else [client.get(endpoint)]
        n = 0
        for n, page in enumerate(pages, start=1):
            log.info("%s page %s -> %s", dataset, n, land(w, base, dataset, run_id, n, endpoint, page))
        log.info("%s done: %s page(s)", dataset, n)
        time.sleep(5)  # snapshot endpoints allow 1 request per 5s


if __name__ == "__main__":
    main()