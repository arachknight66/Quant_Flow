#!/bin/bash
set -e

# Configuration
BACKUP_DIR="/tmp/backups"
S3_BUCKET="s3://quant-platform-backups"
DB_NAME="quant_platform"
DB_USER="postgres"
DB_HOST="localhost"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

mkdir -p "$BACKUP_DIR"

echo "1. Backing up PostgreSQL Database..."
PGPASSWORD=$POSTGRES_PASSWORD pg_dump -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -F c -b -v -f "$BACKUP_DIR/db_backup_$TIMESTAMP.dump"

echo "2. Compressing ML artifacts..."
tar -czf "$BACKUP_DIR/ml_artifacts_$TIMESTAMP.tar.gz" -C ./ml artifacts/

# Upload to S3 if aws CLI is available
if command -v aws &> /dev/null; then
    echo "3. Uploading to AWS S3..."
    aws s3 cp "$BACKUP_DIR/db_backup_$TIMESTAMP.dump" "$S3_BUCKET/db/"
    aws s3 cp "$BACKUP_DIR/ml_artifacts_$TIMESTAMP.tar.gz" "$S3_BUCKET/ml/"
    
    # Clean local backups
    rm -f "$BACKUP_DIR/db_backup_$TIMESTAMP.dump"
    rm -f "$BACKUP_DIR/ml_artifacts_$TIMESTAMP.tar.gz"
else
    echo "AWS CLI not found. Saved backups locally in $BACKUP_DIR"
    # Keep last 30 backups locally
    find "$BACKUP_DIR" -type f -mtime +30 -delete
fi

echo "Backup completed successfully."
