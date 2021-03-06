#!/usr/bin/env python
#
# @author: Gunnar Schaefer

import re
import os
import glob
import time
import shutil
import signal
import logging
import argparse
import datetime

import nimsutil
import nimsdata

log = logging.getLogger('pfilereaper')


class PFileReaper(object):

    def __init__(self, id_, pat_id, discard_ids, data_path, reap_path, sort_path, datetime_file, sleep_time):
        super(PFileReaper, self).__init__()
        self.id_ = id_
        self.pat_id = pat_id
        self.discard_ids = discard_ids
        self.data_glob = os.path.join(data_path, 'P?????.7')
        self.reap_stage = nimsutil.make_joined_path(reap_path)
        self.sort_stage = nimsutil.make_joined_path(sort_path)
        self.datetime_file = datetime_file
        self.sleep_time = sleep_time

        self.current_file_timestamp = nimsutil.get_reference_datetime(self.datetime_file)
        self.monitored_files = {}
        self.alive = True

        # delete any files left behind from a previous run
        for item in os.listdir(self.reap_stage):
            if item.startswith(self.id_):
                shutil.rmtree(os.path.join(self.reap_stage, item))
        for item in os.listdir(self.sort_stage):
            if item.startswith('.' + self.id_):
                shutil.rmtree(os.path.join(self.sort_stage, item))

    def halt(self):
        self.alive = False

    def run(self):
        while self.alive:
            try:
                reap_files = [ReapPFile(p, self) for p in glob.glob(self.data_glob)]
                if not reap_files:
                    raise Warning('No matching files found (or error while checking for files)')
            except (OSError, Warning) as e:
                log.warning(e)
            else:
                reap_files = sorted(filter(lambda f: f.mod_time >= self.current_file_timestamp, reap_files), key=lambda f: f.mod_time)
                for rf in reap_files:
                    if rf.path in self.monitored_files:
                        mf = self.monitored_files[rf.path]
                        if mf.needs_reaping and rf.size == mf.size:
                            rf.reap()
                            if not rf.needs_reaping:
                                nimsutil.update_reference_datetime(self.datetime_file, rf.mod_time)
                                self.current_file_timestamp = rf.mod_time
                        elif mf.needs_reaping:
                            log.info('Monitoring  %s' % rf)
                        elif rf.size == mf.size:
                            rf.needs_reaping = False
                    else:
                        log.info('Discovered  %s' % rf)
                self.monitored_files = dict(zip([rf.path for rf in reap_files], reap_files))
            finally:
                time.sleep(self.sleep_time)


class ReapPFile(object):

    def __init__(self, path, reaper):
        self.path = path
        self.basename = os.path.basename(path)
        self.reaper = reaper
        self.pat_id = None
        self.size = os.path.getsize(path)
        self.mod_time = datetime.datetime.fromtimestamp(os.path.getmtime(path))
        self.needs_reaping = True
        self.pfile = None

    def __repr__(self):
        return '<ReapPFile %s, %d, %s, %s>' % (self.basename, self.size, self.mod_time, self.needs_reaping)

    def __str__(self):
        info = ' (%s) %s_%s_%s' % (self.pat_id, self.pfile.exam_no, self.pfile.series_no, self.pfile.acq_no) if self.pat_id else ''
        return '%s [%s]%s' % (self.basename, nimsutil.hrsize(self.size), info)

    def reap(self):
        try:
            log.info('Inspecting  %s' % self)
            self.pfile = nimsdata.nimsraw.NIMSPFile(self.path)
        except nimsdata.nimsraw.NIMSPFileError as e:
            self.needs_reaping = False
            log.warning('Skipping    %s (%s)' % (self, str(e)))
            return
        else:
            self.pat_id = self.pfile.patient_id
            stage_dir = '%s_%s' % (self.reaper.id_, datetime.datetime.now().strftime('%s.%f'))
            reap_path = nimsutil.make_joined_path(self.reaper.reap_stage, stage_dir)
        if self.pat_id.strip('/').lower() in reaper.discard_ids:
            self.needs_reaping = False
            log.info('Discarding  %s' % self)
            return
        if self.reaper.pat_id and not re.match(self.reaper.pat_id.replace('*','.*'), self.pat_id):
            self.needs_reaping = False
            log.info('Ignoring    %s' % self)
            return

        try:
            log.info('Reaping     %s' % self)
            shutil.copy2(self.path, reap_path)
            for fp in glob.glob(self.path + '_' + self.pfile.series_uid + '_*'):
                log.info('Reaping     %s to %s' % (os.path.basename(fp), os.path.join(reap_path, '_' + self.basename + '_' + fp.rsplit('_', 1)[-1])))
                shutil.copy2(fp, os.path.join(reap_path, '_' + self.basename + '_' + fp.rsplit('_', 1)[-1]))
        except KeyboardInterrupt:
            shutil.rmtree(reap_path)
            raise
        except (shutil.Error, IOError):
            log.warning('Error while reaping %s' % self)
        else:
            log.info('Compressing %s' % self)
            nimsutil.gzip_inplace(os.path.join(reap_path, self.basename), 0o644)
            shutil.move(reap_path, os.path.join(self.reaper.sort_stage, '.' + stage_dir))
            os.rename(os.path.join(self.reaper.sort_stage, '.' + stage_dir), os.path.join(self.reaper.sort_stage, stage_dir))
            self.needs_reaping = False
            log.info('Reaped      %s' % self)


class ArgumentParser(argparse.ArgumentParser):

    def __init__(self):
        super(ArgumentParser, self).__init__()
        self.add_argument('reap_path', help='path to reaping stage')
        self.add_argument('sort_path', help='path to sorting stage')
        self.add_argument('data_path', help='path to data source')
        self.add_argument('-p', '--patid', help='glob for patient IDs to reap (default: "*")')
        self.add_argument('-d', '--discard', default='discard', help='space-separated list of Patient IDs to discard')
        self.add_argument('-s', '--sleeptime', type=int, default=30, help='time to sleep before checking for new data')
        self.add_argument('-f', '--logfile', help='path to log file')
        self.add_argument('-l', '--loglevel', default='info', help='log level (default: info)')
        self.add_argument('-q', '--quiet', action='store_true', default=False, help='disable console logging')


if __name__ == '__main__':
    args = ArgumentParser().parse_args()

    reaper_id = args.data_path.strip('/').replace('/', '_')
    nimsutil.configure_log(args.logfile, not args.quiet, args.loglevel)
    datetime_file = os.path.join(os.path.dirname(__file__), '.%s.datetime' % reaper_id)

    reaper = PFileReaper(reaper_id, args.patid, args.discard.split(), args.data_path, args.reap_path, args.sort_path, datetime_file, args.sleeptime)

    def term_handler(signum, stack):
        reaper.halt()
        log.info('Received SIGTERM - shutting down...')
    signal.signal(signal.SIGTERM, term_handler)

    reaper.run()
    log.warning('Process halted')
