from pathlib import Path

import os
import logging, logging.handlers
import sys, json

from .config import AppConfig
from .database import Database
from .smart import Smart
from .system import System
from .notifications import Notifier

class DiskWatcherApp:
    def __init__(self, config: AppConfig):
        self.config = config

        self._check_binaries()
        self._setup_dirs()
        self._setup_logging()

        self.db = Database(self.config.file_database)
        self.sys = System(self.config.bin.lsblk)
        self.smart = Smart(self.config.bin.smartctl)
        self.notify = Notifier()

    def run_data_fetch(self):
        boot_date = self.sys.get_boot_date()

        for disk in self.sys.get_disk_devices():
            smart_data = None
            try:
                smart_data = Smart().process_smart(disk['KNAME'])
            except Exception as e:
                self.logger.info(f'{disk["KNAME"]} failed to process SMART: {e}')

            if not smart_data or 'power_cycle' not in smart_data:
                continue

            data = \
            {
                'dev': f"/dev/{disk['KNAME']}",
                'serial': disk['SERIAL'],
                'transport': disk['TRAN'],
                'model': disk['MODEL'],
                'dt_boot': boot_date,
                'smart_json': json.dumps(smart_data)
            }

            # lof into the app's file
            with open(self.config.file_log, 'a') as f:
                f.write(','.join([str(value) for value in data.values()]) + "\n")

            # also send to syslog
            msg = f"Disk found: {data['dev']} {data['serial']} ({data['transport']}/{data['model']}) {data['smart_json']}"
            self.logger.info(msg)

            # and store in the db
            data = {**data, **smart_data}
            self.db.store_event(data)

        sys.exit(0)

    def check_continuity(self):
        for disk in self.sys.get_disk_devices():
            dev = disk['KNAME']
            serial = disk['SERIAL']

            evs = self.db.get_last_events(serial)

            if len(evs) < 2:
                self.logger.info(f'/dev/{dev} {serial} has less than two events recorded, skipping!')
                continue

            prev   = json.loads(evs[1]['smart_json'])['power_cycle']
            actual = json.loads(evs[0]['smart_json'])['power_cycle']

            msg_base = f'/dev/{dev} {serial} \nSMART PowerCycleCount: prev={prev} now={actual}'

            if prev == actual or prev == actual-1:
                msg = f'OK {msg_base}'
                self.logger.info(msg.replace('\n','-'))
                if self.config.always_notify:
                    self.notify.send(self.config.app_name, msg, 'normal')
                continue

            if prev != actual-1:
                msg = f'Device tampering! {msg_base}'
                self.logger.critical(msg.replace('\n','-'))
                self.notify.send(self.config.app_name, msg, 'critical')

        sys.exit(0)

    def print_disk_devices(self):
        print('Disks recognized:\n')
        for disk in self.sys.get_disk_devices():
            for key in disk.keys():
                print(f"{key}: {disk[key]}")

            print('')

    def _throw_error(self, msg, priority = logging.ERROR, dieCode = 1):
        self.logger.log(priority, msg)
        print(msg)
        sys.exit(dieCode)


    def _check_binaries(self):
        for name, binary in vars(self.config.bin).items():
            if not os.path.exists(binary):
                raise RuntimeError(f'{name} not found under {binary}')

    def _setup_dirs(self):
        self.config.dir_data.mkdir(mode=0o755, parents=True, exist_ok=True)

    def _setup_logging(self):
        self.logger = logging.getLogger(self.config.app_name)
        self.logger.setLevel(logging.INFO)

        syslog_handler = logging.handlers.SysLogHandler(address='/dev/log')

        formatter = logging.Formatter('%(name)s %(message)s')
        syslog_handler.setFormatter(formatter)
        self.logger.addHandler(syslog_handler)

