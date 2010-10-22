#!/usr/bin/python
# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

'''A module containing kernel handler class used by SAFT.'''

import re

TMP_FILE_NAME = 'kernel_header_dump'
MAIN_STORAGE_DEVICE = '/dev/sda'

    # Types of kernel modifications.
KERNEL_BODY_MOD = 1
KERNEL_VERSION_MOD = 2


class KernelHandlerError(Exception):
    pass


class KernelHandler(object):
    '''An object to provide ChromeOS kernel related actions.

    Mostly it allows to corrupt and restore a particular kernel partition
    (designated by the partition name, A or B.
    '''

    # This value is used to alter contents of a byte in the appropriate kernel
    # image. First added to corrupt the image, then subtracted to restore the
    # image.
    DELTA = 1

    def __init__(self):
        self.chros_if = None
        self.dump_file_name = None
        self.partition_map = {}

    def _get_version(self, device):
        '''Get version of the kernel hosted on the passed in partition.'''
        # 16 K should be enough to include headers and keys
        data = self.chros_if.read_partition(device, 0x4000)
        return self.chros_if.retrieve_body_version(data)

    def _get_partition_map(self):
        '''Scan `cgpt show <device> output to find kernel devices.'''
        kernel_partitions = re.compile('KERN-([AB])')
        disk_map = self.chros_if.run_shell_command_get_output(
            'cgpt show %s' % MAIN_STORAGE_DEVICE)

        for line in disk_map:
            matched_line = kernel_partitions.search(line)
            if not matched_line:
                continue
            label = matched_line.group(1)
            part_info = {}
            device = MAIN_STORAGE_DEVICE + line.split()[2]
            part_info['device'] = device
            part_info['version'] = self._get_version(device)
            self.partition_map[label] = part_info

    def _modify_kernel(self, section,
                       delta,
                       modification_type=KERNEL_BODY_MOD):
        '''Modify kernel image on a disk partition.

        This method supports two types of kernel modification. KERNEL_BODY_MOD
        just adds the value of delta to the first byte of the kernel blob.
        This might leave the kernel corrupted (as required by the test).

        The second type, KERNEL_VERSION_MOD - will use 'delta' as the new
        version number, it will put it in the kernel header, and then will
        resign the kernel blob.
        '''
        dev = self.partition_map[section]['device']
        cmd_template = 'dd if=%s of=%s bs=4M count=1'
        self.chros_if.run_shell_command(cmd_template % (
                dev, self.dump_file_name))
        bfile = open(self.dump_file_name, 'r')
        data = list(bfile.read())
        bfile.close()
        if modification_type == KERNEL_BODY_MOD:
            data[0] = '%c' % ((ord(data[0]) + delta) % 0x100)
            dumpf = open(self.dump_file_name, 'w')
            dumpf.write(''.join(data))
            dumpf.close()
            kernel_to_write = self.dump_file_name
        elif modification_type == KERNEL_VERSION_MOD:
            new_version = delta
            kernel_to_write = self.dump_file_name + '.new'
            self.chros_if.run_shell_command(
                'vbutil_kernel --repack %s --version %d '
                '--signprivate %s --oldblob %s' % (
                    kernel_to_write, new_version,
                    'kernel_data_key.vbprivk', self.dump_file_name))
        else:
            return  # Unsupported mode, ignore.
        self.chros_if.run_shell_command(cmd_template % (kernel_to_write, dev))

    def corrupt_kernel(self, section):
        '''Corrupt a kernel section (add DELTA to the first byte).'''
        self._modify_kernel(section.upper(), self.DELTA)

    def restore_kernel(self, section):
        '''Restore the previously corrupted kernel.'''
        self._modify_kernel(section.upper(), -self.DELTA)

    def get_version(self, section):
        '''Return version read from this section blob's header.'''
        return self.partition_map[section.upper()]['version']

    def set_version(self, section, version):
        '''Set version of this kernel blob and re-sign it.'''
        if version < 0:
            raise KernelHandlerError('Bad version value %d' % version)
        self._modify_kernel(section.upper(), version, KERNEL_VERSION_MOD)

    def init (self, chros_if):
        '''Initialize the kernel handler object.

        Input argument is a ChromeOS interface object reference.
        '''
        self.chros_if = chros_if
        self.dump_file_name = chros_if.state_dir_file(TMP_FILE_NAME)
        self._get_partition_map()
