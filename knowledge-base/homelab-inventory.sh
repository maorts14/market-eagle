#!/usr/bin/env bash
# Read-only homelab capacity inventory. No sudo, network addresses, serials, or environment variables.
set -u

section() { printf '\n== %s ==\n' "$1"; }
has() { command -v "$1" >/dev/null 2>&1; }

section "OS and kernel"
if [[ -r /etc/os-release ]]; then
  . /etc/os-release
  printf 'Distribution: %s\n' "${PRETTY_NAME:-unknown}"
fi
uname -srm

section "CPU"
if has lscpu; then
  lscpu | awk -F: '/^(Architecture|CPU\(s\)|Model name|Thread\(s\) per core|Core\(s\) per socket|Socket\(s\)):/ {gsub(/^[[:space:]]+/, "", $2); print $1 ": " $2}'
elif has nproc; then
  printf 'Logical CPUs: %s\n' "$(nproc)"
fi

section "Memory"
if has free; then free -h; else awk '/MemTotal|MemAvailable/ {print}' /proc/meminfo; fi

section "Disks (names, size, type only)"
if has lsblk; then lsblk -dn -o NAME,SIZE,TYPE,ROTA; fi
if has df; then df -hT /; fi

section "Container and orchestration tools"
for tool in docker kubectl k3s tailscale; do
  if has "$tool"; then
    case "$tool" in
      docker) docker --version 2>/dev/null || true; docker compose version 2>/dev/null || true ;;
      kubectl) kubectl version --client 2>/dev/null | head -n 2 ;;
      k3s) k3s --version 2>/dev/null | head -n 1 ;;
      tailscale) tailscale version 2>/dev/null | head -n 1 ;;
    esac
  else
    printf '%s: not found\n' "$tool"
  fi
done

section "Docker daemon capacity (if accessible)"
if has docker; then
  docker info --format 'Server: {{.ServerVersion}} | CPUs: {{.NCPU}} | Memory bytes: {{.MemTotal}} | Containers: {{.Containers}}' 2>/dev/null || printf 'Docker daemon unavailable to this user\n'
fi
