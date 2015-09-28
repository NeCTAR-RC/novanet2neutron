""" Helper methods to manage network devices, bridges/taps etc. mainly pulled
from neutron linuxbridge manager and nova linux_net
"""

import ConfigParser
import os
from oslo_concurrency import processutils


CONF = ConfigParser.ConfigParser()

TAP_DEVICE_PREFIX = 'tap'
BRIDGE_NAME_PREFIX = "brq"
BRIDGE_FS = "/sys/devices/virtual/net/"
BRIDGE_NAME_PLACEHOLDER = "bridge_name"
BRIDGE_INTERFACES_FS = BRIDGE_FS + BRIDGE_NAME_PLACEHOLDER + "/brif/"


def get_neutron_bridge_name(network_id):
    return BRIDGE_NAME_PREFIX + network_id[0:11]


def get_neutron_tap_device_name(interface_id):
    return TAP_DEVICE_PREFIX + interface_id[0:11]


def get_nova_vnet_name(index):
    return "vnet%s" % index


def get_interfaces_on_bridge(bridge_name):
    if device_exists(bridge_name):
        bridge_interface_path = BRIDGE_INTERFACES_FS.replace(
            BRIDGE_NAME_PLACEHOLDER, bridge_name)
        return os.listdir(bridge_interface_path)
    else:
        return []


def device_exists(device):
    """Check if ethernet device exists."""
    return os.path.exists('/sys/class/net/%s' % device)


def add_dev_to_bridge(bridge, dev):
    if device_exists(dev) and device_exists(bridge):
        try:
            print "Running Cmd: brctl addif %s %s" % (bridge, dev)
            processutils.execute('brctl', 'addif', bridge, dev,
                                 run_as_root=True,
                                 check_exit_code=[0, 2, 254])
        except processutils.ProcessExecutionError:
            print "ERROR adding %s to %s" % (dev, bridge)


def rm_dev_from_bridge(bridge, dev):
    if device_exists(dev) and device_exists(bridge):
        try:
            print "Running Cmd: brctl delif %s %s" % (bridge, dev)
            processutils.execute('brctl', 'delif', bridge, dev,
                                 run_as_root=True,
                                 check_exit_code=[0, 2, 254])
        except processutils.ProcessExecutionError:
            print "ERROR adding %s to %s" % (dev, bridge)


def net_dev_up(dev):
    if device_exists(dev):
        try:
            print "Running Cmd: ip link set %s up" % dev
            processutils.execute('ip', 'link', 'set', dev, 'up',
                                 run_as_root=True,
                                 check_exit_code=[0, 2, 254])
        except processutils.ProcessExecutionError:
            print "ERROR setting up %s" % dev


def net_dev_down(dev):
    if device_exists(dev):
        try:
            print "Running Cmd: ip link set %s down" % dev
            processutils.execute('ip', 'link', 'set', dev, 'down',
                                 run_as_root=True,
                                 check_exit_code=[0, 2, 254])
        except processutils.ProcessExecutionError:
            print "ERROR setting down %s" % dev


def rename_net_dev(old, new):
    """Rename a network device only if it exists."""
    if device_exists(new):
        print "ERROR Rename: new name %s already exists" % new
        return
    if device_exists(old):
        try:
            net_dev_down(old)
            print "Running Cmd: ip link set %s name %s" % (old, new)
            processutils.execute('ip', 'link', 'set', old, 'name', new,
                                 run_as_root=True,
                                 check_exit_code=[0, 2, 254])
            net_dev_up(new)
        except processutils.ProcessExecutionError:
            print "ERROR renaming "
    else:
        print "ERROR Rename: old name %s doesn't exist" % old
