import os, re, subprocess, json

class Smart:
    """Handles fetching and parsing SMART data via smartctl"""

    device_name = ''
    data:dict = None

    DEFAULT_OPTIONS = {
        'binaries':
        {
            'smartctl': '/usr/sbin/smartctl',
        }
    }

    def __init__(self, binary_path: str = '/usr/sbin/smartctl'):
        self.options = self.DEFAULT_OPTIONS.copy()

        for name, binary in self.options['binaries'].items():
            if not os.path.exists(binary):
                raise FileNotFoundError(f'{name} not found under {binary}')

        pass

    def process_smart(self, device_name:str) -> dict:
        out = {}

        data = self._get_smart(device_name)

        if not data.get('device'):
            raise RuntimeError('No device data present!')

        # device agnostic values by smartctl
        out['power_on_hours'] = data['power_on_time']['hours']
        out['power_cycle'] = data['power_cycle_count']
        #out['logical_block_size'] = data['logical_block_size']
        logical_block_size = data['logical_block_size']

        # populate bytes read and written values
        match data['device']['type']:
            case 'nvme':
                self._process_nvme(data, out, logical_block_size)

            case 'ata' | 'sat' | 'sata':
                self._process_ata(data, out, logical_block_size)

            case _:
                raise RuntimeError(f'Device {device_name} is not supported!')

        return out

    # specs: https://nvmexpress.org/specifications/
    # NVM-Express-Base-Specification-Revision-2.1-2024.08.05-Ratified.pdf
    #
    def _process_nvme(self, data: dict, out:dict, block_size:int):
        nvme_key = 'nvme_smart_health_information_log'

        """
        Contains the number of 512 byte data units the host has read from the
        controller as part of processing a SMART Data Units Read Command; this value does not include
        metadata. This value is reported in thousands (i.e., a value of 1 corresponds to 1,000 units of 512 bytes
        read)...
        """
        out['host_read_bytes'] = (data[nvme_key]['data_units_read'] * block_size * 1000)
        out['host_write_bytes'] = (data[nvme_key]['data_units_written'] * block_size * 1000)

    def _process_ata(self, data: dict, out:dict, block_size:int):
        table = data["ata_smart_attributes"]["table"]

        sata = {}
        for item in table:
            sata[item.pop("name")] = item

        ret = self._calculate_reads_writes(sata, block_size)

        out['host_read_bytes'] = ret['read']
        out['host_write_bytes'] = ret['write']

    def _get_smart(self, device_name:str) -> dict:
        """Fetches JSON from smartctl output"""

        #self.data = self.get_smart(device_name)

        if not re.match('^[a-z0-9-_]+$', device_name):
            raise RuntimeError(f'Device name {device_name} contains strange characters!')

        # TODO: res why this outputs extra data?!
        #cmd = [self.options['binaries']['smartctl'], '-a','-j',f'/dev/{device_name}']

        # -a all info, -j json output
        cmd = f"{self.options['binaries']['smartctl']} -a -j /dev/{device_name}"

        # note: sleepy drive statuses not checked... -n
        # smartctl has funny exit codes that reflect disk statuses, hence no check=True
        result = subprocess.run(cmd,
                                shell=True,
                                stdout=subprocess.PIPE)

        smart = json.loads(result.stdout)
        smart['__exitcode'] = self._parse_exit_code(result.returncode)

        return smart


    def _calculate_reads_writes(self, raw_data, block_size:int = 512) -> dict:
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

    def _parse_exit_code(self, exitcode: int):
        """Parses smartctl exit codes"""
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
                if self._is_bit_set(exitcode, bit):
                    out.append(errstr[bit])

        return ", ".join(out)

    def _is_bit_set(self, byte, bit_position:int):
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

