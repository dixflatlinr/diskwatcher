from pathlib import Path
from types import SimpleNamespace

class AppConfig:
    """Configuration settings"""
    def __init__(self, dir_data: str = '/var/lib/diskwatcher', always_notify: bool = True):
        self.app_name = 'diskwatcher'

        self.dir_data = Path(dir_data)
        self.always_notify = always_notify

        self.file_database = self.dir_data / 'dbc.db'
        self.file_log = self.dir_data / 'diskinfo'

        self.bin = SimpleNamespace(
            lsblk = '/usr/bin/lsblk',
            smartctl = '/usr/sbin/smartctl'
        )

