import asyncio
import errno
import os.path

from dbus_next.constants import BusType
from dbus_next.aio import MessageBus
from aiovelib.service import Service, IntegerItem, DoubleItem, TextItem

from .dsmr import SerialReader, OBIS_ID, SerialException

# String formatters for dbus Item based intances
unit_kwh = lambda v: "{:.2f}kWh".format(v)
unit_watt = lambda v: "{:.0f}W".format(v)
unit_volt = lambda v: "{:.1f}V".format(v)
unit_amp = lambda v: "{:.1f}A".format(v)


class P1DbusBridge:
    def __init__(self, port):
        self.port = port
        self.p1 = SerialReader(port)
        self.service = None

    async def wait_for_p1_port(self):
        if os.path.exists(self.port):
            return
        print(f"Waiting for {self.port} to become available...")
        while not os.path.exists(self.port):
            await asyncio.sleep(1)

    async def wait_for_valid_telegram(self):
        telegram = None
        while telegram is None:
            await self.wait_for_p1_port()
            try:
                telegram = await self.p1.async_read()
            except SerialException as exc:
                if exc.errno == errno.ENOENT:
                    print("P1 port is unavailable")
                    await asyncio.sleep(5)  # Debounce
            except TimeoutError as exc:
                print("Timeout on read from P1 port")
        return telegram

    async def register_dbus(self, name, telegram):
        # Setup the dbus service for the session bus
        await self.unregister_dbus()
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        service = Service(bus, 'com.victronenergy.grid.' + name)

        # Create the generic dbus service objects
        service.add_item(TextItem('/ProductName', 'Smart Meter P1 Reader'))
        service.add_item(TextItem('/Mgmt/ProcessName', 'p1-gridmeter'))
        service.add_item(TextItem('/Mgmt/ProcessVersion', 'Unknown version'))
        service.add_item(TextItem('/Mgmt/Connection', 'Serial P1 grid meter service'))
        service.add_item(IntegerItem('/Connected', 1))
        service.add_item(IntegerItem('/DeviceInstance', 10))
        service.add_item(IntegerItem('/ProductId', 45069))  # Carlo Gavazzi ET 340 Energy Meter
        service.add_item(IntegerItem('/DeviceType', 345))   # ET340 Energy Meter
        service.add_item(DoubleItem('/FirmwareVersion', 0.1))
        service.add_item(IntegerItem('/HardwareVersion', 0))
        service.add_item(TextItem('/Role', 'grid'))
        service.add_item(TextItem('/Serial', telegram[OBIS_ID.EQUIPMENT_IDENTIFIER].value))
        service.add_item(IntegerItem('/ErrorCode', 0, writeable=True))

        # Create grid meter dbus objects
        service.add_item(DoubleItem('/Ac/Energy/Forward', None, writeable=True, text=unit_kwh))
        service.add_item(DoubleItem('/Ac/Energy/Reverse', None, writeable=True, text=unit_kwh))
        service.add_item(DoubleItem('/Ac/Power', None, writeable=True, text=unit_watt))
        for prefix in (f"/Ac/L{x}" for x in range(1, 4)):
            service.add_item(DoubleItem(prefix + '/Voltage', None, writeable=True, text=unit_volt))
            service.add_item(DoubleItem(prefix + '/Current', None, writeable=True, text=unit_amp))
            service.add_item(DoubleItem(prefix + '/Power', None, writeable=True, text=unit_watt))
        await service.register()
        self.service = service

    async def unregister_dbus(self):
        if self.service is not None:
            self.service.__del__()
        self.service = None

    def update_dbus(self, telegram):
        with self.service as ctx:
            power_used_kwh_t1 = telegram[OBIS_ID.ELECTRICITY_USED_TARIFF_1].value
            power_used_kwh_t2 = telegram[OBIS_ID.ELECTRICITY_USED_TARIFF_2].value
            power_used_kwh = round(power_used_kwh_t1 + power_used_kwh_t2, 3)
            power_gen_kwh_t1 = telegram[OBIS_ID.ELECTRICITY_DELIVERED_TARIFF_1].value
            power_gen_kwh_t2 = telegram[OBIS_ID.ELECTRICITY_DELIVERED_TARIFF_2].value
            power_gen_kwh = round(power_gen_kwh_t1 + power_gen_kwh_t2, 3)
            ctx["/Ac/Energy/Forward"] = power_used_kwh
            ctx["/Ac/Energy/Reverse"] = power_gen_kwh
            #print("/Ac/Energy/Forward", power_used_kwh)
            #print("/Ac/Energy/Reverse", power_gen_kwh)

            total_power_w = 0
            for phase in (f"L{x}" for x in range(1, 4)):
                voltage = telegram[getattr(OBIS_ID, f"VOLTAGE_{phase}")].value
                power_kw_pos = telegram[getattr(OBIS_ID, f"ACTIVE_POWER_{phase}_POSITIVE")].value
                power_kw_neg = telegram[getattr(OBIS_ID, f"ACTIVE_POWER_{phase}_NEGATIVE")].value
                power_watt = (power_kw_pos - power_kw_neg) * 1000
                prefix = "/Ac/" + phase
                ctx[prefix + "/Voltage"] = voltage
                ctx[prefix + "/Power"] = power_watt
                ctx[prefix + "/Current"] = power_watt / voltage
                #print(prefix + "/Voltage", voltage)
                #print(prefix + "/Power", power_watt)
                #print(prefix + "/Current", round(power_watt / voltage, 3))
                total_power_w += power_watt

            ctx["/Ac/Power"] = total_power_w
            #print("/Ac/Power", total_power_w)

    async def run(self):
        while True:
            await self.unregister_dbus()

            # Try to read at least one valid telegram before we (re-)start operation
            telegram = None
            while telegram is None:
                await self.wait_for_p1_port()
                try:
                    telegram = await self.p1.async_read()
                except SerialException as exc:
                    if exc.errno == errno.ENOENT:
                        print("P1 port is unavailable")
                        await asyncio.sleep(5)  # Debounce
                except TimeoutError as exc:
                    print("Timeout on read from P1 port")

            # (Re-)register on Dbus with the serialnumber found in the telegram
            await self.register_dbus(os.path.basename(self.port), telegram)

            while True:
                # Start reading and pushing telegram data. If an error occurs
                # we'll fall back to the parent loop
                try:
                    telegram = await self.p1.async_read()
                except SerialException as exc:
                    if exc.errno == errno.ENOENT:   # TTY device disappeared
                        break   # No device to read from -> reset
                    raise
                except TimeoutError as exc:
                    break   # No data -> reset
                if telegram is not None:
                    self.update_dbus(telegram)
                else:
                    print("Telegram is None!")
