import boto3
import os
import time
from config import REGION, AWS_ACCESS_KEY, AWS_SECRET_KEY

def full_cleanup(instance_id, key_name, sg_id, key_path, aws_key, aws_secret):
    key = aws_key or AWS_ACCESS_KEY
    secret = aws_secret or AWS_SECRET_KEY

    ec2 = boto3.client(
        "ec2",
        region_name=REGION,
        aws_access_key_id=key,
        aws_secret_access_key=secret,
    )

    if instance_id:
        ec2.terminate_instances(InstanceIds=[instance_id])
        try:
            waiter = ec2.get_waiter("instance_terminated")
            waiter.wait(InstanceIds=[instance_id])
        except Exception:
            pass
    if key_name:
        try:
            ec2.delete_key_pair(KeyName=key_name)
        except Exception:
            pass

    if sg_id:
        for _ in range(5):
            try:
                ec2.delete_security_group(GroupId=sg_id)
                break
            except Exception:
                time.sleep(3)

    candidates = [
        key_path,
        f"{key_name}.pem" if key_name else None,
        os.path.join(os.getcwd(), f"{key_name}.pem") if key_name else None,
        os.path.join(os.path.dirname(__file__), f"{key_name}.pem") if key_name else None,
    ]

    for path in candidates:
        if path and os.path.exists(path):
            try:
                os.remove(path)
                break
            except Exception:
                pass


def delete_instance(instance_id, aws_key=None, aws_secret=None):
    key = aws_key or AWS_ACCESS_KEY
    secret = aws_secret or AWS_SECRET_KEY

    ec2 = boto3.client(
        "ec2",
        region_name=REGION,
        aws_access_key_id=key,
        aws_secret_access_key=secret,
    )

    key_name = None
    sg_ids = []

    try:
        response = ec2.describe_instances(InstanceIds=[instance_id])
        reservations = response.get("Reservations", [])
        if reservations and reservations[0].get("Instances"):
            instance = reservations[0]["Instances"][0]
            key_name = instance.get("KeyName")
            sg_ids = [sg.get("GroupId") for sg in instance.get("SecurityGroups", []) if sg.get("GroupId")]
    except Exception:
        raise

    ec2.terminate_instances(InstanceIds=[instance_id])

    try:
        waiter = ec2.get_waiter("instance_terminated")
        waiter.wait(InstanceIds=[instance_id])
    except Exception:
        pass

    if key_name:
        try:
            ec2.delete_key_pair(KeyName=key_name)
        except Exception:
            pass

        candidates = [
            f"{key_name}.pem",
            os.path.join(os.getcwd(), f"{key_name}.pem"),
            os.path.join(os.path.dirname(__file__), f"{key_name}.pem"),
        ]
        for key_path in candidates:
            if os.path.exists(key_path):
                try:
                    os.remove(key_path)
                    break
                except Exception:
                    pass

    for sg_id in sg_ids:
        try:
            sg_info = ec2.describe_security_groups(GroupIds=[sg_id])["SecurityGroups"][0]
            if sg_info.get("GroupName", "").startswith("app-"):
                for _ in range(5):
                    try:
                        ec2.delete_security_group(GroupId=sg_id)
                        break
                    except Exception:
                        time.sleep(3)
        except Exception:
            pass

    return True