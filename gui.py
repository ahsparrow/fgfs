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

import json
import sys
from datetime import time

import numpy as np
import tkinter as tk

import replay

# Update time, in ms
TDELTA = 100

class App(tk.Frame):
    def __init__(self, replay, start_time, master=None):
        super().__init__(master)

        self.replay = replay
        self.start_seconds = (start_time.hour * 3600 +
                              start_time.minute * 60 +
                              start_time.second)

        self.log_len = replay.log_len
        self.tdelta = replay.tdelta

        self._root().title("Replay")

        self.pack(fill=tk.BOTH, expand=True)
        self.create_widgets()

        self.paused = False
        self.drag = False

        self.count = 0
        self.tick()

    def create_widgets(self):
        self.scale = tk.Scale(self, from_=0, to=(self.log_len - 1),
                showvalue=False, orient=tk.HORIZONTAL, command=self.scale)
        self.scale.bind('<Button-1>', self.button_press)
        self.scale.bind('<ButtonRelease-1>', self.button_release)
        self.scale.grid(row=0, column=0, columnspan=5, padx=(8, 0), pady=(8, 0),
                sticky=tk.E+tk.W)

        self.label_var = tk.StringVar()
        self.label_var.set('0:00')
        label = tk.Label(self, textvariable=self.label_var)
        label.grid(row=0, column=5, padx=(8, 8), pady=(8, 0))

        button = tk.Button(self, text='<<', command=self.transport(-10))
        button.grid(row=1, column=0, padx=(8, 0), pady=8)

        button = tk.Button(self, text='<', command=self.transport(-1),
                repeatdelay=1000, repeatinterval=100)
        button.grid(row=1, column=1, padx=(4, 0), pady=8)

        self.pause_button_text = tk.StringVar()
        button = tk.Button(self, text='Stop/Go', command=self.pause)
        button.grid(row=1, column=2, padx=(8, 0), pady=8)

        button = tk.Button(self, text='>', command=self.transport(1),
                repeatdelay=1000, repeatinterval=100)
        button.grid(row=1, column=3, padx=(8, 0), pady=8)

        button = tk.Button(self, text='>>', command=self.transport(10))
        button.grid(row=1, column=4, padx=(4, 0), pady=8)

        button = tk.Button(self, text='Quit', command=self.master.destroy)
        button.grid(row=1, column=5, padx=(8, 8), pady=8)

    def transport(self, value):
        def skip():
            self.paused = True

            self.count += value
            if self.count < 0:
                self.count = 0
            elif self.count >= self.log_len:
                self.count = self.log_len - 1
        return skip

    def scale(self, value):
        if self.drag:
            self.count = int(value)

    def pause(self):
        self.paused = not self.paused

    def button_press(self, evt):
        self.drag = True

    def button_release(self, evt):
        self.drag = False

    def tick(self):
        if self.drag or self.paused:
            freeze = True
        else:
            if self.count < (self.log_len - 1):
                self.count += 1
            freeze = False

        self.scale.set(self.count)

        secs = self.start_seconds + (self.count * self.tdelta)
        hour, minute = divmod(secs, 3600)
        minute, second = divmod(minute, 60)
        self.label_var.set("%02d:%02d:%04.1f" % (hour, minute, second))

        self.replay.replay(self.count, freeze=freeze)
        self.after(TDELTA, self.tick)

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('id', help='id to replay')
    parser.add_argument('file', type=argparse.FileType('r'),
            help='JSON data file')
    parser.add_argument('--dist', '-d', type=int, default=0,
            help='add others if within distance (m)')
    parser.add_argument('--port', '-p', type=int, default=5124,
            help='FG port number')
    parser.add_argument('--aircraft', '-a', choices=['dg101', 'asg29', 'spitfire', 'lego'],
            default='asg29', help='aircraft model')
    parser.add_argument('--info', action='store_true',
            help='print log info')
    args = parser.parse_args()

    data = json.load(args.file)

    print("Start: %s" % data['start'])
    print("Logs: %s" % ", ".join(data['ids']))
    if args.info:
        sys.exit(0)

    tdelta = data['tdelta']
    start_time = time.fromisoformat(data['start'].split("T")[1])

    replay_logs = replay.find_logs(args.id, data['logs'], args.dist)
    replay = replay.Replay(replay_logs, tdelta, args.aircraft, args.port)

    app = App(replay, start_time)
    app.mainloop()
