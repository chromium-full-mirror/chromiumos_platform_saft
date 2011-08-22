#!/bin/bash
# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# A simple script to run SAFT unit tests and possibly start the SAFT.
#
# The only expected optional command line parameter is the name of the file
# containing the firmware image to test. If the parameter is not provided,
# SAFT is not started, just the unit tests get to run.

rm -rf /tmp/tmp*/var/.fw_test 2> /dev/null
umount -d /tmp/tmp* 2> /dev/null

TMPD_PATTERN='/tmp/tmp_saft.XXXX'

set -e
this_prog=$(readlink -f $0)
if [ -n "$1" ]; then
    new_firmware=$(readlink -f $1)
else
    new_firmware=''
fi

case "$(crossystem arch)" in
  (x86)
    ARCH='x86'
    DEFAULT_FLASH_DEVICE="${FLASH_DEVICE:=sdb}"
    DEFAULT_DISK_DEVICE="${DISK_DEVICE:=sda}"
    ;;
  (arm)
    ARCH='arm'
    DEFAULT_FLASH_DEVICE="${FLASH_DEVICE:=sda}"
    DEFAULT_DISK_DEVICE="${DISK_DEVICE:=mmcblk0}"
    ;;
  (*)
    echo "Failed to auto detect architecture."
    exit 1
    ;;
esac

join_part() {
  local dev="$1"
  local part="$2"
  # Test the dev is mmcblk0 or sda style
  if [ "${dev}" != "${dev/mmcblk/}" ]; then
    echo "$1p$2"
  else
    echo "$1$2"
  fi
}

# This hack has been borrowed from src/scripts/common.sh
enable_rw_mount() {
  local rootfs="$1"
  local ro_compat_offset=$((0x464 + 3))  # Set 'highest' byte
  printf '\000' |
    sudo dd of="$rootfs" seek=${ro_compat_offset} \
            conv=notrunc count=1 bs=1
}

target_hosted () {
  python -c 'import chromeos_interface;\
crosif = chromeos_interface.ChromeOSInterface(True);\
print "%d" % crosif.target_hosted()'
}

on_removable_device() {
    # Check if the code is running off a removable device or not.
    # Print '1' or '0' respectively on the console.
    rootd=$(df "${this_prog}" | grep '^/dev' | awk '{ print $1 }')
    if [ "${rootd}" == '/dev/root' ]; then
        rootd=$(rootdev -s)
    fi
    blockd=$(echo "${rootd}" | sed 's/.*\(sd[a-z]\+\|mmcblk[0-9]\+\).*/\1/')
    removable="/sys/block/"${blockd}"/removable"
    if [ -f "${removable}" ]; then
        cat "${removable}"
    else
        echo '0'
    fi
}

