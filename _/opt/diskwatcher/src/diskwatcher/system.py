import subprocess, re, sys, psutil
from datetime import datetime


class System:

    def __init__(self, lsblk_path: str = '/usr/sbin/lsblk'):
        self.lsblk_path = lsblk_path

    @staticmethod
    def get_boot_date():
        #NOTE: can be replaced with /proc/stat - get line with ^btime (ex: btime 1720196915)
        return str(datetime.fromtimestamp(psutil.boot_time()))

    def get_disk_devices(self)->list:
        columns = ['KNAME','SERIAL','TRAN','MODEL','ROTA']

        result = subprocess.run(f"{self.lsblk_path} -Arndio " + ",".join(columns),
                                shell=True,
                                stdout=subprocess.PIPE)
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
            ['SERIAL'] => str(15) "P3XXXF0JB1XXXXV"
            ['TRAN'] => str(4) "sata"
            ['MODEL'] => str(25) "Samsung SSD 850 EVO 250GB"
            ['ROTA'] => str(1) "0"
        """

        return out
