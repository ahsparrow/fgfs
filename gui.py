import json
import sys

import numpy as np
import tkinter as tk

import replay

class App(tk.Frame):
    def __init__(self, replay, master=None):
        super().__init__(master)

        self.replay = replay
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

        secs = self.count * self.tdelta
        self.label_var.set("%d:%04.1f" % (secs // 60, secs % 60))

        self.replay.replay(self.count, freeze=freeze)
        self.after(int(self.tdelta * 1000), self.tick)

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
    parser.add_argument('--aircraft', '-a', choices=['dg101', 'asg29', 'spitfire', 'lego'],
            default='asg29', help='aircraft model')
    args = parser.parse_args()

    data = json.load(args.file)
    tdelta = data['tdelta']

    replay_logs = replay.find_logs(args.id, data['logs'], args.dist)
    replay = replay.Replay(replay_logs, tdelta, args.aircraft, args.port)

    app = App(replay)
    app.mainloop()
