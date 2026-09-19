"""Used by each scraper to parse beforehand and then update/add listings in MongoDB"""

from datetime import datetime, timezone

import pandas as pd
from pymongo import UpdateOne

from cleanup import CLEANING_VERSION, parse_qualifications
from db import get_collection
from experience import UNKNOWN_STAGE, career_stage

# Don't delete stale listings if a scrape returned under this share of what we
# already store (guards against a half-failed scrape wiping an org). - claude addition
MIN_KEEP_RATIO = 0.5

def existing_ids(organization: str) -> set[str]:
    """IDs already stored for an org, so scrapers can skip re-fetching details."""
    cursor = get_collection().find({"organization": organization}, {"_id": 1})
    return {doc["_id"] for doc in cursor}


def _now_ms() -> datetime:
    """UTC now truncated to the millisecond precision MongoDB stores."""
    now = datetime.now(timezone.utc)
    return now.replace(microsecond=now.microsecond // 1000 * 1000)


def _build_update(rec: dict, organization: str, run_ts: datetime) -> UpdateOne:
    fields = {k: v for k, v in rec.items() if k != "_id" and v is not None}
    fields["organization"] = organization
    fields["last_seen"] = run_ts
    on_insert = {"first_seen": run_ts}

    if fields.get("qualifications"):
        fields.update(parse_qualifications(fields))
        fields["cleaning_version"] = CLEANING_VERSION
    else:
        # if there's no qualifications, then try to get the career stage from other fields
        # otherwise leave it alone
        stage = career_stage(
            job_level=fields.get("job_level"), job_type=fields.get("job_type"), qualifications= None, years = None, title=fields.get("title")
        )
        if stage != UNKNOWN_STAGE:
            fields["career_stage"] = stage

    if "posted_date" not in fields:
        on_insert["posted_date"] = run_ts
    if "career_stage" not in fields:
        on_insert["career_stage"] = UNKNOWN_STAGE

    return UpdateOne(
        {"_id": rec["_id"], "organization": organization},
        {"$set": fields, "$setOnInsert": on_insert},
        upsert=True,
    )


def upsert_listings(
    df: pd.DataFrame,
    organization: str,
    remove_stale: bool = True,
    min_keep_ratio: float = MIN_KEEP_RATIO,
) -> dict:
    """Upsert one organization's listings, scoped so other orgs are never touched."""
    if df.empty:
        print(f"No listings fetched; skipping DB write for {organization}")
        return {}

    if "_id" not in df.columns:
        df = df.reset_index().rename(columns={df.index.name or "index": "_id"})
    df = df.drop_duplicates(subset="_id", keep="last")
    DATE_COLUMNS = ("posted_date", "closing_date")

    for col in DATE_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], utc=True, errors="coerce", format="mixed")
    df = df.astype(object).where(df.notna(), None)
    records = df.to_dict("records")

    collection = get_collection()
    collection.create_index([("organization", 1), ("last_seen", 1)])

    run_ts = _now_ms()
    prior_count = (
        collection.count_documents({"organization": organization})
        if remove_stale
        else 0
    )

    ops = [_build_update(rec, organization, run_ts) for rec in records]
    result = collection.bulk_write(ops, ordered=False)
    summary = {
        "upserted": result.upserted_count,
        "modified": result.modified_count,
        "seen": len(records),
        "removed": 0,
    }
    print(
        f"Upserted: {summary['upserted']}, Modified: {summary['modified']}"
    )

    if remove_stale:
        if prior_count and len(records) < prior_count * min_keep_ratio:
            print(
                f"Scrape returned {len(records)} listings but {prior_count} are stored."
            )
        else:
            # delete records that haven't been updated since this run
            deleted = collection.delete_many(
                {"organization": organization, "last_seen": {"$ne": run_ts}}
            )
            summary["removed"] = deleted.deleted_count
            print(
                f"Removed stale listings: {deleted.deleted_count}"
            )

    return summary
