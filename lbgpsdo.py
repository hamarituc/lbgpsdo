#!/bin/env python

#
# Configuration Utility für Leo Bodnar GPSDO
#
# Copyright (C) 2020  Mario Haustein
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
from fractions import Fraction
import hid
import json
import math
import struct
import sys



USBIDS = \
[
    ( 0x1dd2, 0x2210 ),
    ( 0x1dd2, 0x2211 ),
]



class GPSDOConfigurationException(Exception):
    """
    Exception raised for invalid GPSDO configurations.

    The exception contains a dictionary of invalid settings. The keyword
    specifiyes the parameter and it's value is a verbose error message.
    """

    def errortext(self):
        result = ""
        for attr, msg in self.args[0].items():
            result += "%-7s %s\n" % ( attr + ":", msg )
        return result



class GPSDO(object):
    """
    Virtual GPSDO device independent from a real device.

    Used for clock calculations.
    """

    OUTPUT1 = 0x01
    OUTPUT2 = 0x02

    LEVEL_VALUE_8MA  = 0
    LEVEL_VALUE_16MA = 1
    LEVEL_VALUE_24MA = 2
    LEVEL_VALUE_32MA = 3

    LEVEL_DISPLAY = \
    {
        0:  "8 mA",
        1: "16 mA",
        2: "24 mA",
        3: "32 mA",
    }

    LEVEL_VALUE = \
    {
         8: LEVEL_VALUE_8MA,
        16: LEVEL_VALUE_16MA,
        24: LEVEL_VALUE_24MA,
        32: LEVEL_VALUE_32MA,
    }


    #    8 kHz .. 710 MHz according to table 26 in Si53xx family reference manual
    #    2 kHz .. 710 MHz according to table 3 in Si5328 datasheet
    # 0.25 Hz  ..  10 MHz according to u-blox MAX-M8Q datasheet
    #   10 kHz ..  16 MHz by trial (lower limit set by f3)
    LIMIT_FIN_MIN =    10000
    LIMIT_FIN_MAX = 16000000

    #  2 kHz .. 2 MHz according to table 26 in Si53xx family reference manual
    # 10 kHz .. 2 MHz by trial
    LIMIT_F3_MIN =   10000
    LIMIT_F3_MAX = 2000000

    # according to table 26 in Si53xx family reference manual
    LIMIT_FOSC_MIN = 4850000000
    LIMIT_FOSC_MAX = 5670000000

    #
    # Output frequency range is not defined consistently.
    #
    #   8 kHz .. 808.0 MHz according to table 3 in Si5328 datasheet (model C, non CMOS output)
    #   8 kHz .. 212.5 MHz according to table 3 in Si5328 datasheet (CMOS output)
    #   2 kHz .. 808.0 MHz according to table 26 in Si53xx family reference manual
    # 450 Hz  .. 800.0 MHz according to Leo Bodnar datasheet
    #
    # We choose 450 Hz .. 808 MHz.
    #
    LIMIT_FOUT_MIN =       450
    LIMIT_FOUT_MAX = 808000000


    _CONFIG_CHECKS = \
    [
        ( 'fin',    "GPS reference frequency",     LIMIT_FIN_MIN, LIMIT_FIN_MAX, 0, "in the range of 10 kHz to 16 MHz" ),
        ( 'n3',     "Input divider N3",                        1,         2**19, 0, "in the range of 1 to 524288"      ),
        ( 'n2_hs',  "Feedback divider N2_HS",                  4,            11, 0, "in the range of 4 to 11"          ),
        ( 'n2_ls',  "Feedback divider N2_LS",                  2,         2**20, 2, "in the range of 2 to 1048576"     ),
        ( 'n1_hs',  "Output common divider N1_HS",             4,            11, 0, "in the range of 4 to 11"          ),
        ( 'nc1_ls', "Output 1 divider NC1_LS",                 2,         2**20, 1, "in the range of 1 to 1048576"     ),
        ( 'nc2_ls', "Output 2 divider NC2_LS",                 2,         2**20, 1, "in the range of 1 to 1048576"     ),
        ( 'skew',   "SKEW",                                    0,           255, 0, "in the range of 0 to 255"         ),
        ( 'bw',     "BWSEL",                                   0,            15, 0, "in the range of 0 to 15"          ),
    ]

    _FREQ_CHECKS = \
    [
        ( 'f3',    "Phase detector frequency", LIMIT_F3_MIN,   LIMIT_F3_MAX,   "must be in the range of 2 kHz to 2 MHz"       ),
        ( 'fosc',  "Oscillator frequency",     LIMIT_FOSC_MIN, LIMIT_FOSC_MAX, "must be in the range of 4.85 GHz to 5.67 GHz" ),
        ( 'fout1', "Output 1 frequency",       LIMIT_FOUT_MIN, LIMIT_FOUT_MAX, "must be in the range of 450 Hz to 808 MHz"    ),
        ( 'fout2', "Output 2 frequency",       LIMIT_FOUT_MIN, LIMIT_FOUT_MAX, "must be in the range of 450 Hz to 808 MHz"    ),
    ]


    def __init__(self, *args, **kwargs):
        self.out1   = False
        self.out2   = False
        self.level  = 0
        self.fin    = None
        self.n3     = None
        self.n2_hs  = None
        self.n2_ls  = None
        self.n1_hs  = None
        self.nc1_ls = None
        self.nc2_ls = None
        self.skew   = 0
        self.bw     = 15


    def update(self, *args, **kwargs):
        """
        Update the configuration.

        Specifiy the parameter by keyword argument. The following arguments are
        defined.

        :param out1: Enable output 1.
        :type out1: bool
        :param out2: Enable output 2.
        :type out2: bool
        :param level: Drive level for both outputs.
        :param fin: GPS reference frequency.
        :type fin: int
        :param n3: Input divider factor N3.
        :type n3: int
        :param n2_hs: Feedback high speed divider factor N2_HS.
        :type n2_hs: int
        :param n2_ls: Feedback low speed divider factor N2_LS.
        :type n2_ls: int
        :param n1_hs: Output common divider factor N1_HS.
        :type n1_hs: int
        :param nc1_ls: Output 1 divider factor NC1_LS.
        :type nc1_ls: int
        :param nc2_ls: Output 2 divider factor NC2_LS.
        :type nc2_ls: int
        :param skew: Output 2 divider clock skew.
        :type skew: int
        :param bw: Loop bandwith mode.
        :type bw: int

        :raises: :class:`GPSDOConfigurationException`: Invalid configuration
        """

        out1  = kwargs.pop('out1',  None)
        out2  = kwargs.pop('out2',  None)
        level = kwargs.pop('level', None)

        errdict = {}

        # Check the arguments first.
        for attr, name, vmin, vmax, even, msg in self._CONFIG_CHECKS:
            if attr not in kwargs:
                continue

            value = kwargs[attr]
            if value is None:
                continue

            if not isinstance(value, int):
                errdict[attr] = "%s must be an integer." % name
                continue

            if (vmin is not None and value < vmin) or \
               (vmax is not None and value > vmax):
                errdict[attr] = "%s must be %s." % ( name, msg )

            if even and (value % 2):
                if even == 1 and value != 1:
                    errdict[attr] = "%s must be 1 or even." % name
                    continue

                errdict[attr] = "%s must be even." % name
                continue

        if level is not None and (level < 0 or level > 3):
            errdict['level'] = "Invalid drive level."

        if errdict:
            raise GPSDOConfigurationException(errdict)

        # Update the PLL settings.
        for attr, name, vmin, vmax, even, msg in self._CONFIG_CHECKS:
            value = kwargs.pop(attr, None)
            if value is None:
                continue
            setattr(self, attr, value)

        if out1 is not None:
            self.out1 = bool(out1)
        if out2 is not None:
            self.out2 = bool(out2)
        if level is not None:
            self.level = level


    def asdict(self, ignore_freq_limits = False):
        """
        Returns the configuration as a dictionary.

        The returned dict can by use a argument for `update()` method to
        restore the settings.

        The method raises an exception if the configuration is invalid. If
        `ignore_freq_limits` is `True`, no error is raised if an intermediate
        frequency exceeds the limits specified in the datasheet.

        :param ignore_freq_limits: Ignore frequency limits defined in the datasheet.
        :type ignore_freq_limits: bool

        :raises: :class:`GPSDOConfigurationException`: Invalid configuration

        :returns: Configuration
        :rtype: dict
        """

        freq, errdict, errflag = self.freqplan(ignore_freq_limits = ignore_freq_limits)
        if errflag:
            raise GPSDOConfigurationException({ a: v for a, v in errdict.items() if v is not None })

        configdict = \
            {
                'out1':   self.out1,
                'out2':   self.out2,
                'level':  self.level,
                'fin':    self.fin,
                'n3':     self.n3,
                'n2_hs':  self.n2_hs,
                'n2_ls':  self.n2_ls,
                'n1_hs':  self.n1_hs,
                'nc1_ls': self.nc1_ls,
                'nc2_ls': self.nc2_ls,
                'skew':   self.skew,
                'bw':     self.bw,
            }

        return configdict


    def freqplan(self, modify = False, ignore_freq_limits = False):
        """
        Returns the frequency plan.

        Returns a dictionary containing the output and intermediate frequencies
        for the current settings as well as phase relation between output 1 and
        output 2. If a value cannot be computed its entry is `None`.

        Furthermore informations about configuration errors are returned
        through a dict. The keyword of the dict specifies the parameter wheres
        the value is an verbose error message. The dict contains an entry for
        every element of the frequency plan. If there is no error, its value
        is `None`. The method doesn't raise an exception for invalid
        configurations.

        The last element of the returned tuple is an error flag. It is true if
        the frequency plan is invalid.

        If `modify` is `True`, the method will set unused output dividers
        to reasonable default values if they are undefined.

        :param modify: Enable output 1.
        :type modify: bool

        If `ignore_freq_limits` is `True`, no error is raised if an
        intermediate frequency exceeds the limits specified in the datasheet.

        :param ignore_freq_limits: Ignore frequency limits defined in the datasheet.
        :type ignore_freq_limits: bool

        :raises: :class:`GPSDOConfigurationException`: Invalid configuration

        :returns: Frequency plan and error information
        :rtype: ( dict, dict, bool )
        """

        if modify:
            # Use other channels divider if the channel is disabled, to prevent
            # bogus errors
            if not self.out1 and self.nc1_ls is None and self.out2:
                self.nc1_ls = self.nc2_ls
            if not self.out2 and self.nc2_ls is None and self.out1:
                self.nc2_ls = self.nc1_ls

            # Use a divider value which is safe under any circumstances if no
            # value is specified and both channels are disabled.
            if not self.out1 and not self.out2:
                if self.nc1_ls is None:
                    self.nc1_ls = 5670
                if self.nc2_ls is None:
                    self.nc2_ls = 5670

        errdict = {}

        # Check for undefined settings.
        for attr, name, lmin, lmax, even, msg in self._CONFIG_CHECKS:
            errdict[attr] = ("%s undefined." % name) if getattr(self, attr, None) is None else None

        # Compute frequency plan.
        f3            = None if self.fin    is None or self.n3    is None                        else Fraction(self.fin, self.n3)
        fosc          = None if f3          is None or self.n2_hs is None or self.n2_ls  is None else f3 * self.n2_hs * self.n2_ls
        fout1         = None if fosc        is None or self.n1_hs is None or self.nc1_ls is None else fosc / (self.n1_hs * self.nc1_ls)
        fout2         = None if fosc        is None or self.n1_hs is None or self.nc2_ls is None else fosc / (self.n1_hs * self.nc2_ls)
        phase         = None if fosc        is None or self.n1_hs is None or self.skew   is None else self.skew * self.n1_hs / fosc
        phaseres      = None if fosc        is None or self.n1_hs is None                        else self.n1_hs / fosc
        phaseangle    = None if self.nc2_ls is None or self.skew  is None                        else Fraction(self.skew % self.nc2_ls, self.nc2_ls)
        phaseangleres = None if self.nc2_ls is None                                              else Fraction(1, self.nc2_ls) 

        freq = \
        {
            'f3':            f3,
            'fosc':          fosc,
            'fout1':         fout1,
            'fout2':         fout2,
            'phaseres':      phaseres,
            'phase':         phase,
            'phaseangle':    phaseangle,
            'phaseangleres': phaseangleres,
        }

        # Check allowed frequency ranges.
        for attr, name, lmin, lmax, msg in self._FREQ_CHECKS:
            value = freq[attr]
            if value is None:
                errdict[attr] = "%s undefined." % name
            elif ignore_freq_limits:
                errdict[attr] = None
            elif value < lmin or value > lmax:
                errdict[attr] = "%s is %s, but %s." % ( name, self._format_freq(value), msg )
            else:
                errdict[attr] = None

        # Check skew.
        if self.skew is not None and self.nc2_ls is not None:
            # GPSDO produces wrong signals for SKEW = NC2_LS - 1, so we limit to NC2_LS - 2.
            skewmax = max(self.nc2_ls - 2, 0)
            if self.skew > skewmax:
                errdict['skew'] = "SKEW must be in the range of 0 to %d (= NC2_LS - 2)" % skewmax
        if 'skew' not in errdict:
            errdict['skew'] = None

        return freq, errdict, any([ v is not None for v in errdict.values() ])


    def _scale_freq(self, value):
        if value is None:
            return None, None

        for u in [ "Hz", "kHz", "MHz", "GHz" ]:
            if value < 1000:
                return value, u
            value /= 1000

        return value, "GHz"


    def _scale_duration(self, value):
        if value is None:
            return None, None

        v = value
        for u in [ "s", "ms", "µs", "ns", "ps" ]:
            if math.fabs(v) >= 1:
                return v, u
            v *= 1000

        return value, "s"


    def _format_freq(self, value):
        valuenum, valueunit = self._scale_freq(value)

        if valuenum is None:
            return None
        else:
            return "%7.3f %-3s" % ( valuenum, valueunit )


    def _format_duration(self, value):
        valuenum, valueunit = self._scale_duration(value)

        if valuenum is None:
            return None
        else:
            return "%7.3f %-2s" % ( valuenum, valueunit )


    def _format_phaseangle(self, value):
        if value is None:
            None
        else:
            return "%7.3f °" % (value * 360)


    def _format_scaler_line(self, value, name, text):
        return "%-6s = %7s  %s\n" % \
            (
                name,
                ("%d" % value) if value is not None else "---",
                text,
            )


    def _format_freq_line(self, value, err, name, text, fraction):
        if value is not None:
            valuefloat = "%10.0f Hz" % value
            valuefrac  = ("%10d/%4d Hz" % ( value.numerator, value.denominator )) if fraction else ""
            valueexact = value.denominator == 1
        else:
            valuefloat = "---"
            valuefrac  = "---" if fraction else ""
            valueexact = True

        return "%-6s = %18s %s %13s  %2s %s\n" % \
            (
                name,
                valuefrac,
                ("=" if valueexact else "≈") if fraction else " ",
                valuefloat,
                "!!" if err is not None else "",
                text,
            )


    def _format_phase_line(self, phase, phaseangle, phaseres, phaseangleres):
        phase, phaseunit = self._scale_duration(phase)
        if phase is not None:
            phasefloat = "%10.3f %-2s" % ( phase, phaseunit )
            phasefrac  = "%10d/%4d %-2s" % ( phase.numerator, phase.denominator, phaseunit )
        else:
            phasefloat = "---"
            phasefrac  = "---"

        if phaseangle is not None:
            value = phaseangle * 360
            phaseanglefloat = "%7.3f ° " % ( value )
            phaseanglefrac  = "%10d/%4d ° " % ( value.numerator, value.denominator )
        else:
            phaseanglefloat = "---"
            phaseanglefrac  = "---"

        phaseres, phaseresunit = self._scale_duration(phaseres)
        if phaseres is not None:
            phaseresfloat = "%10.3f %-2s" % ( phaseres, phaseresunit )
            phaseresfrac  = "%10d/%4d %-2s" % ( phaseres.numerator, phaseres.denominator, phaseresunit )
        else:
            phaseresfloat = "---"
            phaseresfrac  = "---"

        if phaseangleres is not None:
            value = phaseangleres * 360
            phaseangleresfloat = "%7.3f ° " % ( value )
            phaseangleresfrac  = "%10d/%4d ° " % ( value.numerator, value.denominator )
        else:
            phaseangleresfloat = "---"
            phaseangleresfrac  = "---"

        result = ""
        result += "phase  = %18s = %13s     Phase offset output 1 --> 2\n" % \
            (
                phasefrac,
                phasefloat,
            )
        result += "       = %18s = %13s     Phase angle w.r.t output 2\n" % \
            (
                phaseanglefrac,
                phaseanglefloat,
            )
        result += "pres   = %18s = %13s     Phase offset resolution\n" % \
            (
                phaseresfrac,
                phaseresfloat,
            )
        result += "       = %18s = %13s\n" % \
            (
                phaseangleresfrac,
                phaseangleresfloat,
            )

        return result


    def infotext(self, show_freq = True, *args, **kwargs):
        """
        Returns current configuration as formatted text.

        The method returns a summary of the current configuration, frequency
        plan and configuration errors as a formatted text block.

        :param show_freq: If `False`, an empty string will be returned
        :type show_freq: bool

        :returns: Configuration
        :rtype: str
        """

        if not show_freq:
            return ""

        freq, errdict, errflag = self.freqplan()

        result = ""

        result += "Output settings\n"
        result += "---------------\n"
        result += "Output 1:    %11s\n" % ((self._format_freq(freq['fout1']) or "---    ") if self.out1 else "")
        result += "Output 2:    %11s\n" % ((self._format_freq(freq['fout2']) or "---    ") if self.out2 else "")
        result += "Phase:       %9s  \n" % ((self._format_phaseangle(freq['phaseangle']) or "---   ") if self.out1 and self.out2 else "")
        result += "Drive level: %10s \n" % self.LEVEL_DISPLAY[self.level]
        result += "\n"

        result += "PLL settings\n"
        result += "------------\n"
        result += self._format_scaler_line(self.n3,     "N3",     "Input divider factor")
        result += self._format_scaler_line(self.n2_hs,  "N2_HS",  "Feedback divider factor")
        result += self._format_scaler_line(self.n2_ls,  "N2_LS",  "")
        result += self._format_scaler_line(self.n1_hs,  "N1_HS",  "Output common divider factor")
        result += self._format_scaler_line(self.nc1_ls, "NC1_LS", "Output 1 divider factor")
        result += self._format_scaler_line(self.nc2_ls, "NC2_LS", "Output 2 divider factor")
        result += "SKEW   =    %+4d  Clock skew\n"         % self.skew
        result += "BWSEL  =     %3d  Loop bandwith code\n" % self.bw
        result += "\n"

        result += "Frequency plan\n"
        result += "--------------\n"
        result += self._format_freq_line(self.fin,      errdict['fin'],   "fin",   "GPS reference frequency",  fraction = False)
        result += self._format_freq_line(freq['f3'],    errdict['f3'],    "f3",    "Phase detector frequency", fraction = True)
        result += self._format_freq_line(freq['fosc'],  errdict['fosc'],  "fosc",  "Oscillator frequency",     fraction = True)
        result += self._format_freq_line(freq['fout1'], errdict['fout1'], "fout1", "Output 1 frequency",       fraction = True)
        result += self._format_freq_line(freq['fout2'], errdict['fout2'], "fout2", "Output 2 frequency",       fraction = True)
        result += self._format_phase_line(freq['phase'], freq['phaseangle'], freq['phaseres'], freq['phaseangleres'])

        if errflag:
            result += "\n"
            result += "Errors\n"
            result += "------\n"
            for attr, msg in errdict.items():
                if msg is not None:
                    result += "%-7s %s\n" % ( attr + ":", msg )

        return result


    def plltext(self):
        """
        Returns a PLL diagram.

        The method returns a formatted text block of the PLL diagram together
        with the frequency constraints. The return value is independent of the
        current configuration.

        :returns: PLL diagram
        :rtype: str
        """

        formula = \
        {
            'f3':    "fin / N3",
            'fosc':  "fin * (N2_LS * N2_HS) / N3",
            'fout1': "fosc / (N1_HS * NC1_LS)",
            'fout2': "fosc / (N1_HS * NC2_LS)",
        }

        result  = ""
        result += "  fin          f3   +-------+                                       fout1  \n"
        result += "------> ÷ N3 -----> |       |   fosc                 +-> ÷ NC1_LS -------->\n"
        result += "                    |  PLL  | --------+--> ÷ N1_HS --|                     \n"
        result += "          +-------> |       |         |              +-> ÷ NC2_LS -------->\n"
        result += "          |         +-------+         |                             fout2  \n"
        result += "          |                           |                                    \n"
        result += "          +-- ÷ N2_LS <--- ÷ N2_HS <--+                                    \n"
        result += "\n"

        flist = []
        flist.extend([ ( f[0], f[2], f[3] ) for f in self._CONFIG_CHECKS if f[0] == 'fin' ])
        flist.extend([ ( f[0], f[2], f[3] ) for f in self._FREQ_CHECKS                    ])
        for name, fmin, fmax in flist:
            result += "%-5s = %-30s %s %s ... %s\n" % \
                (
                    name,
                    formula[name] if name in formula else "",
                    "=" if name in formula else " ",
                    self._format_freq(fmin),
                    self._format_freq(fmax),
                )

        return result



