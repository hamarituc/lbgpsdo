Leo Bodnar GPSDO Configuration Utility
======================================

This is a command line utility to calculate, analyze, retriev and update the
configuration of the Leo Bodnar GPSDO device.

Installation
------------

You ne the python `hid` package. See https://github.com/apmorton/pyhidapi for
more information.

If the package is not provided by your linux distribution you can create an
virtual python environment.

```sh
$ virtualenv DIRECTORY
$ source DIRECTORY/bin/activate
$ pip install -r requirements.txt
```

Setup
-----

To access the device you need access permission to the device file. Placing
the file `99-lbgpsdo.rules` under `/etc/udev/rules.d` will ensure that your
systems `usb` group has access to the device.

Usage
-----

The tool provides a set of subcommands for different tasks. Call it without
specifying a subcommand to get a list of the available commands.

```
$ ./lbgpsdo.py 
usage: lbgpsdo.py [-h]
                  {list,l,status,s,detail,d,modify,m,backup,b,restore,r,identify,i,analyze,a,pll,p}
                  ...

positional arguments:
  {list,l,status,s,detail,d,modify,m,backup,b,restore,r,identify,i,analyze,a,pll,p}
    list (l)            List devices
    status (s)          Show lock status of a device
    detail (d)          Show details of a device
    modify (m)          Change configuration of a single device
    backup (b)          Save configuration of a device
    restore (r)         Restore configuration of a device
    identify (i)        Identify output channel of a device
    analyze (a)         Analyze a configuration
    pll (p)             Show PLL diagram

optional arguments:
  -h, --help            show this help message and exit
```

### Listing devices

The `list` command shows all connected devices.

```
$ ./lbgpsdo.py list
1dd2:2210 /dev/hidraw0      G42610  GPS Reference Clock
```

The list contains the USB vendor and product IDs as well as the device path,
the serial number of the GPSDO and the product string.

### Showing status

The `status` command shows the status of all connected devices.

```
$ ./lbgpsdo.py status
G42610    /dev/hidraw0: SAT unlocked  PLL locked    Loss: 1
```

The output shows the lock status of satellite receiver and the PLL and contains
the number of instants where the satellite connection was lost.

If more than one device is present, you can limit the list to specific devices
by applying a filter based on the serial number or the device path.

```
$ ./lbgpsdo.py status -s G42610
G42610    /dev/hidraw0: SAT unlocked  PLL locked    Loss: 1
```

### Showing configuration

The `detail` command shows the configuration of a device. If more than one
device is connected, you must select the proper device by it's serial number
or device path.

```
$ ./lbgpsdo.py detail
Device information
------------------
VID, PID:     0x2210:0x1dd2
Device:       /dev/hidraw0
Product:      GPS Reference Clock
Manufacturer: Leo Bodnar
S/N:          G42610
Firmware:     1.18

Device status
-------------
Loss count:   1
SAT lock:     unlocked
PLL lock:     LOCKED

Output settings
---------------
Output 1:     25.000 MHz
Output 2:     10.000 MHz
Phase:         0.000 °
Drive level:       8 mA

PLL settings
------------
N3     =       3  Input divider factor
N2_HS  =      10  Feedback divider factor
N2_LS  =     270
N1_HS  =       9  Output common divider factor
NC1_LS =      24  Output 1 divider factor
NC2_LS =      60  Output 2 divider factor
SKEW   =      +0  Clock skew
BWSEL  =      15  Loop bandwith code

Frequency plan
--------------
fin    =                         6000000 Hz     GPS reference frequency
f3     =    2000000/   1 Hz =    2000000 Hz     Phase detector frequency
fosc   = 5400000000/   1 Hz = 5400000000 Hz     Oscillator frequency
fout1  =   25000000/   1 Hz =   25000000 Hz     Output 1 frequency
fout2  =   10000000/   1 Hz =   10000000 Hz     Output 2 frequency
phase  =          0/   1 s  =      0.000 s      Phase offset output 1 --> 2
       =          0/   1 °  =      0.000 °      Phase angle w.r.t output 2
pres   =          5/   3 ns =      1.667 ns     Phase offset resolution
       =          6/   1 °  =      6.000 °
```

### Modify configuration

You can alter the configuration of a device by means of the `modify` command.
Specifiy the parameters to alter on the command line.

This command will set the Output channel 1 divider to 12 and disable Output
channel 2.

```
$ ./lbgpsdo.py modify --nc1-ls 12 --disable-out2
```

To see the available parameters use the help feature of the command.

```
Configuration:
  --fin HZ              GPS reference frequency
  --n3 N                Input divider factor
  --n2-hs N             Feedback divider factor (high speed)
  --n2-ls N             Feedback divider factor (low speed)
  --n1-hs N             Output divider factor (high speed)
  --nc1-ls N            Output 1 divider factor (low speed)
  --nc2-ls N            Output 2 divider factor (low speed)
  --skew N              Output 2 clock skew
  --bw MODE             Bandwith mode
  --enable-out1         Enable output 1
  --disable-out1        Disable output 1
  --enable-out2         Enable output 1
  --disable-out2        Disable output 1
  --level CURRENT       Output drive level in mA
```

