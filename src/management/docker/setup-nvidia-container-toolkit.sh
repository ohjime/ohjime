#!/usr/bin/env bash
#
# One-time host setup: install the NVIDIA Container Toolkit so Docker
# containers can use the GPU (this box has Docker but no `nvidia`
# runtime, so `docker run --gpus all` currently fails).
#
# Follows the official install guide:
# https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html
#
# Usage:
#   sudo ./setup-nvidia-container-toolkit.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "This script needs root. Run: sudo $0" >&2
  exit 1
fi

KEYRING=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | gpg --dearmor --yes -o "$KEYRING"

curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed "s#deb https://#deb [signed-by=$KEYRING] https://#g" \
  > /etc/apt/sources.list.d/nvidia-container-toolkit.list

apt-get update
apt-get install -y nvidia-container-toolkit

# Register the nvidia runtime in /etc/docker/daemon.json and reload.
nvidia-ctk runtime configure --runtime=docker
systemctl restart docker

echo
echo "Done. Verify GPU access with:"
echo "  docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi"