move_to_removable_device() {
    # Move ourselves to the removable device and run off it.

    # For simplicity, hardcode the removable device to be
    # $DEFAULT_FLASH_DEVICE which was assigned at the beginning.
    flash_device="${DEFAULT_FLASH_DEVICE}"
    fname="/sys/block/${flash_device}/removable"

    # Confirm SDB exists and is indeed removable.
    if [ ! -f  "${fname}" -o "$(cat $fname)" != "1" ]; then
        echo "No removable device found"
        exit 1
    fi

    # Determine userland partition on the removable device.
    dev_num=$(cgpt show /dev/"${flash_device}" | \
        grep '"ROOT-A"' | awk '{ print $3 }')
    if [ -z "${dev_num}" ]; then
        echo "/dev/${flash_device} does not contain a valid file system"
        exit 1
    fi
    flash_root_partition=$(join_part "/dev/${flash_device}" "${dev_num}")

    enable_rw_mount "${flash_root_partition}"

    # Find its mountpoint, or mount it if not yet mounted.
    mp=$(mount | grep "${flash_root_partition}" | awk '{print $3}')
    if [ "${mp}" == "" ]; then
        mp=$(mktemp -d "${TMPD_PATTERN}")
        mount "${flash_root_partition}" "${mp}"
    else
        mount -o remount,exec "${mp}"
    fi

    # Copy the two directories SAFT test requires to the removable device to
    # the same path we are in on the root device now.
    my_root=$(readlink -f .)
    dest="${mp}${my_root}"
    if [ ! -d "${dest}" ]; then
        mkdir -p "${dest}"
    fi
    cp -rp "${my_root}"/* "${dest}"

    # Start it running off the removable device. We don't expect to come back
    # from this invocation in case this is a full mode SAFT. If this is a
    # unittest run, some post processing can be added after unit tests return.
    echo "starting as ${mp}${this_prog}  ${new_firmware}"
    "${mp}${this_prog}" "${new_firmware}"
}

configure_gpt_settings() {
    # Let's keep it simple for now, partition 2 is the one to boot.
    cgpt add -i 2 -T 5 -P 9 -S 1 "/dev/${DEFAULT_DISK_DEVICE}"
    cgpt add -i 4 -T 5 -P 5 -S 1 "/dev/${DEFAULT_DISK_DEVICE}"
}

run_tests() {
    ./test_chromeos_interface.py
    if [ "$(target_hosted)" == "0" ]; then
        return
    fi
    ./test_flashrom_handler.py "${new_firmware}"
    ./test_saft_utility.py
    ./test_kernel_handler.py
    ./test_cgpt_handler.py
    ./test_tpm_handler.py
    ./test_cgpt_state.py

    if [ -n "${new_firmware}" ]; then
        configure_gpt_settings
        ./saft_utility.py --ima="${new_firmware}"
    fi
}

check_and_set_saft_environment() {
    # Does the other side contain a valid kernel?
    tmpd=$(mktemp -d "${TMPD_PATTERN}")
    this_root=$(rootdev -s)
    this_kern=$(echo "${this_root}" | tr '35' '24')
    other_kern=$(echo "${this_kern}" | tr '24' '42')
    other_kern_file="${tmpd}/kernel"
    dd if="${other_kern}" of="${other_kern_file}"

    if ! vbutil_kernel --verify "${other_kern_file}" > /dev/null 2>&1
    then
        # The "other side" is not valid, let's set it up
        echo "setting up kernel in ${other_kern}"
        dd if="${this_kern}" of="${other_kern}" bs=4M
        other_root=$(echo "${this_root}" | tr '35' '53')
        echo "setting up root fs in ${other_root}"
        dd if="${this_root}" of="${other_root}" bs=4M
    fi

    # Is flash device kernel configured to run with verified root fs?
    flash_kernel_dev=$(join_part "/dev/${DEFAULT_FLASH_DEVICE}" '2')
    dd if="${flash_kernel_dev}" of="${other_kern_file}"
    cmd_line=$(vbutil_kernel --verify "${other_kern_file}" --verbose | tail -1)

    if echo "${cmd_line}" | grep -q 'root=/dev/dm'; then
        echo 'Disabling rootfs verification on the flash device kernel'
        new_cmd_line_file="${tmpd}/cmdline"
        echo "${cmd_line}" | sed '
s/ ro / rw /
s/dm_verity[^ ]\+//g
s|verity /dev/sd%D%P /dev/sd%D%P ||
s| root=/dev/dm-0 | root=/dev/sd%D%P |
s/dm="[^"]\+" //' > "${new_cmd_line_file}"
        vbutil_kernel --repack "${other_kern_file}.new" \
            --config "${new_cmd_line_file}" \
            --signprivate recovery_kernel_data_key.vbprivk \
            --oldblob "${other_kern_file}"
        dd if="${other_kern_file}.new" of="${flash_kernel_dev}" bs=4M
    fi
}

cd $(dirname ${this_prog})
if [ "$(on_removable_device)" == "0" -a "$(target_hosted)" == "1" ]; then
    check_and_set_saft_environment
    move_to_removable_device
    exit 0
fi

run_tests
