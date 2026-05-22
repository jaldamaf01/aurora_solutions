#!/usr/bin/env python3
"""Deploy Aurora Tickets in an AWS Academy Learner Lab."""

import argparse
import json
import random
import shutil
import string
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError


PROJECT = "AuroraTickets"
DEFAULT_REGION = "us-east-1"
DEFAULT_STUDENT_ID = "juana"
INSTANCE_PROFILE = "LabInstanceProfile"
KEY_NAME = "vockey"
RDS_DB = "aurora"
RDS_USER = "auroraadmin"
DEFAULT_RDS_PASSWORD = "AuroraJuana2026!"


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--student-id", default=DEFAULT_STUDENT_ID)
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--instance-type", default="t3.micro")
    parser.add_argument("--rds-class", default="db.t3.micro")
    return parser.parse_args()


def slug(value):
    chars = []
    for ch in value.lower():
        if ch.isalnum():
            chars.append(ch)
        elif ch in ("-", "_"):
            chars.append("-")
    text = "".join(chars).strip("-")
    return text or "student"


def state_path(solution_dir):
    return solution_dir / ".state" / "deploy_state.json"


def load_state(solution_dir):
    path = state_path(solution_dir)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_state(solution_dir, state):
    path = state_path(solution_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def random_password():
    alphabet = string.ascii_letters + string.digits
    token = "".join(random.choice(alphabet) for _ in range(16))
    return f"Aurora{token}26!"


def resolve_bundle_source(solution_dir, repo_root, name):
    candidates = [
        solution_dir / name,
        repo_root / "Tema 4" / name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    checked = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"Missing bundle source for {name}. Checked: {checked}")


def build_bundle(repo_root, solution_dir):
    build_dir = solution_dir / "bundle_build"
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True)

    bundle_root = build_dir / "aurora_bundle"
    bundle_root.mkdir()
    shutil.copytree(
        resolve_bundle_source(solution_dir, repo_root, "webapp"),
        bundle_root / "webapp",
    )
    shutil.copytree(
        resolve_bundle_source(solution_dir, repo_root, "generators"),
        bundle_root / "generators",
    )
    shutil.copytree(
        resolve_bundle_source(solution_dir, repo_root, "simulators"),
        bundle_root / "simulators",
    )
    shutil.copytree(solution_dir / "spark", bundle_root / "spark")

    docs = bundle_root / "docs"
    docs.mkdir()
    (docs / "BUILD_INFO.txt").write_text(
        f"Built at {datetime.now(timezone.utc).isoformat()}\n", encoding="utf-8"
    )

    zip_path = solution_dir / "aurora_bundle.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in bundle_root.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(bundle_root).as_posix())
    return zip_path


def ensure_bucket(s3, bucket, region):
    try:
        s3.head_bucket(Bucket=bucket)
        return
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code"))
        if code not in ("404", "NoSuchBucket", "NotFound"):
            raise
    kwargs = {"Bucket": bucket}
    if region != "us-east-1":
        kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
    s3.create_bucket(**kwargs)
    s3.put_bucket_versioning(
        Bucket=bucket, VersioningConfiguration={"Status": "Suspended"}
    )


def upload_file(s3, bucket, key, path):
    s3.upload_file(str(path), bucket, key)
    return f"s3://{bucket}/{key}"


def get_default_network(ec2):
    vpcs = ec2.describe_vpcs(Filters=[{"Name": "is-default", "Values": ["true"]}])[
        "Vpcs"
    ]
    if not vpcs:
        raise RuntimeError("No default VPC found")
    vpc_id = vpcs[0]["VpcId"]
    subnets = ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])[
        "Subnets"
    ]
    subnets = sorted(subnets, key=lambda s: s["AvailabilityZone"])
    return vpc_id, [s["SubnetId"] for s in subnets]


def find_sg(ec2, vpc_id, name):
    groups = ec2.describe_security_groups(
        Filters=[
            {"Name": "vpc-id", "Values": [vpc_id]},
            {"Name": "group-name", "Values": [name]},
        ]
    )["SecurityGroups"]
    return groups[0]["GroupId"] if groups else None


