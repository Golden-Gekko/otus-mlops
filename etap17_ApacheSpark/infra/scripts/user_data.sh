#!/bin/bash
set -euo pipefail

log() {
  echo "[$(date)] [INFO] $1" | tee -a /home/ubuntu/setup.log
}

log "Starting setup of proxy VM"

# Install required tools
log "Installing s3cmd and curl"
apt-get update
apt-get install -y s3cmd curl

# Configure s3cmd for Yandex Object Storage
log "Configuring s3cmd with static access key"
cat > /home/ubuntu/.s3cfg <<EOF
[default]
access_key = ${access_key}
secret_key = ${secret_key}
host_base = storage.yandexcloud.net
host_bucket = %(bucket)s.storage.yandexcloud.net
use_https = True
EOF

chown ubuntu:ubuntu /home/ubuntu/.s3cfg
chmod 600 /home/ubuntu/.s3cfg

# Copy SSH key
mkdir -p /home/ubuntu/.ssh
echo '${private_key}' > /home/ubuntu/.ssh/otus-yc
chmod 600 /home/ubuntu/.ssh/otus-yc
chown -R ubuntu:ubuntu /home/ubuntu/.ssh

# Copy ALL data from the source bucket (provided by instructor) to our bucket
# log "Copying ALL files from s3://otus-mlops-source-data/ to s3://${s3_bucket}/"
# s3cmd sync --config=/home/ubuntu/.s3cfg --acl-public s3://otus-mlops-source-data/ s3://${s3_bucket}/

# if [ $? -eq 0 ]; then
#   log "Data successfully copied to bucket ${s3_bucket}"
# else
#   log "ERROR: Failed to copy data from source bucket"
#   exit 1
# fi

# Copy data from source bucket with optional limit
log "Preparing to copy files from s3://otus-mlops-source-data/"

# Create temp dir
mkdir -p /tmp

# Get full list of files (sorted by name = by date)
s3cmd --config=/home/ubuntu/.s3cfg ls s3://otus-mlops-source-data/ | awk '{print $4}' | sort > /tmp/all_files.txt

TOTAL_FILES=$(wc -l < /tmp/all_files.txt)
log "Total files found: $TOTAL_FILES"

# Apply limit
if [ -z '${copy_limit}' ]; then
  log "No limit: copying all files"
  cp /tmp/all_files.txt /tmp/files_to_copy.txt
elif [ '${copy_limit}' = "latest" ]; then
  log "Copying only the latest file"
  tail -n 1 /tmp/all_files.txt > /tmp/files_to_copy.txt
else
  if echo '${copy_limit}' | grep -qE '^[0-9]+$'; then
    N='${copy_limit}'
    if [ "$N" -gt "$TOTAL_FILES" ]; then
      N="$TOTAL_FILES"
    fi
    log "Copying first $N files"
    head -n "$N" /tmp/all_files.txt > /tmp/files_to_copy.txt
  else
    log "ERROR: invalid copy_limit value: '${copy_limit}'"
    exit 1
  fi
fi

# Copy files directly from source bucket to our bucket
while IFS= read -r filepath; do
  filename="$${filepath#s3://otus-mlops-source-data/}"
  log "Copying $filename directly to s3://${s3_bucket}/"
  s3cmd --config=/home/ubuntu/.s3cfg \
        cp --acl-public \
        "s3://otus-mlops-source-data/$filename" \
        "s3://${s3_bucket}/$filename"
done < /tmp/files_to_copy.txt

log "Data copy completed"

# Prepare the HDFS upload script (to be manually or automatically executed on master node later)
log "Creating upload_data_to_hdfs.sh script"
mkdir -p /home/ubuntu/scripts

# Note: we use 'EOF_SCRIPT' to avoid variable expansion during writing
cat > /home/ubuntu/scripts/upload_data_to_hdfs.sh <<'EOF'
#!/bin/bash
set -euo pipefail
if [ -z "$${S3_BUCKET:-}" ]; then
  echo "Error: S3_BUCKET not set"
  exit 1
fi
hdfs dfs -mkdir -p /user/ubuntu/data
hadoop distcp "s3a://$${S3_BUCKET}/" "/user/ubuntu/data/"
hdfs dfs -ls /user/ubuntu/data
echo "Done"
EOF

chmod +x /home/ubuntu/scripts/upload_data_to_hdfs.sh
chown ubuntu:ubuntu /home/ubuntu/scripts/upload_data_to_hdfs.sh

log "user_data.sh is ready at /home/ubuntu/scripts/"

# Prepare the Jupyter setup script
log "Creating setup_jupyter.sh script"

cat > /home/ubuntu/scripts/setup_jupyter.sh <<'EOF'
#!/bin/bash
set -euo pipefail

log() {
  echo "[$(date)] [JUPYTER-SETUP] $1"
}

log "Starting Jupyter + PySpark installation"

pip3 install --user --no-cache-dir jupyter pyspark findspark

log "Jupyter setup completed. To start: jupyter notebook --ip=0.0.0.0 --port=8888 --no-browser --allow-root --NotebookApp.token='' --NotebookApp.password='' --NotebookApp.disable_check_xsrf=True"
EOF

chmod +x /home/ubuntu/scripts/setup_jupyter.sh
chown ubuntu:ubuntu /home/ubuntu/scripts/setup_jupyter.sh

log "setup_jupyter.sh is ready at /home/ubuntu/scripts/"

