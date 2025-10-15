import os
import json
import boto3
from datetime import datetime, timedelta

# ---- config via env vars ----
REGION = os.getenv("AWS_REGION", "us-west-2")
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "7"))
OPTIN_TAG_KEY = os.getenv("OPTIN_TAG_KEY", "scro:optin")
OPTIN_TAG_VAL = os.getenv("OPTIN_TAG_VAL", "true")
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"   # keep true while testing

# optional: set a tag like scro:hourly_usd=0.023 to show savings estimates
COST_TAG_KEY = os.getenv("COST_TAG_KEY", "scro:hourly_usd")

# thresholds (tweak later)
IDLE_CPU_PCT = float(os.getenv("IDLE_CPU_PCT", "5"))
LOW_NET_BYTES = float(os.getenv("LOW_NET_BYTES", "50000"))  # ~50 KB per 6h period
UNDERUTIL_CPU_PCT = float(os.getenv("UNDERUTIL_CPU_PCT", "20"))

ec2 = boto3.client("ec2", region_name=REGION)
cw = boto3.client("cloudwatch", region_name=REGION)


def list_instances():
    """List RUNNING EC2 instances and their basic info + tags."""
    instances = []
    paginator = ec2.get_paginator("describe_instances")
    for page in paginator.paginate():
        for reservation in page.get("Reservations", []):
            for instance in reservation.get("Instances", []):
                if instance["State"]["Name"] != "running":
                    continue
                tags = {t["Key"]: t["Value"] for t in instance.get("Tags", [])}
                instances.append({
                    "id": instance["InstanceId"],
                    "name": tags.get("Name", "Unnamed"),
                    "optin": tags.get(OPTIN_TAG_KEY, "false").lower() == OPTIN_TAG_VAL,
                    "hourly_usd": float(tags.get(COST_TAG_KEY, "0") or 0.0),
                })
    return instances


def get_metric_average(instance_id, metric_name, statistic="Average"):
    """Return average value over lookback window at 6h period granularity."""
    end = datetime.utcnow()
    start = end - timedelta(days=LOOKBACK_DAYS)
    resp = cw.get_metric_statistics(
        Namespace="AWS/EC2",
        MetricName=metric_name,
        Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
        StartTime=start,
        EndTime=end,
        Period=3600 * 6,
        Statistics=[statistic],
    )
    dps = resp.get("Datapoints", [])
    if not dps:
        return 0.0
    avg = sum(dp.get(statistic, 0.0) for dp in dps) / len(dps)
    return round(float(avg), 2)


def analyze_instances(instances):
    results = []
    for inst in instances:
        iid = inst["id"]
        cpu = get_metric_average(iid, "CPUUtilization")
        net_in = get_metric_average(iid, "NetworkIn")
        net_out = get_metric_average(iid, "NetworkOut")

        # decide status
        if cpu < IDLE_CPU_PCT and net_in < LOW_NET_BYTES and net_out < LOW_NET_BYTES:
            status = "idle"
            recommendation = "stop"
        elif cpu < UNDERUTIL_CPU_PCT:
            status = "underutilized"
            recommendation = "downsize"
        else:
            status = "normal"
            recommendation = "keep"

        # savings estimates (only if tag provided)
        hourly = inst["hourly_usd"]
        monthly_hrs = 24 * 30
        est_monthly_savings = 0.0
        if hourly > 0:
            if recommendation == "stop":
                est_monthly_savings = round(hourly * monthly_hrs, 2)
            elif recommendation == "downsize":
                # rough: assume 40% savings on downsizing
                est_monthly_savings = round(hourly * monthly_hrs * 0.4, 2)

        results.append({
            "id": iid,
            "name": inst["name"],
            "cpu_avg_pct": cpu,
            "net_in_avg": net_in,
            "net_out_avg": net_out,
            "status": status,
            "recommendation": recommendation,
            "optin": inst["optin"],
            "est_monthly_savings_usd": est_monthly_savings
        })
    return results


def maybe_stop_idle(results):
    """Stop instances that are idle AND opted-in (tag scro:optin=true) when DRY_RUN=false."""
    to_stop = [r for r in results if r["recommendation"] == "stop" and r["optin"]]
    if not to_stop:
        return {"attempted": 0, "stopped_ids": [], "dry_run": DRY_RUN}

    ids = [r["id"] for r in to_stop]
    if DRY_RUN:
        print(f"[DRY_RUN] Would stop: {ids}")
        return {"attempted": len(ids), "stopped_ids": [], "dry_run": True}

    try:
        resp = ec2.stop_instances(InstanceIds=ids)
        stopped = [i["InstanceId"] for i in resp.get("StoppingInstances", [])]
        print(f"Stopped instances: {stopped}")
        return {"attempted": len(ids), "stopped_ids": stopped, "dry_run": False}
    except Exception as e:
        print(f"StopInstances error: {e}")
        return {"attempted": len(ids), "stopped_ids": [], "error": str(e), "dry_run": DRY_RUN}


def handler(event, context):
    instances = list_instances()
    analysis = analyze_instances(instances)
    action_report = maybe_stop_idle(analysis)

    # ----- compute summary counts -----
    idle_count = sum(1 for r in analysis if r["status"] == "idle")
    underutil_count = sum(1 for r in analysis if r["status"] == "underutilized")
    normal_count = sum(1 for r in analysis if r["status"] == "normal")

    summary_line = (
        f"Summary: {len(analysis)} instances → "
        f"{idle_count} idle | {underutil_count} underutilized | "
        f"{normal_count} normal | "
        f"{action_report.get('attempted',0)} actions executed "
        f"({'DRY-RUN' if action_report.get('dry_run') else 'LIVE'})"
    )

    summary = {
        "timestamp": datetime.utcnow().isoformat(),
        "region": REGION,
        "lookback_days": LOOKBACK_DAYS,
        "instance_count": len(analysis),
        "idle_count": idle_count,
        "underutilized_count": underutil_count,
        "normal_count": normal_count,
        "results": analysis,
        "actions": action_report,
        "summary_line": summary_line,
    }

    print("=" * 80)
    print(summary_line)
    print("=" * 80)
    print(json.dumps(summary, indent=2))
    return summary


