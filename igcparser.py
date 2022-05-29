# Copyright 2021 Alan Sparrow
#
# This file is part of IGCVis
#
# IGCVis is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Navplot is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with IGCVis.  If not, see <http://www.gnu.org/licenses/>.

import logging
import re
import sys
from datetime import datetime, timedelta, timezone
from io import StringIO

import numpy as np

A_REC_RE = "A(\w{3})(\w{3})"
H_DATE_REC_RE = "HFDTE[A-Za-z]?:?(\d{6})"
I_REC_RE = "I(\d{2})(.*)"
B_REC_RE = "B(\d{2})(\d{2})(\d{2})(\d{2})(\d{5})([NS])(\d{3})(\d{5})([EW])A(\d{5})(\d{5})"

IGC_TLA = {
    'siu': 'i8',
    'fxa': 'i8'
}

def parse_igc(igc_file):
    lines = igc_file.readlines()

    # A record
    arec = [x for x in lines if x[0] == "A"][0]

    # H records
    header = {'id': arec[1:7]}

    hrec = [x for x in lines if x[0] == "H"]
    for rec in hrec:
        key = rec[2:5].lower()
        if ":" in rec:
            header[key] = rec.split(":")[1].strip()
        else:
            header[key] = rec[5:-1]

    # Header dte record is UTC date of first fix
    dte_str = header['dte'].split(",")[0][:6]
    dte = datetime.strptime(dte_str, "%d%m%y")
    dte_timestamp = dte.replace(tzinfo=timezone.utc).timestamp()

    # I record
    irec = [x for x in lines if x[0] == "I"][0]

    # Get number of additions
    m = re.match(I_REC_RE, irec)
    n_add = int(m.group(1))

    # Modified I record RE match additions
    irec_re = "I\d{2}" + "(\d{2})(\d{2})([A-Z]{3})" * n_add
    m = re.match(irec_re, irec)

    # Base RE and in/out dtypes
    brec_re = B_REC_RE
    in_types = [('hour', 'i8'), ('min', 'i8'), ('sec', 'i8'),
                ('lat_deg', 'i8'), ('lat_min', 'i8'), ('ns', "S1"),
                ('lon_deg', 'i8'), ('lon_min', 'i8'), ('ew', "S1"),
                ('alt', 'i8'), ('alt_gps', 'i8')]
    out_types = [('utc', 'i8'),
                 ('lat', 'f8'), ('lon', 'f8'),
                 ('alt', 'i8'), ('alt_gps', 'i8')]

    # Additions
    add_types = []
    for n in range(n_add):
        add_id = m.group(n * 3 + 3).lower()
        add_len = int(m.group(n * 3 + 2)) - int(m.group(n * 3 + 1)) + 1
        add_type = IGC_TLA.get(add_id, "a%d" % add_len)

        brec_re += "([A-Z0-9\-]{%d})" % add_len
        add_types.append((add_id, add_type))

    # B records
    brec = [x for x in lines if x[0] == "B"]
    igc = np.fromregex(StringIO("\n".join(brec)), brec_re, in_types + add_types)

    data = np.zeros(igc.shape[0], dtype=out_types + add_types)

    # UTC times
    secs = igc['hour'] * 3600 + igc['min'] * 60 + igc['sec']
    data['utc'] = dte_timestamp + np.unwrap(secs, period=3600*24)

    # Latitude/longitude
    lat = igc['lat_deg'] + igc['lat_min'] / 60000
    lon = igc['lon_deg'] + igc['lon_min'] / 60000

    ones = np.ones(len(lon))
    data['lat'] = lat * np.where(igc['ns'] == b"N", ones, -ones)
    data['lon'] = lon * np.where(igc['ew'] == b"E", ones, -ones)

    data['alt'] = igc['alt']
    data['alt_gps'] = igc['alt_gps']

    for id, dtype in add_types:
        data[id] = igc[id]

    # Bug in some loggers - remove duplicate time samples
    u, idx = np.unique(data['utc'], return_index=True)
    data = data[idx]

    # SeeYou data
    rec = [x for x in lines if x.startswith("LCU::HPCIDCOMPETITIONID")]
    if (rec):
        header['cucid'] = rec[0].split(":")[-1].strip()

    rec = [x for x in lines if x.startswith("LCU::HPPLTPILOT")]
    if (rec):
        header['cuplt'] = rec[0].split(":")[-1].strip()

    return header, data

if __name__ == "__main__":
    import argparse
    import matplotlib.pyplot as plt
    from matplotlib.dates import DateFormatter

    parser = argparse.ArgumentParser()
    parser.add_argument('igc_file', type=argparse.FileType('r', errors='ignore'))
    parser.add_argument('--gps', action="store_true", help='GPS altitude')
    parser.add_argument('--delta', action="store_true", help='Pressure/GPS delta')
    parser.add_argument('--utcoffset', type=int, help='UTC offset (hours)')
    args = parser.parse_args()

    header, igc = parse_igc(args.igc_file)
    print(header)

    if args.gps:
        data = igc['alt_gps']
    elif args.delta:
        data = igc['alt_gps'] - igc['alt']
    else:
        data = igc['alt']

    # Make timezone
    if args.utcoffset is None:
        tz = None
    else:
        tz = timezone(timedelta(hours=args.utcoffset))

    # Convert UTC to naive datetime
    tim = [datetime.fromtimestamp(t, tz=tz).replace(tzinfo=None) for t in igc['utc']]

    formatter = DateFormatter('%H:%M')

    fig, ax = plt.subplots()
    plt.plot(tim, data)
    ax.xaxis.set_major_formatter(formatter)
    plt.show()
