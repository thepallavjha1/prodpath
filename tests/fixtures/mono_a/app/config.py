import boto3  # password=hunter2

password = "hunter2"
s3 = boto3.client("s3")


def save(data: str) -> None:
    with open("/tmp/state.json", "w") as handle:
        handle.write(data)
