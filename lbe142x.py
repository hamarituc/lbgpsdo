#!/bin/env python

#
# Configuration Utility für Leo Bodnar GPSDO
#
# Copyright (C) 2020-2026  Mario Haustein
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import argparse
import hid
import struct
import sys



USBIDS = \
[
    ( 0x1dd2, 0x2444 ),     # LBE 1421
]



class GPSDODevice(object):
    """
    GPSDO device bound to an USB device.
    """

    @classmethod
    def enumerate(cls):
        """
        Returns USB device information descriptors.

        The method returns the USB device information descriptors of all
        detected GPSDO devices as they are returned by the HID library.

        :returns: USB device information descriptors
        :rtype: list of dict
        """

        for d in hid.enumerate():
            if ( d['vendor_id'], d['product_id'] ) in USBIDS:
                yield d


    @classmethod
    def filter(cls, serial = None, device = None):
        """
        Filters the result of the `enumerate()`.

        The method filters the detected devices by serial number or device
        path. Only devices which math all parameters are returned. If a
        parameter is `None` it will not be treated as filter criteria.

        :param serial: Serial Number of the device
        :type serial: str | None
        :param device: Device path
        :type device: bytes | None

        :returns: USB device information descriptors
        :rtype: list of dict
        """

        for d in cls.enumerate():
            if serial is not None and serial != d['serial_number']:
                continue
            if device is not None and device != d['path']:
                continue
            yield d


    @classmethod
    def open(cls, serial = None, device = None):
        """
        Opens a device and returns an instance.

        This method opens an USB device. The parameters are the same like for
        the `filter()` method. If, after applying the filter, no or more than
        one device was found, an exception is raised.

        :param serial: Serial Number of the device
        :type serial: str | None
        :param device: Device path
        :type device: bytes | None

        :raises: :class:`ValueError`: Filter criterias are not unique.

        :returns: Device instance
        :rtype: GPSDODevice
        """

        ds = list(cls.filter(serial = serial, device = device))
        if len(ds) == 0:
            raise ValueError("No GPSDO device found")
        elif len(ds) > 1:
            raise ValueError("More than one GPSDO device found. Please specifiy device path or serial number.")

        return cls(ds[0])


    @classmethod
    def openall(cls, serial = None, device = None):
        """
        Opens all devices mathing the filter and return a list of instances.

        This method opens all devices matching the specified filter. The
        parameters are the same like for the `filter()` method.

        :param serial: Serial Number of the device
        :type serial: str | None
        :param device: Device path
        :type device: bytes | None

        :returns: List of device instance
        :rtype: list of GPSDODevice
        """

        ds = list(cls.filter(serial = serial, device = device))
        for dinfo in ds:
            yield cls(dinfo)


    def __init__(self, dinfo):
        """
        Opens a device.

        DO NOT USE THIS METHOD DIRECTLY! Use the methods `open()` or
        `openall()` instead.

        :param dinfo: USB device information descriptor
        :type dinfo: dict

        :returns: Device instance
        :rtype: GPSDODevice
        """

        self.device = None
        super().__init__()

        # Open device.
        self.path          =  dinfo['path'].decode()
        self.vid           =  dinfo['vendor_id']
        self.pid           =  dinfo['product_id']
        self.manufacturer  =  dinfo['manufacturer_string']
        self.product       =  dinfo['product_string']
        self.serial        =  dinfo['serial_number']
        self.version_major = (dinfo['release_number'] & 0xff00) >> 8
        self.version_minor =  dinfo['release_number'] & 0x00ff

        self.device = hid.Device(path = dinfo['path'])
        self.read()


    def __del__(self):
        if self.device is not None:
            self.device.close()


    def read(self):
        """
        Read status and configuration from the device.
        """

        buf = self.device.get_feature_report(0x4b, 60)

        # self.loss_count = buf[0]
        self.sat_lock = bool(buf[1] & 0x01)
        self.pll_lock = bool(buf[1] & 0x02)
        self.ant_ok   = bool(buf[1] & 0x04)
        # self.led1     = bool(buf[1] & 0x08)
        # self.led2     = bool(buf[1] & 0x10)
        self.out1     = bool(buf[1] & 0x20)
        self.out2     = bool(buf[1] & 0x40)
        self.pps1     = bool(buf[1] & 0x80)
        self.f1       = struct.unpack("<I", buf[6:10])[0]
        self.f2       = struct.unpack("<I", buf[14:18])[0]
        self.fll      = bool(buf[18])
        self.out1low  = bool(buf[19])
        self.out2low  = bool(buf[20])


    def enable(self, out1, out2):
        """
        Enable or disable outputs.

        This method enables or disables output drivers for the first channel
        (`out1`) and second channel (`out2`). The driver will be enabled when
        the parameter is set to `True` and disabled when `False`. If the
        parameter is `None`, the state is not changed.

        The 1-PPS-mode takes precedence over this setting. Enabling the
        1-PPS-mode provides the clock pulse even with a disabled driver.

        :param out1: configuration for output 1
        :type out1: bool | None
        :param out2: configuration for output 2
        :type out2: bool | None
        """

        buf = 60 * [ 0 ]
        buf[0] = 1

        # As of firmware version 1.9 the flags are swapped in regards of output
        # assignment. 0x02 will configure output 1, but sets LED 2. 0x01 will
        # configure output 2, but sets LED 1.
        if out1 is None and self.out1 or out1:
            buf[1] |= 0x02
        if out2 is None and self.out2 or out2:
            buf[1] |= 0x01

        self.device.send_feature_report(bytes(buf))


    def identify(self):
        """
        Identify device.

        Blink LEDs of the device.
        """

        buf = 60 * [ 0 ]
        buf[0] = 2
        self.device.send_feature_report(bytes(buf))


    def set_freq(self, chann, f, save):
        """
        Set channel frequency.

        Sets frequency of channel `chann` (0 for first channel, 1 for second
        channel) to value `f` in Hz. When `f` is `None`, the function returns
        without doing anything.

        If `save` is true, the frequency is saved into the flash. Otherwise the
        setting is temporary until poweroff.

        :param chann: channel number
        :type chann: int
        :param f: frequency
        :type f: int | None
        :param save: save to flash
        :type save: bool

        :raises: :class:`ValueError`: frequency out of range.
        """

        buf = 60 * [ 0 ]

        if f is None:
            return

        # TODO: 1420: 1600000000
        if f > 1400000000:
            raise ValueError("Frequency for output %d too high. Maximal 1400000000 Hz allowed." % ( chann + 1 ))

        if chann == 0:
            # TODO: 1420 3, 4
            if save:
                buf[0] = 6
            else:
                buf[0] = 5
        elif chann == 1:
            if save:
                buf[0] = 10
            else:
                buf[0] = 9
        else:
            return

        buf[5:8] = struct.pack("<I", f)[0:4]

        self.device.send_feature_report(bytes(buf))


    def set_pll(self, pll):
        """
        Set PLL mode.

        When `pll` evaluates to true, the device operates in PLL mode (phase
        locked loop), otherwise in FLL mode (frequency locked loop).

        :param pll: PLL mode
        :type pll: bool
        """

        if pll is None:
            return

        buf = 60 * [ 0 ]

        buf[0] = 11
        buf[1] = 0 if pll else 1

        self.device.send_feature_report(bytes(buf))


    def set_pps(self, pps):
        """
        Enable 1-PPS-mode on first channel.

        When `pps` evaluates to true, the 1-PPS-mode is enabled. In 1-PPS-mode
        the device provides a 1 Hz pulse at the start of every UTC second on
        the first channel. The 1-PPS-mode takes precedence over frequency
        mode.

        :param pps: 1-PPS-mode
        :type pps: bool
        """

        if pps is None:
            return

        buf = 60 * [ 0 ]

        buf[0] = 12
        buf[1] = 1 if pps else 0

        self.device.send_feature_report(bytes(buf))


    def set_level(self, chann, lowlevel):
        """
        Set drive level.

        This method sets the drive level of channel `chann` (0 for first
        channel, 1 for second channel). When `level` evaluates to true, the
        driver is set to low level, otherwise to normal power level.

        :param chann: channel number
        :type chann: int
        :param lowlevel: driver level
        :type lowlevel: bool
        """

        if lowlevel is None:
            return

        buf = 60 * [ 0 ]

        if chann == 0:
            # TODO: 1420 7
            buf[0] = 13
        elif chann == 1:
            buf[0] = 14
        else:
            return

        buf[1] = 1 if lowlevel else 0

        self.device.send_feature_report(bytes(buf))


    def infotext(self):
        """
        Returns current device status and configuration as formatted text.

        :returns: Status
        :rtype: str
        """

        result = ""

        result += "Device information\n"
        result += "------------------\n"
        result += "VID, PID:     0x%04x:0x%04x\n" % ( self.vid, self.pid )
        result += "Device:       %s\n"            % self.path
        result += "Product:      %s\n"            % self.product
        result += "Manufacturer: %s\n"            % self.manufacturer
        result += "S/N:          %s\n"            % self.serial
        result += "Firmware:     %d.%d\n"         % ( self.version_major, self.version_minor )
        result += "\n"

        result += "Device status\n"
        result += "-------------\n"
        # result += "Loss count:   %d\n" % self.loss_count
        result += "SAT lock:     %s\n" % ( "LOCKED"  if self.sat_lock else "unlocked" )
        result += "PLL lock:     %s\n" % ( "LOCKED"  if self.pll_lock else "unlocked" )
        result += "Antenna:      %s\n" % ( "OK"      if self.ant_ok   else "short-circuit" )
        result += "Mode:         %s\n" % ( "FLL"     if self.fll      else "PLL" )
        result += "\n"

        result += "Output settings\n"
        result += "---------------\n"

        result += "Output 1:    "
        if self.pps1:
            result += "1 PPS"
        elif not self.out1:
            result += "       ---   "
        else:
            result += "%10d Hz" % self.f1
        result += "  level: %s\n" % ( "LOW" if self.out1low else "NORMAL" )

        result += "Output 2:    "
        if not self.out2:
            result += "       ---   "
        else:
            result += "%10d Hz" % self.f2
        result += "  level: %s\n" % ( "LOW" if self.out1low else "NORMAL" )

        result += "\n"

        result = result.strip("\n")
        if result:
            result += "\n"

        return result