class GPSDODevice(GPSDO):
    """
    GPSDO device bound to an USB device.
    """

    _COMMAND_OUTPUT   = 1
    _COMMAND_IDENTIFY = 2
    _COMMAND_LEVEL    = 3
    _COMMAND_PLL      = 4


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


    def __del__(self):
        if self.device is not None:
            self.device.close()


    def read_status(self):
        """
        Read status information from the device.

        Read signal loss count and lock status from the device. The
        corresponding status attributes of the instance are updated.
        Furthermore the current status is returned as a dictionary.

        :returns: Status
        :rtype: dict
        """

        buf = self.device.read(2)

        result = {}
        result['loss_count'] = self.loss_count = buf[0]
        result['sat_lock']   = self.sat_lock   = not bool(buf[1] & 0x01)
        result['pll_lock']   = self.pll_lock   = not bool(buf[1] & 0x02)

        return result


    def read_config(self, update = True):
        """
        Read configuration from the device.

        Read configuration from the device. If `update` is `True` the
        corresponding configuration attributes of the instance are updated.
        Furthermore the device configuration is returned as a dictionary
        independently of the value of `update` in the same way as by the
        `asdict()` method. Thus it is possible to compare the current
        configuration with the device configuration by setting `update` to
        `False`.

        :param update: Update configuration attributes according to current
                       device configuration.
        :type update: bool

        :returns: Configuration
        :rtype: dict
        """

        buf = self.device.get_feature_report(9, 60)

        result = {}
        result['out1']   = bool(buf[0] & self.OUTPUT1)
        result['out2']   = bool(buf[0] & self.OUTPUT2)
        result['level']  = struct.unpack("<B", buf[ 1: 2]               )[0]
        result['fin']    = struct.unpack("<I", buf[ 2: 5] + bytes([ 0 ]))[0]
        result['n3']     = struct.unpack("<I", buf[ 5: 8] + bytes([ 0 ]))[0] + 1
        result['n2_hs']  = struct.unpack("<B", buf[ 8: 9]               )[0] + 4
        result['n2_ls']  = struct.unpack("<I", buf[ 9:12] + bytes([ 0 ]))[0] + 1
        result['n1_hs']  = struct.unpack("<B", buf[12:13]               )[0] + 4
        result['nc1_ls'] = struct.unpack("<I", buf[13:16] + bytes([ 0 ]))[0] + 1
        result['nc2_ls'] = struct.unpack("<I", buf[16:19] + bytes([ 0 ]))[0] + 1
        result['skew']   = struct.unpack("<B", buf[19:20]               )[0]
        result['bw']     = struct.unpack("<B", buf[20:21]               )[0]

        if update:
            self.update(**result)

        return result


    def read(self, update = True):
        """
        Read configuration and status from the device.

        This method is an abbreviation for calling `read_status()` and
        `read_config()`. The result of both methods is merged to a single
        dictionary.

        :param update: Update configuration attributes according to current
                       device configuration.
        :type update: bool

        :returns: Configuration
        :rtype: dict
        """

        result = {}
        result.update(self.read_status())
        result.update(self.read_config(update = update))

        return result


    def write(self, overwrite = False, ignore_freq_limits = False):
        """
        Write configuration to the device.

        Write the configuration to the device. If the configuration is invalid
        an exception is raised.

        The configuration will only be updated if it differs from the current
        device configuration. For this check `read_config()` is called
        internally to compare the current configuration with the device. By
        setting `overwrite` to `True` this check will be omitted and the
        configuration will be updated in any case.

        :param overwrite: Force updating the configuration.
        :type overwrite: bool

        If `ignore_freq_limits` is `True`, no error is raised if an
        intermediate frequency exceeds the limits specified in the datasheet.

        :param ignore_freq_limits: Ignore frequency limits defined in the datasheet.
        :type ignore_freq_limits: bool

        :raises: :class:`GPSDOConfigurationException`: Invalid configuration
        """

        # Check settings.
        freq, errdict, errflag = self.freqplan(ignore_freq_limits = ignore_freq_limits)

        # Dont't upload invalid settings.
        if errflag:
            raise GPSDOConfigurationException({ a: v for a, v in errdict.items() if v is not None })

        # Get current settings from device.
        configdict = self.read(update = False)

        # Upload PLL settings.
        if overwrite or \
           (self.fin    != configdict['fin'])    or \
           (self.n3     != configdict['n3'])     or \
           (self.n2_hs  != configdict['n2_hs'])  or \
           (self.n2_ls  != configdict['n2_ls'])  or \
           (self.n1_hs  != configdict['n1_hs'])  or \
           (self.nc1_ls != configdict['nc1_ls']) or \
           (self.nc2_ls != configdict['nc2_ls']) or \
           (self.skew   != configdict['skew'])   or \
           (self.bw     != configdict['bw']):
            buf = 60 * [ 0 ]
            buf[0]     = self._COMMAND_PLL
            buf[ 1: 4] = struct.pack("<I", self.fin       )[0:3]
            buf[ 4: 7] = struct.pack("<I", self.n3     - 1)[0:3]
            buf[ 7: 8] = struct.pack("<B", self.n2_hs  - 4)[0:1]
            buf[ 8:11] = struct.pack("<I", self.n2_ls  - 1)[0:3]
            buf[11:12] = struct.pack("<B", self.n1_hs  - 4)[0:1]
            buf[12:15] = struct.pack("<I", self.nc1_ls - 1)[0:3]
            buf[15:18] = struct.pack("<I", self.nc2_ls - 1)[0:3]
            buf[18:19] = struct.pack("<B", self.skew      )[0:1]
            buf[19:20] = struct.pack("<B", self.bw        )[0:1]
            self.device.send_feature_report(bytes(buf))

        # Upload drive level.
        if overwrite or \
           self.level != configdict['level']:
            buf = 60 * [ 0 ]
            buf[0] = self._COMMAND_LEVEL
            buf[1] = self.level
            self.device.send_feature_report(bytes(buf))

        # Upload output settings.
        if overwrite or \
           self.out1 != configdict['out1'] or \
           self.out2 != configdict['out2']:
            buf = 60 * [ 0 ]
            buf[0]  = self._COMMAND_OUTPUT
            buf[1] |= self.OUTPUT1 if self.out1 else 0
            buf[1] |= self.OUTPUT2 if self.out2 else 0
            self.device.send_feature_report(bytes(buf))


    def identify(self, output):
        """
        Identify output channels.

        Identify output channels by blinking the LEDs. `output` must be one of
        the class attributes `OUTPUT1` or `OUTPUT2`. To stop blinking set
        `output` to 0.

        :param output: Channel to identify
        :type output: int
        """

        buf = 60 * [ 0 ]
        buf[0] = self._COMMAND_IDENTIFY
        buf[1] = output
        self.device.send_feature_report(bytes(buf))


    def infotext(self, show_status = True, *args, **kwargs):
        """
        Returns current device status and configuration as formatted text.

        :param show_status: If `True`, the output will contain device status
                            information.
        :type show_status: bool
        :param show_freq: If `True`, the output will contain the frequency
                          plan and error information.
        :type show_freq: bool

        :returns: Status
        :rtype: str
        """

        result = ""

        if show_status:
            result += "Device information\n"
            result += "------------------\n"
            result += "VID, PID:     0x%04x:0x%04x\n" % ( self.pid, self.vid )
            result += "Device:       %s\n"            % self.path
            result += "Product:      %s\n"            % self.product
            result += "Manufacturer: %s\n"            % self.manufacturer
            result += "S/N:          %s\n"            % self.serial
            result += "Firmware:     %d.%d\n"         % ( self.version_major, self.version_minor )
            result += "\n"

            result += "Device status\n"
            result += "-------------\n"
            result += "Loss count:   %d\n" % self.loss_count
            result += "SAT lock:     %s\n" % ( "LOCKED" if self.sat_lock else "unlocked" )
            result += "PLL lock:     %s\n" % ( "LOCKED" if self.pll_lock else "unlocked" )
            result += "\n"

        result += super().infotext(*args, **kwargs)

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


