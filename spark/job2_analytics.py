#!/usr/bin/env python3
"""Aurora Tickets - Spark job 2: curated to analytics and RDS."""

import argparse
from decimal import Decimal

from pyspark.sql import SparkSession, functions as F


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--student-id", required=True)
    parser.add_argument("--rds-host", required=True)
    parser.add_argument("--rds-port", default="3306")
    parser.add_argument("--rds-db", required=True)
    parser.add_argument("--rds-user", required=True)
    parser.add_argument("--rds-password", required=True)
    return parser.parse_args()


def s3a(bucket, prefix, suffix):
    clean_prefix = prefix.strip("/")
    clean_suffix = suffix.strip("/")
    return f"s3a://{bucket}/{clean_prefix}/{clean_suffix}"


def to_mysql_value(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def write_table(conn, table, ddl, columns, rows):
    with conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {table}")
        cur.execute(ddl)
        placeholders = ",".join(["%s"] * len(columns))
        col_sql = ",".join(columns)
        insert_sql = f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders})"
        payload = []
        for row in rows:
            payload.append(tuple(to_mysql_value(row[col]) for col in columns))
        if payload:
            cur.executemany(insert_sql, payload)
    conn.commit()


def main():
    args = parse_args()
    spark = (
        SparkSession.builder.appName("aurora-job2-analytics")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", "3")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    curated_base = s3a(args.bucket, args.prefix, "curated")
    analytics_base = s3a(args.bucket, args.prefix, "analytics")

    click = spark.read.parquet(f"{curated_base}/clickstream")
    client = click.filter(F.col("source") == "client").filter(F.col("session_id").isNotNull())

    session_flags = client.groupBy("dt", "session_id").agg(
        F.max(F.when(F.col("event_type") == "view_event_list", 1).otherwise(0)).alias(
            "has_event_list"
        ),
        F.max(F.when(F.col("event_type") == "view_event_detail", 1).otherwise(0)).alias(
            "has_event_detail"
        ),
        F.max(F.when(F.col("event_type") == "begin_checkout", 1).otherwise(0)).alias(
            "has_begin_checkout"
        ),
        F.max(F.when(F.col("event_type") == "purchase", 1).otherwise(0)).alias(
            "has_purchase"
        ),
    )

    funnel = (
        session_flags.groupBy("dt")
        .agg(
            F.count("*").alias("sessions_total"),
            F.sum("has_event_list").cast("long").alias("sessions_event_list"),
            F.sum("has_event_detail").cast("long").alias("sessions_event_detail"),
            F.sum("has_begin_checkout").cast("long").alias("sessions_begin_checkout"),
            F.sum("has_purchase").cast("long").alias("sessions_purchase"),
        )
        .withColumn(
            "conversion_rate",
            F.round(F.col("sessions_purchase") / F.col("sessions_total"), 6),
        )
        .withColumn("metric", F.lit("funnel"))
        .orderBy("dt")
    )

    detail_views = (
        client.filter(F.col("event_type") == "view_event_detail")
        .filter(F.col("event_id").isNotNull())
        .groupBy("dt", "event_id")
        .agg(F.count("*").cast("long").alias("detail_views"))
    )
    purchases = (
        client.filter(F.col("event_type") == "purchase")
        .filter(F.col("event_id").isNotNull())
        .groupBy("dt", "event_id")
        .agg(
            F.count("*").cast("long").alias("purchases"),
            F.round(F.sum(F.coalesce(F.col("amount"), F.lit(0.0))), 2).alias(
                "revenue_total"
            ),
        )
    )
    event_rank = (
        detail_views.join(purchases, ["dt", "event_id"], "full")
        .fillna({"detail_views": 0, "purchases": 0, "revenue_total": 0.0})
        .withColumn(
            "interest_to_purchase_ratio",
            F.round(
                F.when(F.col("purchases") > 0, F.col("detail_views") / F.col("purchases"))
                .otherwise(F.col("detail_views")),
                6,
            ),
        )
        .orderBy(F.col("dt"), F.col("interest_to_purchase_ratio").desc())
    )

    server = click.filter(F.col("event_type") == "server_request").filter(F.col("ip").isNotNull())
    anomaly_base = server.groupBy("dt", "ip").agg(
        F.count("*").cast("long").alias("requests"),
        F.sum(F.when(F.col("status_code") >= 400, 1).otherwise(0)).cast("long").alias(
            "errors"
        ),
        F.sum(F.when(F.col("event_type") == "purchase", 1).otherwise(0)).cast("long").alias(
            "purchases"
        ),
        F.countDistinct("session_id").cast("long").alias("sessions"),
        F.round(F.avg("latency_ms"), 2).alias("avg_latency_ms"),
        F.round(F.max("latency_ms"), 2).alias("max_latency_ms"),
    )
    anomalies = (
        anomaly_base.withColumn(
            "is_anomaly",
            (F.col("requests") >= 100)
            | (F.col("errors") >= 5)
            | (F.col("avg_latency_ms") >= 1000)
            | ((F.col("sessions") <= 2) & (F.col("requests") >= 50)),
        )
        .withColumn(
            "reason",
            F.concat_ws(
                ",",
                F.when(F.col("requests") >= 100, F.lit("high_requests")),
                F.when(F.col("errors") >= 5, F.lit("many_errors")),
                F.when(F.col("avg_latency_ms") >= 1000, F.lit("high_latency")),
                F.when(
                    (F.col("sessions") <= 2) & (F.col("requests") >= 50),
                    F.lit("repetitive_ip"),
                ),
            ),
        )
        .withColumn(
            "reason",
            F.when(F.length("reason") == 0, F.lit("normal")).otherwise(F.col("reason")),
        )
        .orderBy(F.col("is_anomaly").desc(), F.col("requests").desc())
    )

    funnel.write.mode("overwrite").partitionBy("dt", "metric").parquet(
        f"{analytics_base}/metrics_funnel_daily"
    )
    event_rank.write.mode("overwrite").partitionBy("dt", "event_id").parquet(
        f"{analytics_base}/metrics_event_rank"
    )
    anomalies.write.mode("overwrite").partitionBy("dt", "is_anomaly").parquet(
        f"{analytics_base}/metrics_anomalies"
    )

    import pymysql

    conn = pymysql.connect(
        host=args.rds_host,
        port=int(args.rds_port),
        user=args.rds_user,
        password=args.rds_password,
        database=args.rds_db,
        connect_timeout=20,
        autocommit=False,
    )
    try:
        write_table(
            conn,
            "metrics_funnel_daily",
            """
            CREATE TABLE metrics_funnel_daily (
              dt DATE PRIMARY KEY,
              sessions_total BIGINT,
              sessions_event_list BIGINT,
              sessions_event_detail BIGINT,
              sessions_begin_checkout BIGINT,
              sessions_purchase BIGINT,
              conversion_rate DOUBLE
            )
            """,
            [
                "dt",
                "sessions_total",
                "sessions_event_list",
                "sessions_event_detail",
                "sessions_begin_checkout",
                "sessions_purchase",
                "conversion_rate",
            ],
            funnel.select(
                "dt",
                "sessions_total",
                "sessions_event_list",
                "sessions_event_detail",
                "sessions_begin_checkout",
                "sessions_purchase",
                "conversion_rate",
            ).collect(),
        )
        write_table(
            conn,
            "metrics_event_rank",
            """
            CREATE TABLE metrics_event_rank (
              dt DATE,
              event_id BIGINT,
              detail_views BIGINT,
              purchases BIGINT,
              revenue_total DOUBLE,
              interest_to_purchase_ratio DOUBLE,
              PRIMARY KEY (dt, event_id)
            )
            """,
            [
                "dt",
                "event_id",
                "detail_views",
                "purchases",
                "revenue_total",
                "interest_to_purchase_ratio",
            ],
            event_rank.select(
                "dt",
                "event_id",
                "detail_views",
                "purchases",
                "revenue_total",
                "interest_to_purchase_ratio",
            ).limit(1000).collect(),
        )
        write_table(
            conn,
            "metrics_anomalies",
            """
            CREATE TABLE metrics_anomalies (
              dt DATE,
              ip VARCHAR(64),
              requests BIGINT,
              errors BIGINT,
              purchases BIGINT,
              sessions BIGINT,
              avg_latency_ms DOUBLE,
              max_latency_ms DOUBLE,
              is_anomaly BOOLEAN,
              reason VARCHAR(255),
              PRIMARY KEY (dt, ip)
            )
            """,
            [
                "dt",
                "ip",
                "requests",
                "errors",
                "purchases",
                "sessions",
                "avg_latency_ms",
                "max_latency_ms",
                "is_anomaly",
                "reason",
            ],
            anomalies.select(
                "dt",
                "ip",
                "requests",
                "errors",
                "purchases",
                "sessions",
                "avg_latency_ms",
                "max_latency_ms",
                "is_anomaly",
                "reason",
            ).filter(F.col("is_anomaly")).limit(1000).collect(),
        )
    finally:
        conn.close()

    print("job2_analytics completed")
    print(f"funnel_rows={funnel.count()}")
    print(f"event_rank_rows={event_rank.count()}")
    print(f"anomaly_rows={anomalies.filter(F.col('is_anomaly')).count()}")
    spark.stop()


if __name__ == "__main__":
    main()
