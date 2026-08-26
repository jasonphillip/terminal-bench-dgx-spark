#!/usr/bin/env bash
# One-time host prep for running amd64 Terminal-Bench task images on an arm64 host.
# Both pieces are required: without binfmt the containers exit 255; without
# ip_forward the task network never comes up ("IPv4 forwarding is disabled").
set -euo pipefail

# 1) qemu user-mode emulation for amd64 images
docker run --privileged --rm tonistiigi/binfmt --install amd64

# 2) IPv4 forwarding (persist across reboots)
sysctl -w net.ipv4.ip_forward=1
mkdir -p /etc/sysctl.d
echo 'net.ipv4.ip_forward=1' > /etc/sysctl.d/99-tbench-ipforward.conf

echo "OK: amd64 emulation + ip_forward enabled"
