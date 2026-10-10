#!/usr/bin/env python3
"""Select one local incident and launch its Bash script."""
import argparse
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
INCIDENTS = {
    1: ('Server or container crash', 'server-crash.sh'),
    2: ('Slow or lossy network responses', 'network.sh'),
    3: ('Full Disk (ENOSPC write errors)', 'full-disk.sh'),
    4: ('Overloaded Database (Redis)', 'database-overload.sh'),
    5: ('Failed Dependency (shipping)', 'failed-dependency.sh'),
    6: ('Sudden Traffic Spike', 'traffic-spike.sh'),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--choice', type=int, choices=INCIDENTS)
    parser.add_argument('--network-mode', choices=('delay', 'loss'))
    parser.add_argument('--users', type=int, default=20, help='network incident shoppers (1–200)')
    parser.add_argument('--rate', type=int, default=2, help='network shopper spawn rate (1–100 per second)')
    parser.add_argument('--list', action='store_true', help='show incidents without running one')
    args = parser.parse_args()
    for number, (label, _) in INCIDENTS.items():
        print(f'{number}) {label}')
    if args.list:
        return 0
    if not 1 <= args.users <= 200 or not 1 <= args.rate <= 100:
        parser.error('--users must be 1–200 and --rate must be 1–100')
    choice = args.choice
    while choice is None:
        answer = input('Choose 1–6, or q to exit: ').strip()
        if answer.lower() == 'q':
            return 0
        if answer.isdigit() and int(answer) in INCIDENTS:
            choice = int(answer)
        else:
            print('Enter a number from 1 to 6.')
    mode = args.network_mode
    if choice == 2 and mode is None:
        while mode not in ('delay', 'loss'):
            mode = input('Network mode: delay or loss [delay]: ').strip().lower() or 'delay'
    label, script = INCIDENTS[choice]
    if choice != 2 and (args.users != 20 or args.rate != 2):
        parser.error('--users and --rate currently apply to network incidents (choice 2)')
    command = ['bash', str(ROOT / 'scripts' / 'incidents' / script)]
    if choice == 2:
        command.extend([mode, '--users', str(args.users), '--rate', str(args.rate)])
    print(f'Running: {label}. Keep Grafana open. Ctrl-C requests cleanup.', flush=True)
    process = subprocess.Popen(command, cwd=ROOT)
    try:
        return process.wait()
    except KeyboardInterrupt:
        # Ctrl-C reaches the foreground child too; let its cleanup finish.
        print('\nWaiting for incident cleanup...', flush=True)
        return process.wait()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        raise SystemExit(130)