def ensure_sg(ec2, vpc_id, name, desc):
    sg_id = find_sg(ec2, vpc_id, name)
    if sg_id:
        return sg_id
    return ec2.create_security_group(GroupName=name, Description=desc, VpcId=vpc_id)[
        "GroupId"
    ]


def authorize_ingress(ec2, sg_id, permissions):
    try:
        ec2.authorize_security_group_ingress(
            GroupId=sg_id, IpPermissions=permissions
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "InvalidPermission.Duplicate":
            raise


def ensure_security(ec2, student_slug, vpc_id):
    ec2_sg = ensure_sg(
        ec2,
        vpc_id,
        f"aurora-{student_slug}-ec2-sg",
        "Aurora EC2 and Spark security group",
    )
    rds_sg = ensure_sg(
        ec2,
        vpc_id,
        f"aurora-{student_slug}-rds-sg",
        "Aurora RDS security group",
    )
    public_tcp = []
    for port in [22, 80, 8080, 8081, 4040]:
        public_tcp.append(
            {
                "IpProtocol": "tcp",
                "FromPort": port,
                "ToPort": port,
                "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
            }
        )
    authorize_ingress(ec2, ec2_sg, public_tcp)
    authorize_ingress(
        ec2,
        ec2_sg,
        [{"IpProtocol": "-1", "UserIdGroupPairs": [{"GroupId": ec2_sg}]}],
    )
    authorize_ingress(
        ec2,
        rds_sg,
        [
            {
                "IpProtocol": "tcp",
                "FromPort": 3306,
                "ToPort": 3306,
                "UserIdGroupPairs": [{"GroupId": ec2_sg}],
            }
        ],
    )
    return ec2_sg, rds_sg


def get_ubuntu_ami(ssm, ec2):
    name = "/aws/service/canonical/ubuntu/server/22.04/stable/current/amd64/hvm/ebs-gp2/ami-id"
    try:
        return ssm.get_parameter(Name=name)["Parameter"]["Value"]
    except ClientError:
        images = ec2.describe_images(
            Owners=["099720109477"],
            Filters=[
                {
                    "Name": "name",
                    "Values": ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"],
                },
                {"Name": "architecture", "Values": ["x86_64"]},
                {"Name": "virtualization-type", "Values": ["hvm"]},
                {"Name": "root-device-type", "Values": ["ebs"]},
            ],
        )["Images"]
        images.sort(key=lambda img: img["CreationDate"], reverse=True)
        return images[0]["ImageId"]


def ensure_db_subnet_group(rds, name, subnet_ids):
    try:
        rds.describe_db_subnet_groups(DBSubnetGroupName=name)
        return
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "DBSubnetGroupNotFoundFault":
            raise
    rds.create_db_subnet_group(
        DBSubnetGroupName=name,
        DBSubnetGroupDescription="Aurora Tickets DB subnet group",
        SubnetIds=subnet_ids[:3],
        Tags=[{"Key": "Project", "Value": PROJECT}],
    )


def ensure_rds_started(rds, db_id, db_class, subnet_group, rds_sg, password):
    try:
        db = rds.describe_db_instances(DBInstanceIdentifier=db_id)["DBInstances"][0]
        return db, False
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "DBInstanceNotFound":
            raise
    print(f"Creating RDS {db_id}; this starts in the background.")
    rds.create_db_instance(
        DBInstanceIdentifier=db_id,
        AllocatedStorage=20,
        DBInstanceClass=db_class,
        Engine="mysql",
        MasterUsername=RDS_USER,
        MasterUserPassword=password,
        DBName=RDS_DB,
        VpcSecurityGroupIds=[rds_sg],
        DBSubnetGroupName=subnet_group,
        PubliclyAccessible=False,
        BackupRetentionPeriod=0,
        DeletionProtection=False,
        Tags=[
            {"Key": "Project", "Value": PROJECT},
            {"Key": "Name", "Value": db_id},
        ],
    )
    return rds.describe_db_instances(DBInstanceIdentifier=db_id)["DBInstances"][0], True


def wait_rds(rds, db_id):
    print("Waiting for RDS to become available.")
    waiter = rds.get_waiter("db_instance_available")
    waiter.wait(
        DBInstanceIdentifier=db_id,
        WaiterConfig={"Delay": 30, "MaxAttempts": 80},
    )
    db = rds.describe_db_instances(DBInstanceIdentifier=db_id)["DBInstances"][0]
    return db["Endpoint"]["Address"]


def reset_rds_password(rds, db_id, password):
    print("Resetting RDS master password to the saved deployment password.")
    rds.modify_db_instance(
        DBInstanceIdentifier=db_id,
        MasterUserPassword=password,
        ApplyImmediately=True,
    )
    return wait_rds(rds, db_id)


def find_instance(ec2, student_id, role):
    reservations = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Project", "Values": [PROJECT]},
            {"Name": "tag:StudentId", "Values": [student_id]},
            {"Name": "tag:Role", "Values": [role]},
            {
                "Name": "instance-state-name",
                "Values": ["pending", "running", "stopping", "stopped"],
            },
        ]
    )["Reservations"]
    instances = [i for r in reservations for i in r["Instances"]]
    instances.sort(key=lambda i: i["LaunchTime"], reverse=True)
    return instances[0] if instances else None


