import json, sys, os, re
import subprocess
from datetime import datetime
from .dbevent import dbEvent
from .smart import Smart
import psutil
import dbus

import logging
import logging.handlers

"""TODO
+refact, if time permits
"""

class DiskWatcher:
    service = 'diskwatcher'
    fileTarget = ''
    db:dbEvent = None
    logger = None

    DEFAULT_OPTIONS = {
        'dir_data': '/var/lib/diskwatcher/',
        'binaries':
        {
            'smartctl': '/usr/sbin/smartctl',
            'lsblk': '/usr/bin/lsblk'
        },
        'always_notify': 0
    }

    def __init__(self, options=None):
        self.options = self.DEFAULT_OPTIONS.copy()
        if options is not None:
            self.options.update(options)

        self.systemInit()

    def systemInit(self):
        dirTarget = self.options['dir_data']

        for name, binary in self.options['binaries'].items():
            if not os.path.exists(binary):
                self.throwError(f'{name} not found under {binary}')

        if not os.path.exists(dirTarget):
            os.makedirs(dirTarget, 0o755, True)

        if not dirTarget.endswith('/'):
            dirTarget += '/'

        self.fileTarget = dirTarget + 'diskinfo'
        self.db = dbEvent(dirTarget + 'dbc.db')
        self.loginit()

        return self

    def loginit(self):
        self.logger = logging.getLogger(self.service)
        self.logger.setLevel(logging.INFO)

        syslog_handler = logging.handlers.SysLogHandler(address='/dev/log')

        formatter = logging.Formatter('%(name)s %(message)s')
        syslog_handler.setFormatter(formatter)
        self.logger.addHandler(syslog_handler)

    def runDataFetch(self):
        bootDate = self.getBootDate()

        for disk in self.getDiskDevices():
            try:
                smartData = Smart(disk['KNAME']).processSMART()
            except Exception as e:
                self.throwError(f'{disk["KNAME"]} failed to process SMART: {e}')

            if not smartData or 'power_cycle' not in smartData:
                continue

            data = {}
            data['dev'] = f"/dev/{disk['KNAME']}"
            data['serial'] = disk['SERIAL']
            data['transport'] = disk['TRAN']
            data['model'] = disk['MODEL']
            data['dt_boot'] = bootDate
            data['smart_json'] = json.dumps(smartData)

            with open(self.fileTarget, 'a') as f:
                f.write(','.join([str(value) for value in data.values()]) + "\n")

            msg = f"Disk found: {data['dev']} {data['serial']} ({data['transport']}/{data['model']}) {data['smart_json']}"
            self.logger.info(msg)

            data = {**data, **smartData}
            self.db.storeEvent(data)

        sys.exit(0)

    @staticmethod
    def getBootDate():
        #NOTE: can be replaced with /proc/stat - get line with ^btime (ex: btime 1720196915)
        return str(datetime.fromtimestamp(psutil.boot_time()))

    def getDiskDevices(self)->list:
        columns = ['KNAME','SERIAL','TRAN','MODEL','ROTA']

        result = subprocess.run(f"{self.options['binaries']['lsblk']} -Arndio " + ",".join(columns), shell=True, stdout=subprocess.PIPE)
        result = result.stdout.decode(sys.getdefaultencoding())

        out = []
        disks = re.split('\n', result)

        for disk in disks:
            if not disk: continue
            values = re.split('\s+', disk)
            kv = dict(zip(columns, values))
            kv['MODEL'] = bytes(kv['MODEL'], 'utf-8').decode('unicode_escape')

            out.append( kv )

        """
        sda XXX0NF0JB1XXXXVV sata Samsung\x20SSD\x20750\x20EVO\x20250GB 0
        nvme0n1 XXXXNX0WXXXXXXL nvme Samsung\x20SSD\x20990\x20PRO\x201TB 0
        =>
        #0 dict(5) 
            ['KNAME'] => str(3) "sda"
            ['SERIAL'] => str(15) "S3R0NF0JB17727V"
            ['TRAN'] => str(4) "sata"
            ['MODEL'] => str(25) "Samsung SSD 850 EVO 250GB"
            ['ROTA'] => str(1) "0"
        """

        return out

    def printDiskDevices(self):
        print('Disks recognized:\n')
        for disk in self.getDiskDevices():
            for key in disk.keys():
                print(f"{key}: {disk[key]}")

            print('')

    def throwError(self, msg, priority = logging.ERROR, dieCode = 1):
        self.logger.log(priority, msg)
        print(msg)
        sys.exit(dieCode)

    def sendNotify(self, msg, errorLevel='critical', timeout=10000):
        #https://specifications.freedesktop.org/notification-spec/notification-spec-latest.html#urgency-levels
        #urgency = 0=low, 1=normal, 2=critical
        err = {
            "low":
            {
                'urgency': 0,
                'app_icon': 'drive-harddisk'
            },
            "normal":
            {
                'urgency': 1,
                'app_icon': 'drive-harddisk'
            },
            "critical":
            {
                'urgency': 2,
                'app_icon': 'error'
            },
        }

        item = "org.freedesktop.Notifications"
        itemPath = "/" + item.replace(".", "/")

        #https://pychao.com/2021/03/01/sending-desktop-notification-in-linux-with-python-with-d-bus-directly/
        org_freedesktop_Notifications = dbus.Interface( dbus.SessionBus().get_object(item, itemPath), item)

        #https://web.archive.org/web/20200606201408/https://developer.gnome.org/notification-spec/

        title = self.service
        errdata = err[errorLevel]

        """
        Notify(app_name, replaces_id, app_icon, summary, body, actions, hints, expire_timeout)

        """
        org_freedesktop_Notifications.Notify( self.service, 0, errdata['app_icon'], title, msg, [], {"urgency": errdata['urgency']}, timeout)

    def checkContinuity(self):
        for disk in self.getDiskDevices():
            dev = disk['KNAME']
            serial = disk['SERIAL']

            evs = self.db.getLastEvents(serial)

            if len(evs) < 2:
                self.logger.info(f'/dev/{dev} {serial} has less than two events recorded, skipping!')
                continue

            prev   = json.loads(evs[1]['smart_json'])['power_cycle']
            actual = json.loads(evs[0]['smart_json'])['power_cycle']

            msg_base = f'/dev/{dev} {serial} \nSMART PowerCycleCount: prev={prev} now={actual}'

            if prev == actual or prev == actual-1:
                msg = f'OK {msg_base}'
                self.logger.info(msg.replace('\n','-'))
                if self.options['always_notify']:
                    self.sendNotify(msg, 'normal')
                continue

            if prev != actual-1:
                msg = f'Device tampering! {msg_base}'
                self.logger.critical(msg.replace('\n','-'))
                self.sendNotify(msg, 'critical')

        sys.exit(0)
