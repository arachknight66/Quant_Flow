#!/bin/bash
set -e

# Setup Certbot and obtain TLS cert for domain
DOMAIN="yourplatform.com"
EMAIL="admin@yourplatform.com"

echo "Installing certbot and certbot-nginx plugin..."
if command -v apt-get &> /dev/null; then
    sudo apt-get update
    sudo apt-get install -y certbot python3-certbot-nginx
elif command -v yum &> /dev/null; then
    sudo yum install -y certbot python3-certbot-nginx
fi

echo "Requesting Let's Encrypt TLS certificate for $DOMAIN..."
sudo certbot certonly --nginx --non-interactive --agree-tos --email "$EMAIL" -d "$DOMAIN" -d "www.$DOMAIN"

echo "Adding automatic renewal cron job..."
CRON_JOB="0 0 * * * certbot renew --quiet"
(crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -

echo "TLS Setup Completed successfully."
