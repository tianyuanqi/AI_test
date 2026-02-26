#!/usr/bin/env python3
import argparse
import csv
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


@dataclass
class Sample:
    timestamp_s: float
    cpu_percent: Optional[float]
    mem_pss_kb: Optional[int]
    mem_percent: Optional[float]
    gc_count: Optional[int]
    net_rx_bytes: Optional[int]
    net_tx_bytes: Optional[int]


def run_adb(cmd: str) -> str:
    result = subprocess.run(
        ["adb", "shell", cmd],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return result.stdout.strip()


def get_uid(package: str) -> Optional[str]:
    output = run_adb("cmd package list packages -U")
    for line in output.splitlines():
        if line.startswith("package:") and package in line:
            match = re.search(r"uid:(\d+)", line)
            if match:
                return match.group(1)
    output = run_adb(f"dumpsys package {package}")
    match = re.search(r"userId=(\d+)", output)
    return match.group(1) if match else None


def get_pid(package: str) -> Optional[str]:
    output = run_adb(f"pidof {package}")
    if not output:
        return None
    return output.split()[0]


def parse_top_cpu(output: str, pid: str) -> Optional[float]:
    lines = [line for line in output.splitlines() if line.strip()]
    header_index = None
    for idx, line in enumerate(lines):
        if line.strip().startswith("PID"):
            header_index = idx
            break
    if header_index is None:
        return None
    headers = re.split(r"\s+", lines[header_index].strip())
    try:
        cpu_idx = headers.index("%CPU")
    except ValueError:
        try:
            cpu_idx = headers.index("CPU%")
        except ValueError:
            return None
    for line in lines[header_index + 1 :]:
        parts = re.split(r"\s+", line.strip())
        if not parts:
            continue
        if parts[0] == pid and len(parts) > cpu_idx:
            try:
                return float(parts[cpu_idx])
            except ValueError:
                return None
    return None


def parse_cpuinfo(output: str, package: str) -> Optional[float]:
    for line in output.splitlines():
        if package in line:
            match = re.search(r"\\s*(\\d+(?:\\.\\d+)?)%\\s+\\d+/" + re.escape(package), line)
            if match:
                return float(match.group(1))
    return None


def get_cpu_percent(package: str) -> Optional[float]:
    pid = get_pid(package)
    if pid:
        output = run_adb(f"top -b -n 1 -p {pid}")
        top_cpu = parse_top_cpu(output, pid)
        if top_cpu is not None:
            return top_cpu
    cpuinfo_output = run_adb("dumpsys cpuinfo")
    return parse_cpuinfo(cpuinfo_output, package)


def parse_mem_pss(output: str) -> Optional[int]:
    match = re.search(r"TOTAL PSS:\s+(\d+)", output)
    if match:
        return int(match.group(1))
    match = re.search(r"TOTAL:\s+(\d+)", output)
    if match:
        return int(match.group(1))
    return None


def get_total_mem_kb() -> Optional[int]:
    output = run_adb("cat /proc/meminfo | head -n 1")
    match = re.search(r"MemTotal:\\s+(\\d+)\\s+kB", output)
    if match:
        return int(match.group(1))
    return None


def parse_gc_count(output: str) -> Optional[int]:
    match = re.search(r"GC\s*:\s*(\d+)", output)
    if match:
        return int(match.group(1))
    return None


def get_mem_gc(package: str) -> tuple[Optional[int], Optional[int]]:
    output = run_adb(f"dumpsys meminfo {package}")
    return parse_mem_pss(output), parse_gc_count(output)


def parse_netstats(output: str) -> tuple[Optional[int], Optional[int]]:
    rx = None
    tx = None
    rx_matches = re.findall(r"rxBytes=(\d+)", output)
    tx_matches = re.findall(r"txBytes=(\d+)", output)
    if rx_matches:
        rx = int(rx_matches[-1])
    if tx_matches:
        tx = int(tx_matches[-1])
    return rx, tx


def get_net_bytes(uid: Optional[str]) -> tuple[Optional[int], Optional[int]]:
    if not uid:
        return None, None
    output = run_adb(f"dumpsys netstats --uid {uid}")
    return parse_netstats(output)


def get_power_mah(package: str) -> Optional[float]:
    output = run_adb(f"dumpsys batterystats {package}")
    match = re.search(r"Estimated power use \(mAh\):\s*([0-9.]+)", output)
    if match:
        return float(match.group(1))
    match = re.search(r"Total estimated power use \(mAh\):\s*([0-9.]+)", output)
    if match:
        return float(match.group(1))
    return None


def ensure_adb() -> None:
    result = subprocess.run(
        ["adb", "devices"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("adb command failed. Ensure adb is installed and accessible.")


def write_csv(samples: list[Sample], csv_path: str) -> None:
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "timestamp_s",
                "cpu_percent",
                "mem_pss_kb",
                "mem_percent",
                "gc_count",
                "net_rx_bytes",
                "net_tx_bytes",
            ]
        )
        for sample in samples:
            writer.writerow(
                [
                    f"{sample.timestamp_s:.2f}",
                    sample.cpu_percent,
                    sample.mem_pss_kb,
                    sample.mem_percent,
                    sample.gc_count,
                    sample.net_rx_bytes,
                    sample.net_tx_bytes,
                ]
            )


def plot_series(samples: list[Sample], power_mah: Optional[float], output_dir: str) -> str:
    timestamps = [sample.timestamp_s for sample in samples]
    cpu = [sample.cpu_percent for sample in samples]
    mem = [sample.mem_percent for sample in samples]
    gc = [sample.gc_count for sample in samples]
    rx = [sample.net_rx_bytes for sample in samples]
    tx = [sample.net_tx_bytes for sample in samples]

    fig, axes = plt.subplots(3, 2, figsize=(12, 12))
    ax_cpu = axes[0, 0]
    ax_mem = axes[0, 1]
    ax_gc = axes[1, 0]
    ax_net = axes[1, 1]
    ax_power = axes[2, 0]
    axes[2, 1].axis("off")

    ax_cpu.plot(timestamps, cpu, marker="o")
    ax_cpu.set_title("CPU %")
    ax_cpu.set_xlabel("Time (s)")
    ax_cpu.set_ylabel("CPU %")

    ax_mem.plot(timestamps, mem, marker="o", color="tab:green")
    ax_mem.set_title("Memory Usage (%)")
    ax_mem.set_xlabel("Time (s)")
    ax_mem.set_ylabel("Memory %")

    ax_gc.plot(timestamps, gc, marker="o", color="tab:orange")
    ax_gc.set_title("GC Count")
    ax_gc.set_xlabel("Time (s)")
    ax_gc.set_ylabel("GC Count")

    ax_net.plot(timestamps, rx, marker="o", label="RX Bytes")
    ax_net.plot(timestamps, tx, marker="o", label="TX Bytes")
    ax_net.set_title("Network Bytes")
    ax_net.set_xlabel("Time (s)")
    ax_net.set_ylabel("Bytes")
    ax_net.legend()

    if power_mah is not None:
        ax_power.bar(["Total mAh"], [power_mah], color="tab:red")
        ax_power.set_ylabel("mAh")
    else:
        ax_power.text(0.5, 0.5, "Power data unavailable", ha="center", va="center")
        ax_power.set_xticks([])
        ax_power.set_yticks([])
    ax_power.set_title("Power Consumption")

    fig.tight_layout()
    plot_path = os.path.join(output_dir, "performance_charts.png")
    fig.savefig(plot_path)
    plt.close(fig)
    return plot_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor Android app performance via adb.")
    parser.add_argument(
        "--package",
        default="com.nothing.smartcenter",
        help="App package name (default: com.nothing.smartcenter)",
    )
    parser.add_argument("--duration", type=int, default=30, help="Duration to monitor in seconds")
    parser.add_argument("--interval", type=float, default=1.0, help="Sampling interval in seconds")
    parser.add_argument("--output", default="output", help="Output directory")
    parser.add_argument(
        "--out-dir",
        dest="output",
        help="Output directory (alias for --output)",
    )
    args = parser.parse_args()

    ensure_adb()
    os.makedirs(args.output, exist_ok=True)

    uid = get_uid(args.package)
    total_mem_kb = get_total_mem_kb()
    run_adb("dumpsys batterystats --reset")

    monkey_cmd = [
        "adb",
        "shell",
        "monkey",
        "-p",
        args.package,
        "--throttle",
        "200",
        "-v",
        "999999",
    ]
    monkey_process = subprocess.Popen(
        monkey_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    samples: list[Sample] = []
    start = time.time()
    while True:
        elapsed = time.time() - start
        if elapsed >= args.duration:
            break
        cpu_percent = get_cpu_percent(args.package)
        mem_pss_kb, gc_count = get_mem_gc(args.package)
        mem_percent = None
        if total_mem_kb and mem_pss_kb is not None:
            mem_percent = mem_pss_kb / total_mem_kb * 100
        net_rx_bytes, net_tx_bytes = get_net_bytes(uid)
        cpu_display = f"{cpu_percent:.2f}%" if cpu_percent is not None else "N/A"
        mem_display = f"{mem_percent:.2f}%" if mem_percent is not None else "N/A"
        print(f"Elapsed {elapsed:.1f}s | CPU {cpu_display} | Memory {mem_display}")
        samples.append(
            Sample(
                timestamp_s=elapsed,
                cpu_percent=cpu_percent,
                mem_pss_kb=mem_pss_kb,
                mem_percent=mem_percent,
                gc_count=gc_count,
                net_rx_bytes=net_rx_bytes,
                net_tx_bytes=net_tx_bytes,
            )
        )
        time.sleep(args.interval)

    monkey_process.terminate()
    run_adb("pkill -f monkey")

    power_mah = get_power_mah(args.package)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(args.output, f"samples_{timestamp}.csv")
    write_csv(samples, csv_path)
    plot_path = plot_series(samples, power_mah, args.output)

    print("Monitoring complete.")
    print(f"CSV saved to: {csv_path}")
    print(f"Charts saved to: {plot_path}")
    if power_mah is not None:
        print(f"Total power usage (mAh): {power_mah}")
    else:
        print("Power usage data unavailable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
