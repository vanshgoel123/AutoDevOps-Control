import boto3
from config import *
import os

def get_ec2_clients(aws_key=None, aws_secret=None):
    key = aws_key or AWS_ACCESS_KEY
    secret = aws_secret or AWS_SECRET_KEY

    ec2_client = boto3.client(
        "ec2",
        region_name=REGION,
        aws_access_key_id=key,
        aws_secret_access_key=secret,
    )

    ec2_resource = boto3.resource(
        "ec2",
        region_name=REGION,
        aws_access_key_id=key,
        aws_secret_access_key=secret,
    )

    return ec2_client, ec2_resource


# 🔹 Create Key Pair
def create_key_pair(ec2_client, name):
    key_pair = ec2_client.create_key_pair(KeyName=name)
    key_path = f"{name}.pem"

    with open(key_path, "w") as f:
        f.write(key_pair["KeyMaterial"])

    os.chmod(key_path, 0o400)

    return name, key_path


# 🔹 Create Security Group
def create_security_group(ec2_client, name, backend_port=None):
    response = ec2_client.create_security_group(
        GroupName=name,
        Description="Allow SSH and HTTP"
    )

    sg_id = response["GroupId"]

    permissions = [
        {
            "IpProtocol": "tcp",
            "FromPort": 22,
            "ToPort": 22,
            "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
        },
        {
            "IpProtocol": "tcp",
            "FromPort": 80,
            "ToPort": 80,
            "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
        },
    ]

    if backend_port and backend_port != 80:
        permissions.append(
            {
                "IpProtocol": "tcp",
                "FromPort": backend_port,
                "ToPort": backend_port,
                "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
            }
        )

    ec2_client.authorize_security_group_ingress(
        GroupId=sg_id,
        IpPermissions=permissions,
    )

    return sg_id


# 🔹 Create EC2
def create_ec2(app_id, aws_key=None, aws_secret=None, backend_port=None):
    ec2_client, ec2_resource = get_ec2_clients(aws_key, aws_secret)

    key_name, key_path = create_key_pair(ec2_client, f"key-{app_id}")
    sg_id = create_security_group(ec2_client, f"app-{app_id}", backend_port=backend_port)

    instance = ec2_resource.create_instances(
        ImageId=AMI_ID,
        InstanceType=INSTANCE_TYPE,
        KeyName=key_name,
        SecurityGroupIds=[sg_id],
        BlockDeviceMappings=[
            {
                "DeviceName": "/dev/sda1",
                "Ebs": {
                    "VolumeSize": ROOT_VOLUME_SIZE_GB,
                    "VolumeType": "gp3",
                    "DeleteOnTermination": True,
                },
            }
        ],
        
        MinCount=1,
        MaxCount=1,
    )[0]

    instance.wait_until_running()
    instance.reload()

    return instance.public_ip_address, key_path, instance.id, key_name, sg_id