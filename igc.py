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

# Caculate speed from 1-D array of positions
def speed(x, td, tavg):
    v = np.diff(x, append=x[-1:]) / td
    vs = boxcar(v, tavg / td)
    return vs

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
def calibrate_altitude(alt_pressure, alt_gps):
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

    return alt, avg_errors

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

    return t, x1, y1, z1

# Calculate flight dynamics, heading, roll, etc.
def dynamics(x, y, z, tdelta, wind_speed, wind_dir):
    wind_speed = wind_speed * 1852 / 3600
    wind_dir = np.radians(wind_dir)

    # Correct for wind velocity
    n = len(x)
    wind_x = np.arange(n) * wind_speed * tdelta * np.sin(wind_dir)
    wind_y = np.arange(n) * wind_speed * tdelta * np.cos(wind_dir)
    xw = x + wind_x
    yw = y + wind_y

    # Calculate heading
    xdelta = np.diff(xw, append=xw[-1:])
    ydelta = np.diff(yw, append=yw[-1:])
    heading = np.degrees(np.arctan2(xdelta, ydelta))

    unwrapped_heading = np.unwrap(np.radians(heading))
    av_unwrapped_heading = boxcar(unwrapped_heading, 4 / tdelta)

    # Calculate speed
    speed = np.sqrt(xdelta ** 2  + ydelta ** 2) / tdelta
    speed = boxcar(speed, 5 / tdelta)

    # Bank angle
    omega = np.diff(unwrapped_heading, append=unwrapped_heading[-1:]) / tdelta
    theta = np.degrees(np.arctan(omega * speed / 9.81))

    av_theta = boxcar(theta, 5 / tdelta)

    # Pitch angle
    zdelta = np.diff(z, append=z[-1:])
    pitch = np.degrees(zdelta / (speed * tdelta))
    pitch = boxcar(pitch, 2 / tdelta)

    return xw, yw, np.mod(np.degrees(av_unwrapped_heading), 360), av_theta, pitch 

