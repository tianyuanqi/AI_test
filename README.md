# Android App Performance Monitor

This script uses `adb` to monitor an Android app's CPU, memory usage (% of total), GC count, power usage, and network usage while running Monkey for 30 seconds.

## Requirements

- Android device connected via USB with USB debugging enabled
- `adb` available in PATH
- Python 3.10+
- `matplotlib` installed

## Usage

```bash
python3 monitor_app.py --duration 30 --interval 1 --output output
```

You can also run the compatibility wrapper (for `ai_test.py`) or use `--out-dir` as an alias:

```bash
python3 ai_test.py --duration 30 --interval 1 --out-dir output
```

The script will:

1. Reset battery stats.
2. Start Monkey on the target package.
3. Sample CPU, memory usage, GC count, and network bytes every interval.
4. Stop Monkey after the duration.
5. Generate a CSV and charts.

Outputs are written to the `output/` directory:

- `samples_<timestamp>.csv`
- `performance_charts.png`

## Notes

- Some devices/Android versions may not expose GC or network stats; those fields will be blank in the output.
- CPU sampling falls back to `dumpsys cpuinfo` if `top` doesn't return process data.
- Power usage is collected after the run from `dumpsys batterystats` and displayed as a total.