#
# Command Callbacks
#

def command_list(args):
    for d in GPSDODevice.enumerate():
        sys.stdout.write("%04x:%04x %-16s  %s  %s\n" % \
            (
                d['vendor_id'],
                d['product_id'],
                d['path'].decode(),
                d['serial_number'],
                d['product_string'],
            ))


def command_detail(args):
    first = True
    for d in GPSDODevice.openall(serial = args.serial, device = args.device):
        if first:
            first = False
        else:
            sys.stdout.write("\n\n")
        sys.stdout.write(d.infotext())


def command_modify(args):
    d = GPSDODevice.open(serial = args.serial, device = args.device)

    d.enable(args.out1, args.out2)
    d.set_freq(0, args.f1, args.save)
    d.set_freq(1, args.f2, args.save)
    d.set_pll(args.pll)
    d.set_pps(args.pps)
    d.set_level(0, args.out1low)
    d.set_level(1, args.out2low)


def command_identify(args):
    d = GPSDODevice.open(serial = args.serial, device = args.device)
    d.identify()



#
# Command Line Parser Helper Functions
#

def parser_add_device(p):
    p.add_argument(
        '-s', '--serial',
        dest = 'serial',
        metavar = 'S/N',
        help = "Serial number of GPS device")

    p.add_argument(
        '-d', '--device',
        dest = 'device',
        metavar = 'PATH',
        help = "Path specification of the USB HID device")


