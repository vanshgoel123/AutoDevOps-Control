import paramiko
import time


def run_command(ip, key_path, command):
    key = paramiko.RSAKey.from_private_key_file(key_path)

    last_error = None
    ssh = None

    for _ in range(10):
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(
                hostname=ip,
                username="ubuntu",
                pkey=key,
                timeout=10,
                banner_timeout=20,
                auth_timeout=20,
            )
            break
        except Exception as exc:
            last_error = exc
            if ssh:
                ssh.close()
            time.sleep(5)

    if ssh is None or not ssh.get_transport() or not ssh.get_transport().is_active():
        raise ConnectionError(f"Unable to connect to port 22 on {ip}: {last_error}")

    stdin, stdout, stderr = ssh.exec_command(command)
    exit_code = stdout.channel.recv_exit_status()

    out = stdout.read().decode()
    err = stderr.read().decode()

    ssh.close()

    if exit_code != 0:
        raise RuntimeError(f"Remote command failed with exit_code={exit_code}. stderr={err.strip()} stdout={out.strip()}")

    return out, err