def command_status(args):
    for d in GPSDODevice.openall(serial = args.serial, device = args.device):
        d.read_status()
        sys.stdout.write("%-8s  %s: SAT %-8s  PLL %-8s  Loss: %d\n" % \
            (
                d.serial,
                d.path,
                "locked" if d.sat_lock else "unlocked",
                "locked" if d.pll_lock else "unlocked",
                d.loss_count,
            ))


def command_detail(args):
    first = True
    for d in GPSDODevice.openall(serial = args.serial, device = args.device):
        d.read()
        if first:
            first = False
        else:
            sys.stdout.write("\n\n")
        sys.stdout.write(d.infotext())


def command_modify(args):
    d = GPSDODevice.open(serial = args.serial, device = args.device)

    try:
        d.read()
        d.update(**parser_get_config(args))
        sys.stdout.write(d.infotext(show_status = args.show_status, show_freq = args.show_freq))
        if not args.pretend:
            d.write(ignore_freq_limits = args.ignore_freq_limits)
    except GPSDOConfigurationException as e:
        sys.stdout.write("Parameter error:\n")
        sys.stdout.write(e.errortext())


def command_backup(args):
    d = GPSDODevice.open(serial = args.serial, device = args.device)

    try:
        d.read()
        sys.stdout.write(d.infotext(show_status = args.show_status, show_freq = args.show_freq))
        json.dump(d.asdict(ignore_freq_limits = args.ignore_freq_limits),
                  args.output_file, indent = 2)
    except GPSDOConfigurationException as e:
        sys.stdout.write("Parameter error:\n")
        sys.stdout.write(e.errortext())


