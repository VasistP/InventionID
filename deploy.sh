#!/bin/bash
set -e

echo "=== Patent Agent Deployment ==="

# 1. Install Python dependencies
echo "Installing Python dependencies..."
pip3 install fastapi uvicorn[standard] python-multipart --break-system-packages 2>/dev/null || \
pip3 install fastapi "uvicorn[standard]" python-multipart

# 2. Install nginx
echo "Installing nginx..."
sudo dnf install -y nginx

# 3. Build frontend (Node.js must already be installed)
echo "Building frontend..."
cd /home/ec2-user/patent-agent/frontend
npm install
npm run build

# 4. Configure nginx
echo "Configuring nginx..."
sudo cp /home/ec2-user/patent-agent/config/nginx.conf /etc/nginx/conf.d/patent-agent.conf
# Remove default config if it exists
sudo rm -f /etc/nginx/conf.d/default.conf
sudo nginx -t
sudo systemctl enable nginx
sudo systemctl restart nginx

# 5. Configure and start backend service
echo "Configuring backend service..."
sudo cp /home/ec2-user/patent-agent/config/patent-agent-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable patent-agent-api
sudo systemctl restart patent-agent-api

echo ""
echo "=== Deployment complete ==="
echo "Backend status:"
sudo systemctl status patent-agent-api --no-pager -l || true
echo ""
echo "Nginx status:"
sudo systemctl status nginx --no-pager -l || true
echo ""
echo "IMPORTANT: Ensure EC2 security group allows inbound TCP port 80 from 0.0.0.0/0"
echo "Application URL: http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo 'YOUR_PUBLIC_IP')"
