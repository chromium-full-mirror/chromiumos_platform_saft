#!/usr/bin/python
# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

'''Unittest wrapper for tpm_handler.py.'''

import os
import shutil
import subprocess
import tempfile
import unittest

import tpm_handler

CONF_FILE_TEMPLATE = '''
# Trousers daemon, which talks to the TPM (or the TPM emulator).

stop on starting halt or starting reboot

pre-start script
    tpmc clear  || logger "tpmc clear:  status $?"
    tpmc enable || logger "tpmc enable: status $?"
    tpmc act    || logger "tpmc act:    status $?"
%s    tpmc block  || logger "tpmc block:  status $?"
%s    tpmc pplock || logger "tpmc pplock: status $?"

  fi
end script

exec /usr/sbin/tcsd
'''

class CrosIfMock(object):
    MOCKED_COMMANDS = {
        'initctl status tcsd': 'tcsd start/running, process 3757',
        'tpmc read 0x1007 0xa': '1 0 1 1 1 0 0 0 0 0',
        'tpmc read 0x1008 0xd': '1 4c 57 52 47 1 2 1 0 0 0 0 0',
        'stop tcsd': 'tcsd stop/waiting',
        'tpmc write 0x1008 0x01 0x4c 0x57 0x52 0x47 0x01 0x00 ' +
        '0x01 0x00 0x00 0x00 0x00 0x00' : '',
        }

    def __init__(self):
        self.last_cmd = None
        self.state_dir = tempfile.mkdtemp()

    def run_shell_command_get_output(self, cmd):
        self.last_cmd = cmd
        return (self.MOCKED_COMMANDS[cmd],)

    def run_shell_command(self, cmd):
        self.last_cmd = cmd
        assert(cmd in self.MOCKED_COMMANDS)

    def state_dir_file(self, file_name):
        return os.path.join(self.state_dir, file_name)

    def __del__(self):
        shutil.rmtree(self.state_dir)

class TestTpmHandler(unittest.TestCase):
    def setUp(self):
        self.tpmh = tpm_handler.TpmHandler()
        self.tpmh.init(CrosIfMock())

    def test_boot_version(self):
         self.assertEqual(self.tpmh.get_fw_version(), 257)

    def test_read_kernel_version(self):
         self.assertEqual(self.tpmh.get_kernel_version(), 513)

    def test_write_kernel_version(self):
        self.tpmh.set_kernel_version(1)

    def test_config_file_handling(self):
        '''Verify that config file gets modified/restored properly.'''
        conf_file, conf_file_name = tempfile.mkstemp()
        os.write(conf_file, CONF_FILE_TEMPLATE % ('', ''))
        os.close(conf_file)
        self.tpmh.enable_write_access(conf_file_name)
        self.assertEqual(open(conf_file_name).read(), CONF_FILE_TEMPLATE % (
                tpm_handler.COMMENT_PATTERN, tpm_handler.COMMENT_PATTERN))
        self.tpmh.disable_write_access(conf_file_name)
        self.assertEqual(open(conf_file_name).read(),
                         CONF_FILE_TEMPLATE % ('', ''))
        os.remove(conf_file_name)

if __name__ == '__main__':
    unittest.main()
