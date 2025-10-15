# Cloud Cost Optimizer (AWS Lambda + Boto3 + CloudWatch)

Serverless Lambda that analyzes CloudWatch metrics (CPU, Network) to detect idle or underutilized EC2 instances and recommends cost-saving actions. Uses least-privilege IAM, scheduled via EventBridge, and updates a CloudWatch dashboard.

## Stack
- AWS Lambda (Python 3.11), Boto3
- CloudWatch (metrics, dashboard), EventBridge (schedule)
- IAM (least privilege)

## Status
✅ Step 1: project scaffold & Lambda heartbeat
