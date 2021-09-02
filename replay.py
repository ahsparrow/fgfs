import json
import socket
import sys
import time
import xdrlib

import numpy as np

class Replay:
    def __init__(self, logs, tdelta, aircraft, port):
        self.logs = logs
        self.tdelta = tdelta
        self.port = port

        if aircraft == 'asg29':
            self.model = 'Aircraft/ASG29/Models/asg29.xml'
        elif aircraft == 'spitfire':
            self.model = 'Aircraft/Spitfire/Models/spitfire_model.xml'
        elif aircraft == 'lego':
            self.model = 'Aircraft/ogel/Models/SinglePiston.xml'
        else:
            self.model = 'Aircraft/DG-101G/Models/DG-101G.xml'

        self.log_len = len(logs[0]['data'])

    def replay(self, n, freeze=False):
        for log in self.logs:
            x, y, z, orix, oriy, oriz, vx, vy, vz = log['data'][n]
            if freeze:
                vx, vy, vz = (0, 0, 0)

            self.send_msg(log['id'], x, y, z, orix, oriy, oriz, vx, vy, vz)

    def send_msg(self, id, x, y, z, orix, oriy, oriz, vx, vy, vz):
        model = bytes(self.model, 'utf-8')
        model += bytearray(96 - len(model))

        # Not really sure what value this should be, but this seems to work
        lag = self.tdelta

        # Pack XDR data
        packer = xdrlib.Packer()

        utc_secs = time.time() % (24 * 3600)
        packer.pack_double(utc_secs)
        packer.pack_double(lag)

        packer.pack_double(x)
        packer.pack_double(y)
        packer.pack_double(z)

        packer.pack_float(orix)
        packer.pack_float(oriy)
        packer.pack_float(oriz)

        packer.pack_float(vx)
        packer.pack_float(vy)
        packer.pack_float(vz)

        # Angular velocity
        packer.pack_float(0)
        packer.pack_float(0)
        packer.pack_float(0)

        # Linear acceleration
        packer.pack_float(0)
        packer.pack_float(0)
        packer.pack_float(0)

        # Angular acceleration
        packer.pack_float(0)
        packer.pack_float(0)
        packer.pack_float(0)

        data = model + packer.get_buffer() + bytearray(4)

        # Make header
        idb = bytes(id[:8], 'ascii')
        hdr = b"FGFS" + \
              bytearray([0, 1, 0, 1,
                         0, 0, 0, 7,
                         0, 0, 0, len(data)+32,
                         0, 0, 0, 0,
                         0, 0, 0, 0]) + idb + bytearray(8 - len(idb))
        msg = hdr + data

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(msg, ("127.0.0.1", self.port))

#----------------------------------------------------------------------

# Calculate minimum distance between two logs
def min_distance(data1, data2):
    xyz1 = np.array([(x[0], x[1], x[2]) for x in data1])
    xyz2 = np.array([(x[0], x[1], x[2]) for x in data2])

    dist = np.linalg.norm(xyz1 - xyz2, axis=1)
    return np.min(dist)

# Replay log data
def find_logs(id, logs, dist):
    # Find log data
    ref_log = None
    for log in logs:
        if log['id'] == id:
            ref_log = log
            break

    if ref_log is None:
        print("Can't find log for " + id)
        sys.exit()

    replay_logs = [ref_log]

    # Find close encounters
    for log in logs:
        log_id = log['id']
        if log_id != id:
            mdist = min_distance(ref_log['data'], log['data'])
            if mdist <= dist:
                print("Adding log " + log_id + ", min distance %d" % mdist)
                replay_logs.append(log)

    return replay_logs

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('file', type=argparse.FileType('r'),
            help='JSON data file')
    parser.add_argument('id', nargs='?', help='id to replay')
    parser.add_argument('--dist', '-d', type=int, default=0,
            help='add if within distance (m)')
    parser.add_argument('--port', '-p', type=int, default=5124,
            help='FG port number')
    parser.add_argument('--list', '-l', action='store_true',
            help='print list of IDs in file')
    parser.add_argument('--aircraft', '-a', choices=['dg101', 'asg29', 'spitfire', 'lego'],
            default='asg29', help='aircraft model')
    args = parser.parse_args()

    data = json.load(args.file)
    if args.list:
        print(", ".join(data['ids']))
        sys.exit(0)

    tdelta = data['tdelta']

    replay_logs = find_logs(args.id, data['logs'], args.dist)

    replay = Replay(replay_logs, tdelta, args.aircraft, args.port)
    for i in range(replay.log_size):
        replay.replay(i)
        time.sleep(tdelta)