def command_restore(args):
    d = GPSDODevice.open(serial = args.serial, device = args.device)

    try:
        d.update(**json.load(args.input_file))
        sys.stdout.write(d.infotext(show_status = False, show_freq = args.show_freq))
        if not args.pretend:
            d.write(ignore_freq_limits = args.ignore_freq_limits)
    except GPSDOConfigurationException as e:
        sys.stdout.write("Parameter error:\n")
        sys.stdout.write(e.errortext())


def command_identify(args):
    d = GPSDODevice.open(serial = args.serial, device = args.device)
    d.identify(args.out)


def command_analyze(args):
    if args.input_device or args.output_device:
        d = GPSDODevice.open(serial = args.serial, device = args.device)
    else:
        d = GPSDO()

    try:
        if args.input_device:
            d.read()
        elif args.input_file:
            d.update(**json.load(args.input_file))

        d.update(**parser_get_config(args))
        sys.stdout.write(d.infotext(show_status = False))

        if args.output_device:
            d.write(ignore_freq_limits = args.ignore_freq_limits)
        elif args.output_file:
            json.dump(d.asdict(ignore_freq_limits = args.ignore_freq_limits),
                      args.output_file, indent = 2)
            
    except GPSDOConfigurationException as e:
        sys.stdout.write("Parameter error:\n")
        sys.stdout.write(e.errortext())