def make_user_data(
    role,
    bootstrap_url,
    bundle_url,
    student_id,
    bucket,
    prefix,
    region,
    master_private="",
    rds_host="",
    rds_password="",
):
    return f"""#!/bin/bash
set -euxo pipefail
exec > >(tee -a /var/log/aurora-userdata-loader.log | logger -t aurora-loader -s 2>/dev/console) 2>&1
curl -fsSL '{bootstrap_url}' -o /tmp/aurora_bootstrap.sh
chmod +x /tmp/aurora_bootstrap.sh
/tmp/aurora_bootstrap.sh '{role}' '{bundle_url}' '{student_id}' '{bucket}' '{prefix}' '{region}' '{master_private}' '{rds_host}' '{RDS_DB}' '{RDS_USER}' '{rds_password}'
"""


def launch_or_get_instance(
    ec2,
    *,
    role,
    name,
    student_id,
    ami,
    instance_type,
    subnet_id,
    sg_id,
    user_data,
    volume_size,
):
    existing = find_instance(ec2, student_id, role)
    if existing:
        state = existing["State"]["Name"]
        if state == "stopped":
            ec2.start_instances(InstanceIds=[existing["InstanceId"]])
        print(f"Reusing {role}: {existing['InstanceId']} ({state})")
        return existing["InstanceId"]

    print(f"Launching {role}")
    resp = ec2.run_instances(
        ImageId=ami,
        InstanceType=instance_type,
        KeyName=KEY_NAME,
        MinCount=1,
        MaxCount=1,
        IamInstanceProfile={"Name": INSTANCE_PROFILE},
        NetworkInterfaces=[
            {
                "DeviceIndex": 0,
                "SubnetId": subnet_id,
                "Groups": [sg_id],
                "AssociatePublicIpAddress": True,
            }
        ],
        UserData=user_data,
        BlockDeviceMappings=[
            {
                "DeviceName": "/dev/sda1",
                "Ebs": {
                    "VolumeSize": volume_size,
                    "VolumeType": "gp3",
                    "DeleteOnTermination": True,
                },
            }
        ],
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [
                    {"Key": "Name", "Value": name},
                    {"Key": "Project", "Value": PROJECT},
                    {"Key": "StudentId", "Value": student_id},
                    {"Key": "Role", "Value": role},
                ],
            }
        ],
    )
    return resp["Instances"][0]["InstanceId"]


def describe_instance(ec2, instance_id):
    return ec2.describe_instances(InstanceIds=[instance_id])["Reservations"][0][
        "Instances"
    ][0]


