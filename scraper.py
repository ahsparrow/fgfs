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

import argparse
import html
import os.path
import re
import urllib.parse

from bs4 import BeautifulSoup
import requests

def get_logs(url, log_dir):
    req = requests.get(url)

    # Find the download pop-ups
    soup = BeautifulSoup(req.text, "html.parser")
    links = soup.find_all('a', attrs={'data-toggle': 'popover'})

    for link in links:
        cn = link.string.strip()
        print("Downloading " + cn)

        # Extract the download link
        dl_soup = BeautifulSoup(html.unescape(link['data-content']),
                "html.parser")
        href = dl_soup.find(string=re.compile("Download IGC")).parent['href']

        # Get the log file URL
        split_url = urllib.parse.urlsplit(href)
        if split_url.netloc == "":
            split_url = split_url._replace(scheme="https",
                                           netloc="www.soaringspot.com")
        log_url = urllib.parse.urlunsplit(split_url)

        # Download log file
        log_req = requests.get(log_url)

        # Write to file
        log_path = os.path.join(log_dir, cn + ".igc")
        with open(log_path, "wt") as f:
            f.write(log_req.text)

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("url", help='Soaring Spot URL')
    parser.add_argument("log_dir", help="Directory to store IGC files")
    args = parser.parse_args()

    get_logs(args.url, args.log_dir)
