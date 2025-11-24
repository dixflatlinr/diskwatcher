import argparse
import sys,os
from .config import AppConfig
from .core import DiskWatcherApp

def main():
    parser = argparse.ArgumentParser(description="Diskwatcher")
    subparser = parser.add_subparsers(dest='command', help="Commands")

    # Fetch command (root)
    parser_fetch = subparser.add_parser("fetch", help="Fetch SMART data (root only)")

    # Watch command
    parser_watch = subparser.add_parser("watch", help="Check continuity and notify")
    parser_watch.add_argument('--list', action='store_true', default=False, help='List detected disk drives')
    parser_watch.add_argument('--always_notify', type=int, default=0, help='Always show notifications (1=Yes, 0=Only when needed)')

    # TODO: FUT: these also need more privs!
    #parser.add_argument("--ignore", help="Specify disk serial number to ignore", type=str, default="")
    #parser.add_argument("--remove", help="Remove serial from ignore list", type=str, default="")

    args = parser.parse_args()

    # when run as a systemd service, the /etc/default/diskwatcher file is read and its options are fed as env values
    notify_env = os.environ.get('ALWAYS_NOTIFY')
    notify_status = args.command == 'watch' and args.always_notify or notify_env == '1'

    config = AppConfig(always_notify=notify_status)
    app = DiskWatcherApp(config)

    if args.command == 'fetch':
        # NOTE: or check capabilities (if run with run0) -> prctl.cap_effective
        if os.geteuid() == 0:
            app.run_data_fetch()
            exit(0)

        print(f'Error: {config.app_name} {args.command} must be run as root!')
        sys.exit(1)

    elif args.command == 'watch':
        if args.list:
            app.print_disk_devices()
            exit(0)

        app.check_continuity()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