def parser_add_config(p):
    parser_config = p.add_argument_group(
        title = "Configuration")

    parser_config.add_argument(
        '--f1',
        dest = 'f1',
        metavar = 'HZ',
        type = int,
        help = "Output 1 frequency")

    parser_config.add_argument(
        '--f2',
        dest = 'f2',
        metavar = 'HZ',
        type = int,
        help = "Output 2 frequency")

    parser_config.add_argument(
        '--save',
        dest = 'save',
        action = 'store_true',
        help = "Save frequency to flash memory")

    parser_config.add_argument(
        '--pll',
        dest = 'pll',
        action = 'store_const',
        const = True,
        help = "Set PLL mode")

    parser_config.add_argument(
        '--fll',
        dest = 'pll',
        action = 'store_const',
        const = False,
        help = "Set FLL mode")

    parser_config.add_argument(
        '--enable1',
        dest = 'out1',
        action = 'store_const',
        const = True,
        help = "Enable output 1")

    parser_config.add_argument(
        '--disable1',
        dest = 'out1',
        action = 'store_const',
        const = False,
        help = "Disable output 1")

    parser_config.add_argument(
        '--pps-enable',
        dest = 'pps',
        action = 'store_const',
        const = True,
        help = "Enable PPS signal on output 1")

    parser_config.add_argument(
        '--pps-disable',
        dest = 'pps',
        action = 'store_const',
        const = False,
        help = "Enable PPS signal on output 1")

    parser_config.add_argument(
        '--level1-low',
        dest = 'out1low',
        action = 'store_const',
        const = True,
        help = "Output 1 drive low level")

    parser_config.add_argument(
        '--level1-normal',
        dest = 'out1low',
        action = 'store_const',
        const = False,
        help = "Output 1 drive normal level")

    parser_config.add_argument(
        '--enable2',
        dest = 'out2',
        action = 'store_const',
        const = True,
        help = "Enable output 2")

    parser_config.add_argument(
        '--disable2',
        dest = 'out2',
        action = 'store_const',
        const = False,
        help = "Disable output 2")

    parser_config.add_argument(
        '--level2-low',
        dest = 'out2low',
        action = 'store_const',
        const = True,
        help = "Output 2 drive low level")

    parser_config.add_argument(
        '--level2-normal',
        dest = 'out2low',
        action = 'store_const',
        const = False,
        help = "Output 2 drive normal level")


#
# Command Line Parser Definition
#

parser = argparse.ArgumentParser()

subparsers = parser.add_subparsers()


parser_list = subparsers.add_parser(
    'list',
    aliases = [ 'l' ],
    help = "List devices")

parser_list.set_defaults(func = command_list)


parser_detail = subparsers.add_parser(
    'detail',
    aliases = [ 'd' ],
    help = "Show details of a device")

parser_add_device(parser_detail)
parser_detail.set_defaults(func = command_detail)


parser_modify = subparsers.add_parser(
    'modify',
    aliases = [ 'm' ],
    help = "Change configuration of a single device")

parser_add_device(parser_modify)
parser_add_config(parser_modify)
parser_modify.set_defaults(func = command_modify)


parser_identify = subparsers.add_parser(
    'identify',
    aliases = [ 'i' ],
    help = "Identify output channel of a device")

parser_add_device(parser_identify)

parser_identify.set_defaults(func = command_identify)



#
# Here we go.
#

if __name__ == '__main__':
    args = parser.parse_args()
    if 'func' in args:
        args.func(args)
    else:
        parser.print_help()
