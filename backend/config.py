import os


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DOCKER_USERNAME = os.getenv("DOCKER_USERNAME", "")

AWS_ACCESS_KEY = ""
AWS_SECRET_KEY = ""
REGION = os.getenv("AWS_REGION", "us-east-1")

AMI_ID = os.getenv("AMI_ID", "ami-0ec10929233384c7f")  # Ubuntu
INSTANCE_TYPE = os.getenv("INSTANCE_TYPE", "t3.micro")
ROOT_VOLUME_SIZE_GB = int(os.getenv("ROOT_VOLUME_SIZE_GB", "30"))
