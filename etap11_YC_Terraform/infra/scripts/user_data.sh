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

# Copy ALL data from the source bucket (provided by instructor) to our bucket
log "Copying ALL files from s3://otus-mlops-source-data/ to s3://${s3_bucket}/"
s3cmd sync --config=/home/ubuntu/.s3cfg --acl-public s3://otus-mlops-source-data/ s3://${s3_bucket}/

if [ $? -eq 0 ]; then
  log "Data successfully copied to bucket ${s3_bucket}"
else
  log "ERROR: Failed to copy data from source bucket"
  exit 1
fi

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

log "user_data.sh completed successfully"