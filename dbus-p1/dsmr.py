
import asyncio
from ctypes import c_ushort
from enum import Enum, unique
import re
import serial
from serial import SerialException

@unique
class OBIS_ID(Enum):
    """ Object Identification System constants """
    P1_MESSAGE_TIMESTAMP = r'\d-\d:1\.0\.0.+?\r\n'
    EQUIPMENT_IDENTIFIER = r'\d-\d:96\.1\.1.+?\r\n'
    ELECTRICITY_USAGE = r'\d-\d:1\.7\.0.+?\r\n'
    ELECTRICITY_DELIVERY = r'\d-\d:2\.7\.0.+?\r\n'
    ELECTRICITY_USED_TARIFF_1 = r'\d-\d:1\.8\.1.+?\r\n'
    ELECTRICITY_USED_TARIFF_2 = r'\d-\d:1\.8\.2.+?\r\n'
    ELECTRICITY_DELIVERED_TARIFF_1 = r'\d-\d:2\.8\.1.+?\r\n'
    ELECTRICITY_DELIVERED_TARIFF_2 = r'\d-\d:2\.8\.2.+?\r\n'
    VOLTAGE_L1 = r'\d-\d:32\.7\.0.+?\r\n'
    VOLTAGE_L2 = r'\d-\d:52\.7\.0.+?\r\n'
    VOLTAGE_L3 = r'\d-\d:72\.7\.0.+?\r\n'
    CURRENT_L1 = r'\d-\d:31\.7\.0.+?\r\n'
    CURRENT_L2 = r'\d-\d:51\.7\.0.+?\r\n'
    CURRENT_L3 = r'\d-\d:71\.7\.0.+?\r\n'
    ACTIVE_POWER_L1_POSITIVE = r'\d-\d:21\.7\.0.+?\r\n'
    ACTIVE_POWER_L2_POSITIVE = r'\d-\d:41\.7\.0.+?\r\n'
    ACTIVE_POWER_L3_POSITIVE = r'\d-\d:61\.7\.0.+?\r\n'
    ACTIVE_POWER_L1_NEGATIVE = r'\d-\d:22\.7\.0.+?\r\n'
    ACTIVE_POWER_L2_NEGATIVE = r'\d-\d:42\.7\.0.+?\r\n'
    ACTIVE_POWER_L3_NEGATIVE = r'\d-\d:62\.7\.0.+?\r\n'


class CosemValue:
    def __init__(self, name, line):
        self.name = name
        data = line.split('(', 1)[1].rstrip(')')
        try:
            value, self.unit = data.split('*')
            self.value = float(value)
        except ValueError:
            self.value = data
            self.unit = None

    def __str__(self):
        unit = ''
        if self.unit:
            unit = ' ' + self.unit
        return f"{self.name}: {self.value}{unit}"


class Telegram:
    def __init__(self, raw):
        self.header, data = raw.split('\r\n', 1)
        self.data = data.lstrip('\r\n')

    def __getitem__(self, id):
        assert isinstance(id, OBIS_ID)
        pattern = id.value
        match = re.search(pattern, self.data)
        if match is None:
            return None # Object id not found
        line = match.group(0).strip()
        return CosemValue(id, line)


class TelegramParser:
    crc16_table = []

    def __init__(self):
        if not TelegramParser.crc16_table:
            for i in range(0, 256):
                crc = c_ushort(i).value
                for j in range(0, 8):
                    if (crc & 0x0001):
                        crc = c_ushort(crc >> 1).value ^ 0xA001
                    else:
                        crc = c_ushort(crc >> 1).value
                TelegramParser.crc16_table.append(hex(crc))

    def parse(self, telegram):
        split = telegram.index('!') + 1
        data = telegram[:split]
        crc = telegram[split:].rstrip()
        if crc:
            calculated_crc = TelegramParser.crc16(data)
            expected_crc = int(crc, base=16)
            if calculated_crc != expected_crc:
                print(f"Recieved telegram with crc error")
                return None
        return Telegram(data)

    @staticmethod
    def crc16(telegram):
        """
        Calculate the CRC16 value for the given telegram

        :param str telegram:
        """
        crc = 0x0000

        for c in telegram:
            d = ord(c)
            tmp = crc ^ d
            rotated = c_ushort(crc >> 8).value
            crc = rotated ^ int(TelegramParser.crc16_table[(tmp & 0x00ff)], 0)

        return crc


class SerialReader:
    def __init__(self, port, baud=115200, bytesize=7, parity="none"):
        self.port = port
        self.baud = baud
        try:
            self.parity = getattr(serial, f'PARITY_{parity.upper()}')
        except AttributeError:
            raise AttributeError("Invalid parity argument") from None
        try:
            self.bytesize = (serial.SEVENBITS, serial.EIGHTBITS)[bytesize - 7]
        except IndexError:
            raise AttributeError("Invalid bytesize argument: Should be 7 or 8")
        self.parser = TelegramParser()

    def _read_telegram(self, only_last=True):
        telegram = None
        with serial.Serial(self.port, self.baud, self.bytesize, self.parity, timeout=3) as ser:
            while True:
                line = ser.read_until(b'\n')
                if line == b'':
                    raise TimeoutError(f"Timeout on reading from {self.port}")
                if telegram is None:
                    if line.startswith(b'/'):   # First line
                        telegram = line
                else:
                    telegram += line
                    if line.startswith(b'!'):   # Last line
                        if only_last and ser.in_waiting:
                            # There is a newer telegram in the input buffer.
                            # Discard this one and get the new one.
                            telegram = None
                        else:
                            break
        return telegram.decode('ascii')

    def read(self):
        telegram = self._read_telegram()
        return self.parser.parse(telegram)
    
    async def async_read(self, loop=None):
        loop = loop or asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.read)
