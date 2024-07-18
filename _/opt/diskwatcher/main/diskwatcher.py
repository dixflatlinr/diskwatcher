import json, sys, os, re
import subprocess
from datetime import datetime
from .dbevent import dbEvent
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
            smartData = self.getSMART(disk['KNAME'])
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

    def is_bit_set(self, byte, bit_position:int):
        """
        # Example usage:
        # bitpos:   76543210
        byte =    0b10001001
        bit_position = 7

        is_set = is_bit_set(byte, bit_position)
        print(f"Is bit {bit_position} set in byte {bin(byte)}? {'Yes' if is_set else 'No'}")
        """
        if bit_position < 0 or bit_position > 7:
            raise ValueError("Bit position must be in the range 0-7")
        mask = 1 << bit_position

        return (byte & mask) != 0

    def getSMART(self, dev):
        if not re.match('^[a-z0-9-_]+$',dev):
            self.throwError(f'Device name {dev} contains strange characters!')

        # note: sleepy drive statuses not checked... -n
        result = subprocess.run(f"{self.options['binaries']['smartctl']} -a -j /dev/{dev}", shell=True, stdout=subprocess.PIPE)
        smart = json.loads(result.stdout)

        out = self.processSMART(smart)
        out['status'] = self.smartCtlExitCodeParser(result.returncode)

        #TODO: remove debug
        with open(f'{self.options["dir_data"]}debug_smart.txt', 'a') as file:
            file.write(f"###################{dev}:")
            json.dump(out, file)
            file.write(result.stdout.decode("utf-8"))
            file.write("\n")

        #Enddebug

        return out

    def smartCtlExitCodeParser(self, exitcode:int):
        errstr = \
            {
                0: 'smartctl parameter error',
                1: 'device cannot be opened',
                2: 'smart/ata cmd fail or checksum error',
                3: 'disk failing',
                4: 'prefail attributes below threshold',
                5: 'usage/prefail attributes were below threshold in the past',
                6: 'error log not empty',
                7: 'self test log has errors',
            }
        # smartctl uses a bitmask in the return code to communicate if any errors occured with the device
        if exitcode & 0xFF == 0:
            return 'OK'

        out = []

        if exitcode & 0xFF != 0:
            for bit in range(0,7+1):
                if self.is_bit_set(exitcode, bit):
                    out.append(errstr[bit])

        return ", ".join(out)

    def processSMART(self, data)->dict:
        out = {}
        logical_sector_size = 512 #TODO: need to parse value from smartctl output if it varies

    ### NVME
        nvme_key = 'nvme_smart_health_information_log'
        nvme_keys = ['host_reads','host_writes','power_cycles','power_on_hours']

        if nvme_key in data:
            out['host_read_bytes'] = (data[nvme_key]['host_reads'] * logical_sector_size)
            out['host_write_bytes'] = (data[nvme_key]['host_writes'] * logical_sector_size)
            out['power_cycle'] = data[nvme_key]['power_cycles']
            out['power_on_hours'] = data[nvme_key]['power_on_hours']

            return out

    ### SATA
        if "ata_smart_attributes" not in data:
            return {}

        table = data["ata_smart_attributes"]["table"]

        sata = {}
        for item in table:
            name = item.pop("name")
            sata[name] = item

        out['host_read_bytes'] = 0
        out['host_write_bytes'] = (sata["Total_LBAs_Written"]['raw']['value'] * logical_sector_size) # / (1000**4)
        out['power_cycle'] = sata["Power_Cycle_Count"]['raw']['value']
        out['power_on_hours'] = sata["Power_On_Hours"]['raw']['value']

        return out

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
