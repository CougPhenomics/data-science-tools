import psycopg2
import psycopg2.extras
import argparse
import json
import os
import sys
import zipfile
import paramiko
import numpy as np
import cv2
import datetime
import fnmatch
from tqdm import tqdm

class options():
    def __init__(self):
        self.config = "cppcserver-remote.config"
        self.exper = "GoldStandard2_RGB"
        self.outdir = "testing"
        self.date1 = "2019-08-01"
        self.date2 = "2019-08-02"
        self.force = True
        self.camera = None

args = options()
