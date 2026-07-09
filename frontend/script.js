let deploymentInProgress = false;

function setDeployButtonState(isDisabled) {
    const deployBtn = document.getElementById("deploy_btn");
    if (!deployBtn) {
        return;
    }
    deployBtn.disabled = isDisabled;
    deployBtn.innerText = isDisabled ? "Deploying..." : "Deploy App";
}

async function deploy() {
    if (deploymentInProgress) {
        document.getElementById("status").innerText = "Deployment already in progress";
        return;
    }

    let repo = document.getElementById("repo").value.trim();
    let awsKey = document.getElementById("aws_key").value.trim();
    let awsSecret = document.getElementById("aws_secret").value.trim();
    let backend_port = document.getElementById("backend_port").value.trim();
    let frontend_port = document.getElementById("frontend_port").value.trim();
    let backend_df = document.getElementById("backend_dockerfile").value.trim();
    let frontend_df = document.getElementById("frontend_dockerfile").value.trim();
    const status = document.getElementById("status");
    const result = document.getElementById("result");

    if (!repo) {
        status.innerText = "Enter a repository URL first";
        result.innerHTML = "";
        return;
    }

    if (!repo.startsWith("https://github.com/")) {
        status.innerText = "Only GitHub repositories are supported";
        result.innerHTML = "";
        return;
    }

    if (!awsKey || !awsSecret) {
        status.innerText = "AWS credentials are required";
        result.innerHTML = "";
        return;
    }

    try {
        localStorage.setItem("aws_key", awsKey);
        localStorage.setItem("aws_secret", awsSecret);
    } catch (e) {}

    if (!backend_df && !frontend_df) {
        status.innerText = "Please provide at least one Dockerfile";
        result.innerHTML = "";
        return;
    }

    if (backend_df && !backend_port) {
        status.innerText = "Backend port is required when backend Dockerfile is provided";
        result.innerHTML = "";
        return;
    }

    if (frontend_df) {
        frontend_port = "80";
        document.getElementById("frontend_port").value = "80";
    }

    deploymentInProgress = true;
    setDeployButtonState(true);

    status.innerText = "Deployment queued...";
    result.innerHTML = "";
    result.className = "result loading";

    let res = await fetch("/deploy", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            repo_url: repo,
            aws_key: awsKey,
            aws_secret: awsSecret,
            backend_port: backend_port ? Number(backend_port) : null,
            frontend_port: frontend_df ? 80 : null,
            backend_dockerfile: backend_df || null,
            frontend_dockerfile: frontend_df || null,
        }),
    });
    let data = await res.json();

    if (!res.ok) {
        status.innerText = "Could not start deployment";
        result.innerText = data.detail || "Validation failed";
        result.className = "result error";
        deploymentInProgress = false;
        setDeployButtonState(false);
        return;
    }

    if (!data.task_id) {
        status.innerText = "Could not start deployment";
        result.className = "result error";
        deploymentInProgress = false;
        setDeployButtonState(false);
        return;
    }

    result.innerHTML = `<div class="progress-card"><strong>Task queued</strong><p>Tracking deployment id ${data.task_id}</p></div>`;
    check(data.task_id);
}

async function check(id) {
    let interval = setInterval(async () => {
        try {
            let res = await fetch("/status/" + id);
            let data = await res.json();
            const status = document.getElementById("status");
            const result = document.getElementById("result");

            if (data.meta && data.meta.step) {
                status.innerText = data.meta.step;
            }

            if (data.state === "PENDING") {
                status.innerText = "Waiting for worker...";
            }

            if (data.state === "STARTED") {
                status.innerText = "Deploying on infrastructure...";
            }

            if (data.state === "SUCCESS") {
                clearInterval(interval);
                deploymentInProgress = false;
                setDeployButtonState(false);

                if (data.result && (data.result.url || data.result.backend_url || data.result.frontend_url)) {
                    status.innerText = "Deployment successful";
                    result.className = "result success";
                    let links = [];
                    const instanceId = data.result.instance_id ? `<div><strong>Instance:</strong> ${data.result.instance_id}</div>` : "";
                    const appId = data.result.app_id ? `<div><strong>App ID:</strong> ${data.result.app_id}</div>` : "";

                    if (data.result.frontend_url) {
                        links.push(`<div><strong>Frontend:</strong> <a href="${data.result.frontend_url}" target="_blank" rel="noopener noreferrer">${data.result.frontend_url}</a></div>`);
                    }

                    if (data.result.backend_url) {
                        links.push(`<div><strong>Backend:</strong> <a href="${data.result.backend_url}" target="_blank" rel="noopener noreferrer">${data.result.backend_url}</a></div>`);
                    }

                    if (links.length === 0 && data.result.url) {
                        links.push(`<a href="${data.result.url}" target="_blank" rel="noopener noreferrer">${data.result.url}</a>`);
                    }

                    result.innerHTML = `<div class="progress-card success-card">${appId}${instanceId}${links.join("")}</div>`;
                } else {
                    status.innerText = "Deployment failed";
                    result.className = "result error";
                    result.innerText = data.result && data.result.error ? data.result.error : "Unknown task error";
                }
            }

            if (data.state === "FAILURE") {
                clearInterval(interval);
                deploymentInProgress = false;
                setDeployButtonState(false);
                status.innerText = "Deployment failed";
                result.className = "result error";
                result.innerText = "Task failed on worker";
            }
        } catch (error) {
            clearInterval(interval);
            deploymentInProgress = false;
            setDeployButtonState(false);
            document.getElementById("status").innerText = "Network error while checking status";
            result.className = "result error";
        }
    }, 2000);
}

function fillExample() {
    const repo = document.getElementById("repo");
    const awsKey = document.getElementById("aws_key");
    const awsSecret = document.getElementById("aws_secret");
    const backendPort = document.getElementById("backend_port");
    const frontendPort = document.getElementById("frontend_port");
    const backendDf = document.getElementById("backend_dockerfile");
    const frontendDf = document.getElementById("frontend_dockerfile");

    repo.value = repo.value || "https://github.com/user/repo";
    awsKey.value = awsKey.value || "YOUR_AWS_ACCESS_KEY";
    awsSecret.value = awsSecret.value || "YOUR_AWS_SECRET_KEY";
    backendPort.value = backendPort.value || "8000";
    frontendPort.value = "80";
    backendDf.value = backendDf.value || `FROM python:3.11-slim\nWORKDIR /app\nCOPY . /app\nRUN pip install -r requirements.txt\nEXPOSE 8000\nCMD [\"uvicorn\", \"main:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8000\"]`;
    frontendDf.value = frontendDf.value || `FROM nginx:alpine\nCOPY . /usr/share/nginx/html\nEXPOSE 80`;
}