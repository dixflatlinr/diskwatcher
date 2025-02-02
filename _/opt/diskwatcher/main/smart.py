import os, re, subprocess, json

class Smart:
    device_name = ''
    data:dict = None

    DEFAULT_OPTIONS = {
        'binaries':
        {
            'smartctl': '/usr/sbin/smartctl',
        }
    }

    def __init__(self, device_name):
        self.options = self.DEFAULT_OPTIONS.copy()
        self.device_name = device_name

        for name, binary in self.options['binaries'].items():
            if not os.path.exists(binary):
                raise Exception(f'{name} not found under {binary}')

        self.data = self.getSMART(device_name)

        pass

    def getSMART(self, device_name:str) -> dict:
        if not re.match('^[a-z0-9-_]+$', device_name):
            raise Exception(f'Device name {device_name} contains strange characters!')

        # note: sleepy drive statuses not checked... -n
        result = subprocess.run(f"{self.options['binaries']['smartctl']} -a -j /dev/{device_name}", shell=True,
                                stdout=subprocess.PIPE)
        smart = json.loads(result.stdout)
        smart['__exitcode'] = self.parseSmartCtlExitCode(result.returncode)

        return smart

    def processSMART(self) -> dict:
        out = {}

        if not self.data.get('device'):
            raise Exception('No device data present!')

        # device agnostic values by smartctl
        out['power_on_hours'] = self.data['power_on_time']['hours']
        out['power_cycle'] = self.data['power_cycle_count']
        #out['logical_block_size'] = self.data['logical_block_size']
        logical_block_size = self.data['logical_block_size']

        # specs: https://nvmexpress.org/specifications/
        # NVM-Express-Base-Specification-Revision-2.1-2024.08.05-Ratified.pdf
        #
        match self.data['device']['type']:
            case 'nvme':
                nvme_key = 'nvme_smart_health_information_log'

                """
                Contains the number of 512 byte data units the host has read from the
                controller as part of processing a SMART Data Units Read Command; this value does not include
                metadata. This value is reported in thousands (i.e., a value of 1 corresponds to 1,000 units of 512 bytes
                read)...
                """
                out['host_read_bytes'] = (self.data[nvme_key]['data_units_read'] * logical_block_size * 1000)
                out['host_write_bytes'] = (self.data[nvme_key]['data_units_written'] * logical_block_size * 1000)

            case 'ata' | 'sat' | 'sata':
                table = self.data["ata_smart_attributes"]["table"]

                sata = {}
                for item in table:
                    sata[item.pop("name")] = item

                ret = self.calculateReadsWrites(sata, logical_block_size)

                out['host_read_bytes'] = ret['read']
                out['host_write_bytes'] = ret['write']

            case _:
                raise Exception(f'Device {self.device_name} is not supported!')

        return out

    def calculateReadsWrites(self, raw_data, block_size:int = 512) -> dict:
        """
        Returns the read/written bytes

        :param raw_data: The raw ata_smart_attributes data
        :param block_size: The LBA block size
        :return:
        """

        out = {'read': 0, 'write': 0}
        lba_to_bytes = lambda val, bs : val * block_size
        _gib = lambda val, _: val * (1024 ** 3)
        _mib = lambda val, _: val * (1024 ** 2)
        _32mib = lambda val, _: val * ((1024 ** 2) * 32)
        _asis = lambda val, _: val

        transform_read = \
        {
            'Total_LBAs_Read': lba_to_bytes,
            'Host_Reads': lba_to_bytes,
            'Host_Reades_GiB': _gib,
            'Host_Reads_MiB': _mib,
            'Lifetime_Reads_GiB': _gib,
            'Host_Reads_32MiB': _32mib,
            'Host_Reads_GiB': _gib,
            'Total_Reads_GiB': _gib,
            'Total_Reads_GB': _gib,
            'Flash_Reads_LBAs': lba_to_bytes,
            'Device_Bytes_Read': _asis,
        }

        for key in raw_data:
            if key in transform_read:
                func = transform_read[key]
                out['read'] = func(raw_data[key]['raw']['value'], block_size)
                break

        transform_write =  \
        {
            'Total_LBAs_Written': lba_to_bytes,
            'Host_Writes_GiB': _gib,
            'Host_Writes_MiB': _mib,
            'Lifetime_Writes_GiB': _gib,
            'Host_Writes_32MiB': _32mib,
            'Flash_Writes_GiB': _gib,
            'Total_Writes_GiB': _gib,
            'Total_Writes_GB': _gib,
            'Flash_Writes_LBAs': lba_to_bytes,
        }

        for key in raw_data:
            if key in transform_write:
                func = transform_write[key]
                out['write'] = func(raw_data[key]['raw']['value'], block_size)
                break

        return out

    def parseSmartCtlExitCode(self, exitcode: int):
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
            for bit in range(0, 7 + 1):
                if self.is_bit_set(exitcode, bit):
                    out.append(errstr[bit])

        return ", ".join(out)

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