def command_pll(args):
    sys.stdout.write(GPSDO().plltext())



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


def parser_add_input(p, required = False):
    p.add_argument(
        '-i', '--input-file',
        required = required,
        dest = 'input_file',
        metavar = 'FILE',
        type = argparse.FileType('r'),
        help = "Input configuration file")


def parser_add_multiinput(p):
    parser_multiinput = p.add_argument_group(
        title = "Input options")

    parser_multiinput = parser_multiinput.add_mutually_exclusive_group()

    parser_add_input(parser_multiinput)
    
    parser_multiinput.add_argument(
        '-I', '--input-device',
        dest = 'input_device',
        action = 'store_true',
        help = "Read configuration from device")


def parser_add_output(p, required = False):
    p.add_argument(
        '-o', '--output-file',
        required = required,
        dest = 'output_file',
        metavar = 'FILE',
        type = argparse.FileType('w'),
        help = "Output configuration file")


def parser_add_multioutput(p):
    parser_multioutput = p.add_argument_group(
        title = "Output options")

    parser_add_output(parser_multioutput)
    
    parser_multioutput.add_argument(
        '-O', '--output-device',
        dest = 'output_device',
        action = 'store_true',
        help = "Write configuration to device")


def parser_add_config(p):
    parser_config = p.add_argument_group(
        title = "Configuration")

    parser_config.add_argument(
        '--fin',
        dest = 'fin',
        metavar = 'HZ',
        type = int,
        help = "GPS reference frequency")

    parser_config.add_argument(
        '--n3',
        dest = 'n3',
        metavar = 'N',
        type = int,
        help = "Input divider factor")

    parser_config.add_argument(
        '--n2-hs',
        dest = 'n2_hs',
        metavar = 'N',
        type = int,
        help = "Feedback divider factor (high speed)")

    parser_config.add_argument(
        '--n2-ls',
        dest = 'n2_ls',
        metavar = 'N',
        type = int,
        help = "Feedback divider factor (low speed)")

    parser_config.add_argument(
        '--n1-hs',
        dest = 'n1_hs',
        metavar = 'N',
        type = int,
        help = "Output divider factor (high speed)")

    parser_config.add_argument(
        '--nc1-ls',
        dest = 'nc1_ls',
        metavar = 'N',
        type = int,
        help = "Output 1 divider factor (low speed)")

    parser_config.add_argument(
        '--nc2-ls',
        dest = 'nc2_ls',
        metavar = 'N',
        type = int,
        help = "Output 2 divider factor (low speed)")

    parser_config.add_argument(
        '--skew',
        dest = 'skew',
        metavar = 'N',
        type = int,
        help = "Output 2 clock skew")

    parser_config.add_argument(
        '--bw',
        dest = 'bw',
        metavar = 'MODE',
        type = int,
        help = "Bandwith mode")

    parser_config.add_argument(
        '--enable-out1',
        dest = 'out1',
        action = 'store_const',
        const = True,
        help = "Enable output 1")

    parser_config.add_argument(
        '--disable-out1',
        dest = 'out1',
        action = 'store_const',
        const = False,
        help = "Disable output 1")

    parser_config.add_argument(
        '--enable-out2',
        dest = 'out2',
        action = 'store_const',
        const = True,
        help = "Enable output 1")

    parser_config.add_argument(
        '--disable-out2',
        dest = 'out2',
        action = 'store_const',
        const = False,
        help = "Disable output 1")

    parser_config.add_argument(
        '--level',
        dest = 'level',
        metavar = 'CURRENT',
        choices = [ 8, 16, 24, 32 ],
        help = "Output drive level in mA")


