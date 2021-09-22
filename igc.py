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

import numpy as np
from pyproj import Transformer
from scipy.interpolate import splrep, splev

EPSG_WGS84 = 4326
EPSG_XY = 3035

# Apply simple running average
def boxcar(data, n):
    # Filter length must be odd
    n1 = int(n // 2) * 2 + 1

    kernel = np.ones(n1) / n1
    m = n1 // 2

    # Pad data to minimise end effects
    pad = np.ones(m)
    d = np.concatenate((pad * data[0], data, pad * data[-1]))

    out = np.convolve(d, kernel, mode='valid')
    return out

# Caculate velocities from array of XYZ
def speed(xyz, tdelta):
    v = np.diff(xyz, append=xyz[:, -1:]) / tdelta
    vx = boxcar(v[0], 3.0 / tdelta)
    vy = boxcar(v[1], 3.0 / tdelta)
    vz = boxcar(v[2], 3.0 / tdelta)

    return np.stack((vx, vy, vz))

def get_tdelta(utc):
    # Sample interval
    duration = utc[-1] - utc[0]
    delta = duration / (len(utc) - 1)

    return round(delta)

# Convert altitude from ellipsoid to geoid (if necessary)
def check_geoid(alt, elevation, geoid):
    takeoff_alt = np.mean(alt[:10])

    err_geoid = abs(takeoff_alt - elevation)
    err_ellip = abs((takeoff_alt - geoid) - elevation)

    if (err_ellip < err_geoid):
        alt = alt - geoid
    else:
        # IGC loggers should use ellipsoid altitude, but many don't
        logging.warning("geoid reference")

    min_err = min(err_ellip, err_geoid)
    if min_err > 10:
        logging.warning("takeoff elevation error exceeds 10 m: %.1f m" % min_err)

    return alt

# Calculate 'calibrated' pressure altitude
def calibrate_altitude(alt_pressure, alt_gps, errors=False):
    # Calibrate 100m intervals
    bin_size = 100

    # Digitise pressure altitude into 'bin_size' bins
    min_alt = (np.min(alt_pressure) // bin_size) * bin_size
    max_alt = (np.max(alt_pressure) // bin_size + 1) * bin_size
    bins = np.arange(min_alt, max_alt + bin_size, bin_size)
    n_bins = len(bins)

    inds = np.digitize(alt_pressure, bins)

    # Calculate average error for each pressure altitude bin
    error = alt_gps -  alt_pressure
    avg_errors = [np.mean(error[np.where(inds == b)]) for b in range(1, n_bins)]

    # Calculate calibration using simple linear interpolation
    cal = np.interp(alt_pressure, bins[:-1] + bin_size / 2, avg_errors)

    # Correct pressure altitude for GPS 'calibration'
    alt = alt_pressure + cal

    if errors:
        return alt, avg_errors
    else:
        return alt

# Convert to local X/Y coordinates and resample data
def resample_xyz(utc, lat, lon, alt, resample_t):
    # Convert to local x/y coordinates
    transformer = Transformer.from_crs(EPSG_WGS84, EPSG_XY)
    y, x = transformer.transform(lat, lon)

    # Resample using cubic splines
    n = round((utc[-1] - utc[0]) / resample_t) + 1
    t = (np.arange(n) * resample_t) + utc[0]

    x1 = splev(t, splrep(utc, x, s=0), der=0)
    y1 = splev(t, splrep(utc, y, s=0), der=0)
    z1 = splev(t, splrep(utc, alt, s=0), der=0)

    return t, np.stack((x1, y1, z1))

# Calculate flight dynamics, heading, roll, etc.
def dynamics(xyz, tdelta, wind_speed, wind_dir):
    wind_speed = wind_speed * 1852 / 3600
    wind_dir = np.radians(wind_dir)

    x = xyz[0]
    y = xyz[1]
    z = xyz[2]

    # Correct for wind velocity
    n = len(x)
    wind_x = np.arange(n) * wind_speed * tdelta * np.sin(wind_dir)
    wind_y = np.arange(n) * wind_speed * tdelta * np.cos(wind_dir)
    xw = x + wind_x
    yw = y + wind_y

    # Calculate (unwrapped) heading
    xdelta = np.diff(xw, append=xw[-1:])
    ydelta = np.diff(yw, append=yw[-1:])
    heading = np.unwrap(np.arctan2(xdelta, ydelta))

    av_heading = boxcar(heading, 4 / tdelta)

    # Calculate speed
    speed = np.sqrt(xdelta ** 2  + ydelta ** 2) / tdelta
    speed = boxcar(speed, 5 / tdelta)

    # Bank angle
    omega = np.diff(heading, append=heading[-1:]) / tdelta
    bank = np.degrees(np.arctan(omega * speed / 9.81))
    bank = boxcar(bank, 5 / tdelta)

    # Pitch angle
    zdelta = np.diff(z, append=z[-1:])
    pitch = np.degrees(zdelta / (speed * tdelta))
    pitch = boxcar(pitch, 2 / tdelta)

    xyz_out = np.stack((xw, yw, z))
    hrp_out = np.stack((np.mod(np.degrees(av_heading), 360), bank, pitch))

    return xyz_out, hrp_out

