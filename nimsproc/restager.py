#!/usr/bin/env python
#
# @author:  Gunnar Schaefer

import os
import time
import shlex
import shutil
import signal
import logging
import argparse
import subprocess

import nimsutil

log = logging.getLogger('restager')


class Restager(object):
    def __init__(self, source_stage, data_host, reap_stage, sort_stage, sleep_time):
        super(Restager, self).__init__()
        self.source_stage = source_stage
        self.sleep_time = sleep_time
        self.alive = True

        self.scp_cmd = 'rsync -a %%s %s:%s' % (data_host, reap_stage)
        self.move_cmd = 'ssh %s \'mv %s/%%s %s\'' % (data_host, reap_stage, sort_stage)
        self.setup_cmd = 'ssh %s \'mkdir -p %s %s; rm -rf %s/*\'' % (data_host, reap_stage, sort_stage, reap_stage)

    def halt(self):
        self.alive = False

    def run(self):
        try:
            subprocess.check_call(shlex.split(self.setup_cmd))
        except subprocess.CalledProcessError:
            self.alive = False
            log.error('Cannot set up remote staging area')

        while self.alive:
            stage_contents = [os.path.join(self.source_stage, sc) for sc in os.listdir(self.source_stage)]
            if stage_contents:
                item_path = min(stage_contents, key=os.path.getmtime)
                try:
                    log.info('Restaging %s' % os.path.basename(item_path))
                    subprocess.check_call(shlex.split(self.scp_cmd % item_path))
                    subprocess.check_call(shlex.split(self.move_cmd % os.path.basename(item_path)))
                except subprocess.CalledProcessError:
                    log.info('Failed to restage %s' % os.path.basename(item_path))
                else:
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                    else:
                        os.remove(item_path)
                    log.info('Restaged  %s' % os.path.basename(item_path))
            else:
                log.debug('Waiting for work...')
                time.sleep(self.sleep_time)


class ArgumentParser(argparse.ArgumentParser):
    def __init__(self):
        super(ArgumentParser, self).__init__()
        self.add_argument('source_stage', help='path to source staging area')
        self.add_argument('data_host', help='username@hostname of data destination')
        self.add_argument('remote_stage', help='path to destination staging area')
        self.add_argument('-s', '--sleeptime', type=int, default=30, help='time to sleep before checking for new data')
        self.add_argument('-f', '--logfile', help='path to log file')
        self.add_argument('-l', '--loglevel', default='info', help='log level (default: info)')
        self.add_argument('-q', '--quiet', action='store_true', default=False, help='disable console logging')


if __name__ == "__main__":
    args = ArgumentParser().parse_args()

    nimsutil.configure_log(args.logfile, not args.quiet, args.loglevel)
    source_stage = nimsutil.make_joined_path(args.source_stage, 'sort')
    reap_stage = nimsutil.make_joined_path(args.remote_stage, 'reap')
    sort_stage = nimsutil.make_joined_path(args.remote_stage, 'sort')

    restager = Restager(source_stage, args.data_host, reap_stage, sort_stage, args.sleeptime)

    def term_handler(signum, stack):
        restager.halt()
        log.info('Received SIGTERM - shutting down...')
    signal.signal(signal.SIGTERM, term_handler)

    restager.run()
    log.warning('Process halted')
