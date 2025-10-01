from fastapi import FastAPI, Query
import subprocess, requests, os, json
from pathlib import Path
from google.cloud import storage

app = FastAPI()

DOWNLOAD_DIR = "/tmp/jars"
Path(DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)


def load_config_from_bucket(env: str, country: str):
    """Fetch JSON config from GCS bucket"""
    bucket_name = os.getenv("CONFIG_BUCKET", "dataflow-configs-bucket")
    file_path = f"{env}/{country}.json"

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(file_path)

    if not blob.exists():
        raise Exception(f"Config not found: gs://{bucket_name}/{file_path}")

    return json.loads(blob.download_as_text())


def download_jars(jar_urls):
    """Download JARs from Nexus to /tmp/jars"""
    downloaded = []
    for url in jar_urls:
        filename = url.split("/")[-1]
        path = os.path.join(DOWNLOAD_DIR, filename)

        if not os.path.exists(path):  # avoid redownload
            r = requests.get(url, stream=True, timeout=60)
            if r.status_code != 200:
                raise Exception(f"Failed to fetch {url}")
            with open(path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        downloaded.append(path)
    return downloaded


@app.post("/trigger")
def trigger_dataflow(
    country: str = Query(..., enum=["us", "uk", "au"]),
    env: str = Query(..., enum=["qa", "dev", "uat", "prod"])
):
    try:
        # 1. Load config from GCS
        config = load_config_from_bucket(env, country)
        project_id = config["project"]
        region = config.get("region", "us-central1")
        bucket = config["bucket"]
        jars = config.get("jars", [])
        main_jar_name = config.get("main_jar")
        extra_args = config.get("extra_args", [])

        if not jars:
            return {"error": "No jars specified in config"}

        # 2. Download jars
        downloaded_paths = download_jars(jars)

        # 3. Pick main jar
        main_jar = None
        for p in downloaded_paths:
            if p.endswith(main_jar_name):
                main_jar = p
                break
        if not main_jar:
            return {"error": f"main_jar {main_jar_name} not found in downloaded jars"}

        # 4. Build classpath
        classpath = ":".join(downloaded_paths)

        # 5. Build java command
        command = [
            "java", "-cp", classpath, "-jar", main_jar,
            f"--project={project_id}",
            f"--region={region}",
            f"--tempLocation={bucket}/tmp",
            f"--stagingLocation={bucket}/staging",
            f"--country={country}",
            f"--environment={env}"
        ] + extra_args

        # 6. Run job
        result = subprocess.run(command, capture_output=True, text=True)

        if result.returncode != 0:
            return {"status": "failed", "stderr": result.stderr, "command": command}

        return {"status": "success", "stdout": result.stdout, "command": command}

    except Exception as e:
        return {"error": str(e)}