def tag_value(instance, key, default=""):
    return next((t["Value"] for t in instance.get("Tags", []) if t["Key"] == key), default)


def wait_instances_running(ec2, instance_ids):
    waiter = ec2.get_waiter("instance_running")
    waiter.wait(InstanceIds=instance_ids, WaiterConfig={"Delay": 10, "MaxAttempts": 60})


def put_query_definition(logs, name, log_group, query):
    existing = logs.describe_query_definitions(queryDefinitionNamePrefix=name).get(
        "queryDefinitions", []
    )
    match = next((q for q in existing if q["name"] == name), None)
    kwargs = {
        "name": name,
        "logGroupNames": [log_group],
        "queryString": query,
    }
    if match:
        kwargs["queryDefinitionId"] = match["queryDefinitionId"]
    logs.put_query_definition(**kwargs)


def configure_cloudwatch(logs, cloudwatch, student_id, region):
    log_group = f"/aurora/{student_id}/clickstream"
    try:
        logs.create_log_group(logGroupName=log_group)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceAlreadyExistsException":
            raise
    logs.put_retention_policy(logGroupName=log_group, retentionInDays=14)

    queries = {
        "aurora_q1_funnel_daily": """
fields dt, session_id, event_type
| filter student_id = "{student}" and source = "client"
| filter event_type in ["view_event_list","view_event_detail","begin_checkout","purchase"]
| stats count_distinct(session_id) as sessions by dt, event_type
| sort dt asc, event_type asc
""".strip().format(student=student_id),
        "aurora_q2_top_events_interest_vs_revenue": """
fields dt, event_id, event_type, amount
| filter student_id = "{student}" and source = "client" and ispresent(event_id)
| filter event_type in ["view_event_detail","purchase"]
| stats count(*) as events, sum(amount) as revenue_total by dt, event_id, event_type
| sort dt asc, events desc
""".strip().format(student=student_id),
        "aurora_q3_errors_and_latency": """
fields @timestamp, request_path, status_code, latency_ms
| filter student_id = "{student}" and event_type = "server_request"
| stats count(*) as requests, avg(latency_ms) as avg_latency_ms, pct(latency_ms, 95) as p95_latency_ms, max(status_code) as max_status by bin(1h), request_path
| sort bin(1h) desc
""".strip().format(student=student_id),
        "aurora_q4_anomalies_suspected_bots": """
fields dt, ip, session_id, latency_ms
| filter student_id = "{student}" and event_type = "server_request"
| stats count(*) as requests, count_distinct(session_id) as sessions, avg(latency_ms) as avg_latency_ms by dt, ip
| filter requests > 100 or (sessions <= 2 and requests > 50) or avg_latency_ms > 1000
| sort requests desc
""".strip().format(student=student_id),
    }
    for name, query in queries.items():
        put_query_definition(logs, name, log_group, query)

    dashboard_name = f"aurora-dashboard-{student_id}"
    source = f"SOURCE '{log_group}'"
    widgets = [
        {
            "type": "log",
            "x": 0,
            "y": 0,
            "width": 12,
            "height": 6,
            "properties": {
                "region": region,
                "title": "Funnel diario",
                "view": "table",
                "query": f"{source} | fields dt, session_id, event_type | filter student_id = \"{student_id}\" and source = \"client\" | filter event_type in [\"view_event_list\",\"view_event_detail\",\"begin_checkout\",\"purchase\"] | stats count_distinct(session_id) as sessions by dt, event_type | sort dt asc",
            },
        },
        {
            "type": "log",
            "x": 12,
            "y": 0,
            "width": 12,
            "height": 6,
            "properties": {
                "region": region,
                "title": "Interes vs ingresos",
                "view": "table",
                "query": f"{source} | fields dt, event_id, event_type, amount | filter student_id = \"{student_id}\" and source = \"client\" and ispresent(event_id) | filter event_type in [\"view_event_detail\",\"purchase\"] | stats count(*) as events, sum(amount) as revenue_total by dt, event_id, event_type | sort events desc",
            },
        },
        {
            "type": "log",
            "x": 0,
            "y": 6,
            "width": 12,
            "height": 6,
            "properties": {
                "region": region,
                "title": "Errores y latencia",
                "view": "table",
                "query": f"{source} | fields request_path, status_code, latency_ms | filter student_id = \"{student_id}\" and event_type = \"server_request\" | stats count(*) as requests, avg(latency_ms) as avg_latency_ms, pct(latency_ms,95) as p95_latency_ms, max(status_code) as max_status by request_path | sort requests desc",
            },
        },
        {
            "type": "log",
            "x": 12,
            "y": 6,
            "width": 12,
            "height": 6,
            "properties": {
                "region": region,
                "title": "IPs anomalas",
                "view": "table",
                "query": f"{source} | fields dt, ip, session_id, latency_ms | filter student_id = \"{student_id}\" and event_type = \"server_request\" | stats count(*) as requests, count_distinct(session_id) as sessions, avg(latency_ms) as avg_latency_ms by dt, ip | filter requests > 100 or (sessions <= 2 and requests > 50) or avg_latency_ms > 1000 | sort requests desc",
            },
        },
    ]
    cloudwatch.put_dashboard(
        DashboardName=dashboard_name, DashboardBody=json.dumps({"widgets": widgets})
    )
    return log_group, dashboard_name