def parser_add_pretend(p):
    p.add_argument(
        '-p', '--pretend',
        dest = 'pretend',
        action = 'store_true',
        help = "Don't modify device configuration")


def parser_add_show_status(p):
    p.add_argument(
        '-S', '--show-status',
        dest = 'show_status',
        action = 'store_true',
        help = "Show device status")


def parser_add_show_freq(p):
    p.add_argument(
        '-F', '--show-freq',
        dest = 'show_freq',
        action = 'store_true',
        help = "Show frequency plan")


def parser_add_ignore_freq_limits(p):
    p.add_argument(
        '--ignore-freq-limits',
        action = 'store_true',
        help = "Ignore frequency limits specified in the datasheet")


def parser_get_config(args):
    result = {}
    for attr in [ 'fin', 'n3', 'n2_hs', 'n2_ls', 'n1_hs', 'nc1_ls', 'nc2_ls', 'skew', 'bw', 'out1', 'out2' ]:
        result[attr] = getattr(args, attr, None)

    level = getattr(args, 'level', None)
    if level is not None:
        result['level'] = GPSDO.LEVEL_VALUE[level]

    return result


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


parser_status = subparsers.add_parser(
    'status',
    aliases = [ 's' ],
    help = "Show lock status of a device")

parser_add_device(parser_status)
parser_status.set_defaults(func = command_status)


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
parser_add_pretend(parser_modify)
parser_add_show_status(parser_modify)
parser_add_show_freq(parser_modify)
parser_add_config(parser_modify)
parser_add_ignore_freq_limits(parser_modify)
parser_modify.set_defaults(func = command_modify)


