import os
import json
import datetime as dt
import boto3

REGION = os.getenv("AWS_REGION", "us-east-1")
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "14"))
OPTIN_TAG_KEY = os.getenv("OPTIN_TAG_KEY", "scro:optin")
OPTIN_TAG_VAL = os.getenv("OPTIN_TAG_VAL", "true")

ec2 = boto3.client("ec2", region_name=REGION)
cw  = boto3.client("cloudwatch", region_name=REGION)

def handler(event, context):
    now = dt.datetime.utcnow().isoformat()
    return {
        "status": "ok",
        "message": f"Cloud Cost Optimizer heartbeat at {now}",
        "region": REGION,
        "lookback_days": LOOKBACK_DAYS,
        "optin_tag": f"{OPTIN_TAG_KEY}={OPTIN_TAG_VAL}"
    }
