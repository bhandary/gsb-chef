#!/usr/bin/env python3
"""Read-only TCP listener lookup for the verification scripts.

Usage:
  ports.py listeners 8000 2024 3000
  ports.py busy 8000 2024 3000
"""

from __future__ import annotations

import json
import os
import sys


def _listen_inodes(port: int) -> list[str]:
    needle = f":{port:04X}"
    found: list[str] = []
    for name in ("tcp", "tcp6"):
        path = f"/proc/net/{name}"
        try:
            lines = open(path, encoding="utf-8").read().splitlines()
        except OSError:
            continue
        for line in lines[1:]:
            parts = line.split()
            if len(parts) < 10 or parts[3] != "0A":
                continue
            if parts[1].rsplit(":", 1)[-1].upper() == f"{port:04X}":
                found.append(parts[9])
            elif parts[1].upper().endswith(needle):
                found.append(parts[9])
    return found


def _pids_for_inode(inode: str) -> list[int]:
    target = f"socket:[{inode}]"
    pids: list[int] = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        fd_dir = f"/proc/{pid}/fd"
        try:
            fds = os.listdir(fd_dir)
        except OSError:
            continue
        for fd in fds:
            try:
                if os.readlink(f"{fd_dir}/{fd}") == target:
                    pids.append(int(pid))
                    break
            except OSError:
                continue
    return pids


def listeners(ports: list[int]) -> list[dict[str, int | str]]:
    rows: list[dict[str, int | str]] = []
    seen: set[tuple[int, int]] = set()
    for port in ports:
        for inode in _listen_inodes(port):
            for pid in _pids_for_inode(inode):
                key = (port, pid)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    pgid = os.getpgid(pid)
                except OSError:
                    continue
                rows.append({"port": port, "pid": pid, "pgid": pgid, "inode": inode})
    return rows


def _ppid(pid: int) -> int:
    stat = open(f"/proc/{pid}/stat", encoding="utf-8").read()
    after = stat[stat.rfind(")") + 2 :]
    return int(after.split()[1])


def owned_by_leader(pid: int, leader: int) -> bool:
    try:
        if os.getpgid(pid) == leader or pid == leader:
            return True
    except OSError:
        return False
    seen: set[int] = set()
    current = pid
    while current > 1 and current not in seen:
        seen.add(current)
        if current == leader:
            return True
        try:
            current = _ppid(current)
        except OSError:
            return False
    return False


def main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[1] not in {"listeners", "busy", "owned"}:
        print("usage: ports.py listeners|busy PORT... | owned PID LEADER", file=sys.stderr)
        return 2
    if argv[1] == "owned":
        ok = owned_by_leader(int(argv[2]), int(argv[3]))
        print("yes" if ok else "no")
        return 0 if ok else 1
    ports = [int(item) for item in argv[2:]]
    rows = listeners(ports)
    if argv[1] == "listeners":
        print(json.dumps(rows))
        return 0
    print(json.dumps(rows))
    return 1 if rows else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
