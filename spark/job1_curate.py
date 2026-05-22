#!/usr/bin/env python3
"""Aurora Tickets - Spark job 1: raw to curated."""

import argparse

from pyspark.sql import SparkSession, functions as F, types as T


PAYMENT_METHODS = ["card", "bizum", "transfer", "cash"]
CHANNELS = ["search", "social", "display", "email", "affiliate", "direct"]


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--student-id", required=True)
    return parser.parse_args()


def s3a(bucket, prefix, suffix):
    clean_prefix = prefix.strip("/")
    clean_suffix = suffix.strip("/")
    return f"s3a://{bucket}/{clean_prefix}/{clean_suffix}"


def ensure_column(df, name, dtype):
    if name not in df.columns:
        return df.withColumn(name, F.lit(None).cast(dtype))
    return df


def main():
    args = parse_args()
    spark = (
        SparkSession.builder.appName("aurora-job1-curate")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", "3")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    raw_base = s3a(args.bucket, args.prefix, "raw")
    curated_base = s3a(args.bucket, args.prefix, "curated")

    click = spark.read.json(f"{raw_base}/clickstream/*.jsonl")
    for name, dtype in [
        ("student_id", T.StringType()),
        ("timestamp", T.StringType()),
        ("dt", T.StringType()),
        ("session_id", T.StringType()),
        ("event_type", T.StringType()),
        ("source", T.StringType()),
        ("page", T.StringType()),
        ("request_path", T.StringType()),
        ("method", T.StringType()),
        ("status_code", T.StringType()),
        ("latency_ms", T.StringType()),
        ("event_id", T.StringType()),
        ("utm_campaign", T.StringType()),
        ("amount", T.StringType()),
        ("ip", T.StringType()),
        ("user_agent", T.StringType()),
        ("action", T.StringType()),
        ("element_id", T.StringType()),
        ("referrer", T.StringType()),
        ("query", T.StringType()),
    ]:
        click = ensure_column(click, name, dtype)

    click_curated = (
        click.filter(F.col("student_id") == args.student_id)
        .withColumn("event_ts", F.to_timestamp("timestamp"))
        .withColumn(
            "dt",
            F.when(F.length(F.col("dt")) == 10, F.col("dt")).otherwise(
                F.to_date("event_ts").cast("string")
            ),
        )
        .withColumn("event_type", F.coalesce(F.col("event_type"), F.lit("unknown")))
        .withColumn("source", F.coalesce(F.col("source"), F.lit("unknown")))
        .withColumn("event_id", F.col("event_id").cast("long"))
        .withColumn("amount", F.col("amount").cast("double"))
        .withColumn("status_code", F.col("status_code").cast("int"))
        .withColumn("latency_ms", F.col("latency_ms").cast("double"))
        .filter(F.col("dt").isNotNull())
    )

    (
        click_curated.write.mode("overwrite")
        .partitionBy("dt", "event_type")
        .parquet(f"{curated_base}/clickstream")
    )

    events_raw = spark.read.option("header", True).csv(f"{raw_base}/business/events.csv")
    events = (
        events_raw.withColumn("event_id", F.col("event_id").cast("long"))
        .withColumn("base_price", F.col("base_price").cast("double"))
        .withColumn("capacity", F.col("capacity").cast("long"))
        .withColumn("is_active", F.col("is_active").cast("int"))
        .withColumn("event_dt", F.to_date("event_date").cast("string"))
        .withColumn("dt", F.coalesce(F.col("event_dt"), F.lit("unknown")))
        .filter(F.col("event_id").isNotNull())
        .filter(F.length(F.trim(F.col("name"))) > 0)
        .filter(F.length(F.trim(F.col("city"))) > 0)
        .filter(F.length(F.trim(F.col("category"))) > 0)
        .filter((F.col("base_price") > 0) & (F.col("base_price") < 1000))
    )
    events.write.mode("overwrite").partitionBy("dt", "category").parquet(
        f"{curated_base}/events"
    )

    campaigns_raw = spark.read.option("header", True).csv(
        f"{raw_base}/business/campaigns.csv"
    )
    campaigns = (
        campaigns_raw.withColumn("monthly_cost", F.col("monthly_cost").cast("double"))
        .withColumn("dt", F.coalesce(F.col("start_dt"), F.lit("unknown")))
        .filter(F.length(F.trim(F.col("utm_campaign"))) > 0)
        .filter(F.col("channel").isin(CHANNELS))
        .filter((F.col("monthly_cost") >= 0) & (F.col("monthly_cost") < 100000))
    )
    campaigns.write.mode("overwrite").partitionBy("dt", "channel").parquet(
        f"{curated_base}/campaigns"
    )

    transactions_raw = spark.read.option("header", True).csv(
        f"{raw_base}/business/transactions.csv"
    )
    transactions = (
        transactions_raw.withColumn("event_id", F.col("event_id").cast("long"))
        .withColumn("quantity", F.col("quantity").cast("int"))
        .withColumn("amount", F.col("amount").cast("double"))
        .withColumn("tx_ts", F.to_timestamp("timestamp"))
        .withColumn(
            "dt",
            F.when(F.length(F.col("dt")) == 10, F.col("dt")).otherwise(
                F.to_date("tx_ts").cast("string")
            ),
        )
        .filter(F.length(F.trim(F.col("transaction_id"))) > 0)
        .filter(F.length(F.trim(F.col("session_id"))) > 0)
        .filter(F.col("event_id").isNotNull())
        .filter((F.col("amount") > 0) & (F.col("amount") < 5000))
        .filter(F.col("payment_method").isin(PAYMENT_METHODS))
    )
    transactions.write.mode("overwrite").partitionBy("dt", "payment_method").parquet(
        f"{curated_base}/transactions"
    )

    print("job1_curate completed")
    print(f"clickstream_rows={click_curated.count()}")
    print(f"events_rows={events.count()}")
    print(f"campaign_rows={campaigns.count()}")
    print(f"transaction_rows={transactions.count()}")
    spark.stop()


if __name__ == "__main__":
    main()