To check the effect of your changes, append the `--show-freq` parameter. By
appending `--pretend` the changes are only shown, but not uploaded to the
device.

If you specify an invalid configuration an error is written out.

```
$ ./lbgpsdo.py modify --nc1-ls 13 --disable-out2
Parameter error:
nc1_ls: Output 1 divider NC1_LS must be 1 or even.
```

### Backup and restore configuration

You can save the configuration of a device by means of the `backup` command.

```
$ ./lbgpsdo.py backup --output save.json
```

It will produce a JSON file containing the configuration.

```
{
  "out1": true,
  "out2": false,
  "level": 0,
  "fin": 6000000,
  "n3": 3,
  "n2_hs": 10,
  "n2_ls": 270,
  "n1_hs": 9,
  "nc1_ls": 12,
  "nc2_ls": 60,
  "skew": 0,
  "bw": 15
}
```

You can even modifiy the file yourself with a text editor.

To restore the configuration use the `restore` command.

```
$ ./lbgpsdo.py restore --input save.json
```

### Identify channels

The `identify` command let the channels LED blink. The channel must be enabled.

```
$ ./lbgpsdo.py identify --out1
```

Resume to normal operation by using the `--off` parameter.

```
$ ./lbgpsdo.py identify --off
```

### Analyzing configurations

Even without a GPSDO device connected you can prepare a configuration by means
of the `analyze` command. The command computes the frequency plan base on the
specified parameters. You don't have to start with a whole parameter set.
Values which cannot be computed will be left undefined.

```
$ ./lbgpsdo.py analyze --fin 5000000 --n3 5 --n2-hs 11 --n2-ls 450
Output settings
---------------
Output 1:
Output 2:
Phase:
Drive level:       8 mA

PLL settings
------------
N3     =       5  Input divider factor
N2_HS  =      11  Feedback divider factor
N2_LS  =     450
N1_HS  =     ---  Output common divider factor
NC1_LS =     ---  Output 1 divider factor
NC2_LS =     ---  Output 2 divider factor
SKEW   =      +0  Clock skew
BWSEL  =      15  Loop bandwith code

Frequency plan
--------------
fin    =                         5000000 Hz     GPS reference frequency
f3     =    1000000/   1 Hz =    1000000 Hz     Phase detector frequency
fosc   = 4950000000/   1 Hz = 4950000000 Hz     Oscillator frequency
fout1  =                --- =           ---  !! Output 1 frequency
fout2  =                --- =           ---  !! Output 2 frequency
phase  =                --- =           ---     Phase offset output 1 --> 2
       =                --- =           ---     Phase angle w.r.t output 2
pres   =                --- =           ---     Phase offset resolution
       =                --- =           ---

Errors
------
n1_hs:  Output common divider N1_HS undefined.
nc1_ls: Output 1 divider NC1_LS undefined.
nc2_ls: Output 2 divider NC2_LS undefined.
fout1:  Output 1 frequency undefined.
fout2:  Output 2 frequency undefined.
```

You can load backup file with the `--input-file` parameter to initialize the
parameters before changes are applied. Although the command is designed to work
without a device, you can load the configuration directly from a device using
the `--input-device` parameter.

You can export the computed frequency plan to a file or a device by using the
`--output-file` or `--output-device` parameters. It is only possible to read
an write to the same device.

The `analyze` command is thus a more general version of the `modify`, `backup`
and `restore` commands.

### Miscellaneous

The `pll` command shows a diagram of the PLL together with the contraints of
the intermediate frequencies. It output just static text an doesn't acces
any device.

```
$ ./lbgpsdo.py pll
  fin          f3   +-------+                                       fout1  
------> ÷ N3 -----> |       |   fosc                 +-> ÷ NC1_LS -------->
                    |  PLL  | --------+--> ÷ N1_HS --|                     
          +-------> |       |         |              +-> ÷ NC2_LS -------->
          |         +-------+         |                             fout2  
          |                           |                                    
          +-- ÷ N2_LS <--- ÷ N2_HS <--+                                    

fin   =                                   10.000 kHz ...  16.000 MHz
f3    = fin / N3                       =  10.000 kHz ...   2.000 MHz
fosc  = fin * (N2_LS * N2_HS) / N3     =   4.850 GHz ...   5.670 GHz
fout1 = fosc / (N1_HS * NC1_LS)        = 450.000 Hz  ... 808.000 MHz
fout2 = fosc / (N1_HS * NC2_LS)        = 450.000 Hz  ... 808.000 MHz
```

Frequency Limit
---------------

The datasheet specifies limits for the intermediate frequenciens. However it
was reported, the clock performs well even outside this limits. The parameter
`--ignore-freq-limits` skips the internal checks of these limits whenever a
configuration is written to the device or exported into a file (commands
`modify`, `backup`, `restore`, `analyze`). The limit violations are still shown
in the diagnostic output.

Future plans
------------

It is planned to extend the tool by a `compute` command which determins all
saettings from specified output frequencies.

Acknowledgements
----------------

Thanks to the Leo Bodnar techical support for providing details information.
See https://github.com/simontheu/lb-gps-linux for an other configuration
utility.