parser_backup = subparsers.add_parser(
    'backup',
    aliases = [ 'b' ],
    help = "Save configuration of a device")

parser_add_device(parser_backup)
parser_add_show_status(parser_backup)
parser_add_show_freq(parser_backup)
parser_add_ignore_freq_limits(parser_backup)
parser_add_output(parser_backup, required = True)
parser_backup.set_defaults(func = command_backup)


parser_restore = subparsers.add_parser(
    'restore',
    aliases = [ 'r' ],
    help = "Restore configuration of a device")

parser_add_device(parser_restore)
parser_add_pretend(parser_restore)
parser_add_show_freq(parser_restore)
parser_add_ignore_freq_limits(parser_restore)
parser_add_input(parser_restore, required = True)
parser_restore.set_defaults(func = command_restore)


parser_identify = subparsers.add_parser(
    'identify',
    aliases = [ 'i' ],
    help = "Identify output channel of a device")

parser_add_device(parser_identify)

parser_identify_output = parser_identify.add_mutually_exclusive_group(required = True)

parser_identify_output.add_argument(
    '--off',
    dest = 'out',
    action = 'store_const',
    const = 0,
    help = "Disable Identification")

parser_identify_output.add_argument(
    '--out1',
    dest = 'out',
    action = 'store_const',
    const = GPSDODevice.OUTPUT1,
    help = "Channel 1")

parser_identify_output.add_argument(
    '--out2',
    dest = 'out',
    action = 'store_const',
    const = GPSDODevice.OUTPUT2,
    help = "Channel 2")

parser_identify.set_defaults(func = command_identify)


parser_analyze = subparsers.add_parser(
    'analyze',
    aliases = [ 'a' ],
    help = "Analyze a configuration")

parser_add_device(parser_analyze)
parser_add_multiinput(parser_analyze)
parser_add_multioutput(parser_analyze)
parser_add_config(parser_analyze)
parser_add_ignore_freq_limits(parser_analyze)
parser_analyze.set_defaults(func = command_analyze)


parser_pll = subparsers.add_parser(
    'pll',
    aliases = [ 'p' ],
    help = "Show PLL diagram")

parser_add_config(parser_pll)
parser_pll.set_defaults(func = command_pll)



#
# Here we go.
#

if __name__ == '__main__':
    args = parser.parse_args()
    if 'func' in args:
        args.func(args)
    else:
        parser.print_help()