def main():
    args = parse_args()
    student_id = args.student_id
    student_slug = slug(student_id)
    repo_root = Path(__file__).resolve().parents[1]
    solution_dir = Path(__file__).resolve().parent

    session = boto3.Session(region_name=args.region)
    sts = session.client("sts")
    account = sts.get_caller_identity()["Account"]
    state = load_state(solution_dir)

    bucket = state.get("bucket") or f"aurora-{account}-{student_slug}-20260508"
    prefix = state.get("prefix") or f"aurora/{student_id}"
    had_rds_password = bool(state.get("rds_password"))
    rds_password = state.get("rds_password") or DEFAULT_RDS_PASSWORD
    db_id = state.get("rds_identifier") or f"aurora-{student_slug}-db"
    state.update(
        {
            "account": account,
            "region": args.region,
            "student_id": student_id,
            "bucket": bucket,
            "prefix": prefix,
            "rds_identifier": db_id,
            "rds_db": RDS_DB,
            "rds_user": RDS_USER,
            "rds_password": rds_password,
        }
    )
    save_state(solution_dir, state)

    ec2 = session.client("ec2")
    s3 = session.client("s3")
    ssm = session.client("ssm")
    rds = session.client("rds")
    logs = session.client("logs")
    cloudwatch = session.client("cloudwatch")

    ensure_bucket(s3, bucket, args.region)
    log_group, dashboard_name = configure_cloudwatch(logs, cloudwatch, student_id, args.region)

    bundle_zip = build_bundle(repo_root, solution_dir)
    bootstrap_path = solution_dir / "remote" / "bootstrap.sh"
    bundle_key = f"{prefix}/deploy/aurora_bundle.zip"
    bootstrap_key = f"{prefix}/deploy/bootstrap.sh"
    upload_file(s3, bucket, bundle_key, bundle_zip)
    upload_file(s3, bucket, bootstrap_key, bootstrap_path)
    bundle_url = s3.generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": bundle_key}, ExpiresIn=43200
    )
    bootstrap_url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": bootstrap_key},
        ExpiresIn=43200,
    )

    vpc_id, subnet_ids = get_default_network(ec2)
    ec2_sg, rds_sg = ensure_security(ec2, student_slug, vpc_id)
    subnet_group = f"aurora-{student_slug}-db-subnets"
    ensure_db_subnet_group(rds, subnet_group, subnet_ids)
    _db, rds_created = ensure_rds_started(
        rds, db_id, args.rds_class, subnet_group, rds_sg, rds_password
    )

    ami = get_ubuntu_ami(ssm, ec2)

    master_ud = make_user_data(
        "spark-master",
        bootstrap_url,
        bundle_url,
        student_id,
        bucket,
        prefix,
        args.region,
    )
    master_id = launch_or_get_instance(
        ec2,
        role="spark-master",
        name=f"aurora-{student_slug}-spark-master",
        student_id=student_id,
        ami=ami,
        instance_type=args.instance_type,
        subnet_id=subnet_ids[0],
        sg_id=ec2_sg,
        user_data=master_ud,
        volume_size=12,
    )
    wait_instances_running(ec2, [master_id])
    master = describe_instance(ec2, master_id)
    master_private = master["PrivateIpAddress"]

    other_ids = []
    for idx, role in enumerate(["spark-worker-1", "spark-worker-2", "spark-worker-3"], start=1):
        ud = make_user_data(
            role,
            bootstrap_url,
            bundle_url,
            student_id,
            bucket,
            prefix,
            args.region,
            master_private=master_private,
        )
        other_ids.append(
            launch_or_get_instance(
                ec2,
                role=role,
                name=f"aurora-{student_slug}-{role}",
                student_id=student_id,
                ami=ami,
                instance_type=args.instance_type,
                subnet_id=subnet_ids[0],
                sg_id=ec2_sg,
                user_data=ud,
                volume_size=12,
            )
        )

    web_ud = make_user_data(
        "web",
        bootstrap_url,
        bundle_url,
        student_id,
        bucket,
        prefix,
        args.region,
    )
    web_id = launch_or_get_instance(
        ec2,
        role="web",
        name=f"aurora-{student_slug}-web",
        student_id=student_id,
        ami=ami,
        instance_type=args.instance_type,
        subnet_id=subnet_ids[0],
        sg_id=ec2_sg,
        user_data=web_ud,
        volume_size=20,
    )
    wait_instances_running(ec2, other_ids + [web_id])

    rds_host = wait_rds(rds, db_id)
    if not rds_created and not had_rds_password:
        rds_host = reset_rds_password(rds, db_id, rds_password)

    submit_ud = make_user_data(
        "submit",
        bootstrap_url,
        bundle_url,
        student_id,
        bucket,
        prefix,
        args.region,
        master_private=master_private,
        rds_host=rds_host,
        rds_password=rds_password,
    )
    submit_id = launch_or_get_instance(
        ec2,
        role="submit",
        name=f"aurora-{student_slug}-submit",
        student_id=student_id,
        ami=ami,
        instance_type=args.instance_type,
        subnet_id=subnet_ids[0],
        sg_id=ec2_sg,
        user_data=submit_ud,
        volume_size=20,
    )
    wait_instances_running(ec2, [submit_id])

    ids = [master_id] + other_ids + [web_id, submit_id]
    instances = [describe_instance(ec2, iid) for iid in ids]

    state.update(
        {
            "account": account,
            "region": args.region,
            "student_id": student_id,
            "bucket": bucket,
            "prefix": prefix,
            "log_group": log_group,
            "dashboard_name": dashboard_name,
            "rds_identifier": db_id,
            "rds_host": rds_host,
            "rds_db": RDS_DB,
            "rds_user": RDS_USER,
            "rds_password": rds_password,
            "master_private_ip": master_private,
            "instances": {
                tag_value(i, "Name", i["InstanceId"]): {
                    "instance_id": i["InstanceId"],
                    "state": i["State"]["Name"],
                    "private_ip": i.get("PrivateIpAddress"),
                    "public_ip": i.get("PublicIpAddress"),
                    "role": tag_value(i, "Role"),
                }
                for i in instances
            },
            "web_url": f"http://{describe_instance(ec2, web_id).get('PublicIpAddress')}",
            "spark_master_url": f"http://{describe_instance(ec2, master_id).get('PublicIpAddress')}:8080",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    save_state(solution_dir, state)

    print(json.dumps(state, indent=2, sort_keys=True))
    print("Deployment launched. Bootstrap continues inside the EC2 instances.")
    print("Check status objects under:")
    print(f"s3://{bucket}/{prefix}/status/")


if __name__ == "__main__":
    main()
