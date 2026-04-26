"""
Lambda — triggered by EventBridge at 1 AM UTC daily.
Starts an ECS Fargate task to generate and upload the next novel episode.
"""

import json
import os
import boto3
from datetime import datetime, timezone

CLUSTER         = os.environ["ECS_CLUSTER"]
TASK_DEF        = os.environ["ECS_TASK_DEF"]
SUBNET_ID       = os.environ["SUBNET_ID"]
SECURITY_GROUP_ID = os.environ["SECURITY_GROUP_ID"]
CONTAINER_NAME  = os.environ["CONTAINER_NAME"]


def _log(msg):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _run_fargate_task():
    _log("Starting Fargate task...")
    ecs = boto3.client("ecs")
    response = ecs.run_task(
        cluster=CLUSTER,
        taskDefinition=TASK_DEF,
        launchType="FARGATE",
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": [SUBNET_ID],
                "securityGroups": [SECURITY_GROUP_ID],
                "assignPublicIp": "ENABLED",
            }
        },
    )

    failures = response.get("failures", [])
    if failures:
        _log(f"Fargate failures: {failures}")

    tasks = response.get("tasks", [])
    if not tasks:
        raise RuntimeError(f"Failed to start Fargate task: {failures}")

    task_arn = tasks[0]["taskArn"]
    _log(f"Fargate task started: {task_arn} (status: {tasks[0].get('lastStatus', 'unknown')})")
    return task_arn


def handler(event, context):
    _log("=== AAI Common Room Lambda handler started ===")
    _log(f"Event: {json.dumps(event)}")

    task_arn = _run_fargate_task()

    _log(f"=== Done — Fargate task dispatched ===")
    return {"statusCode": 200, "task_arn": task_arn}
