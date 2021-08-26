import argparse
import os.path
import re

from bs4 import BeautifulSoup
import requests

def get_logs(comp, day, log_dir):
    url = 'https://www.soaringspot.com/en_gb/%s/results/%s/daily' % (args.comp, args.day)
    req = requests.get(url)

    soup = BeautifulSoup(req.text, "html.parser")
    links = soup.find_all('a', attrs={'data-toggle': 'popover'})

    for link in links:
        cn = link.string.strip()
        print("Downloading " + cn)

        data = link['data-content']
        log_id = re.search("\d{4}-\d{10}", data).group()

        log_url = 'https://www.soaringspot.com/en_gb/download-contest-flight/%s?dl=1' % log_id
        log_req = requests.get(log_url)

        log_path = os.path.join(log_dir, cn + ".igc")
        with open(log_path, "wt") as f:
            f.write(log_req.text)

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("comp", help='Competition part of Soaring Spot URL')
    parser.add_argument("day", help='Class/day part of Soaring Spot URL')
    parser.add_argument("log_dir", help="Directory to store IGC files")
    args = parser.parse_args()

    get_logs(args.comp, args.day, args.log_dir)
