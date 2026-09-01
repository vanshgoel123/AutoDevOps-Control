import paramiko
import time
import os


def _get_ssh_client(ip, key_path):
    """Return an authenticated SSHClient, retrying up to 10 times."""
    key = paramiko.RSAKey.from_private_key_file(key_path)
    last_error = None

    for _ in range(10):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(
                hostname=ip,
                username="ubuntu",
                pkey=key,
                timeout=10,
                banner_timeout=20,
                auth_timeout=20,
            )
            return ssh
        except Exception as exc:
            last_error = exc
            ssh.close()
            time.sleep(5)

    raise ConnectionError(f"Unable to connect to {ip}: {last_error}")


def run_command(ip, key_path, command):
    """Run a shell command over SSH and return (stdout, stderr)."""
    ssh = _get_ssh_client(ip, key_path)

    try:
        stdin, stdout, stderr = ssh.exec_command(command, get_pty=False)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode()
        err = stderr.read().decode()
    finally:
        ssh.close()

    if exit_code != 0:
        raise RuntimeError(
            f"Remote command failed (exit={exit_code}). "
            f"stderr={err.strip()!r}  stdout={out.strip()!r}"
        )

    return out, err


def scp_file(ip, key_path, local_path, remote_path):
    """
    Copy a local file to the remote host via SFTP (paramiko).
    Used to transfer the .env file to the EC2 instance.
    """
    ssh = _get_ssh_client(ip, key_path)
    try:
        sftp = ssh.open_sftp()
        sftp.put(local_path, remote_path)
        sftp.close()
    finally:
        ssh.close()