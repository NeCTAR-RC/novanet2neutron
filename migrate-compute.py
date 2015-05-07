#!/usr/bin/env python

import ConfigParser
import os
import socket
import libvirt
from lxml import etree
import argparse
import time
import MySQLdb
import netifaces

from nova.openstack.common import processutils

from novanet2neutron import common


CONF = ConfigParser.ConfigParser()

TAP_DEVICE_PREFIX = 'tap'
BRIDGE_NAME_PREFIX = "brq"
BRIDGE_FS = "/sys/devices/virtual/net/"
BRIDGE_NAME_PLACEHOLDER = "bridge_name"
BRIDGE_INTERFACES_FS = BRIDGE_FS + BRIDGE_NAME_PLACEHOLDER + "/brif/"


def get_instance_iface(instance, network_name, protocol=4):
    addresses = instance.addresses.get(network_name, None)
    for address in addresses:
        if address.get('version') == protocol:
            return address
    return {}


def get_mac_db(cursor, instance, network_name):
    sql = """SELECT * from network_migration_info where uuid = '%(uuid)s'
    AND network_name = '%(network_name)s'
    """
    cursor.execute(sql % {'uuid': instance.id,
                          'network_name': network_name})
    rows = cursor.fetchall()
    if len(rows) > 1:
        print "ERROR"
    if len(rows) == 0:
        return None
    return rows[0]['mac_address']


def build_devmap():
    mappings = {}
    for device in netifaces.interfaces():
        mac = netifaces.ifaddresses(device)[netifaces.AF_LINK][0]['addr']
        mappings[mac] = device
    return mappings


class NetworkMigration(object):

    def __init__(self, network, neutron_client):
        self.network = network
        self.neutron_client = neutron_client


class NeutronMigration(NetworkMigration):

    tap_prefix = 'vnet'

    def get_old_bridge(self):
        return self.network['bridge']

    def get_new_bridge(self):
        return get_neutron_bridge_name(self.network['id'])

    def get_new_tap(self, instance, index):
        ports = self.neutron_client.list_ports(device_id=instance.id,
                                               network_id=self.network['id'])
        if not ports['ports']:
            print "%s ERROR no neutron port found, cannot migrate" % instance.id
            return None
        if len(ports['ports']) != 1:
            print "%s ERROR multiple neutron ports found, cannot migrate" % instance.id
            return None

        new_tap = get_neutron_tap_device_name(ports['ports'][0].get('id'))
        return new_tap


class NovaMigration(NetworkMigration):

    tap_prefix = 'tap'

    def get_old_bridge(self):
        return get_neutron_bridge_name(self.network['id'])

    def get_new_bridge(self):
        return self.network['bridge']

    def get_new_tap(self, instance, index):
        return get_nova_vnet_name(index)


def migrate_interfaces(noop, migrate_manager, neutronc,
                       cursor, networks, instances):
    errors = False
    device_map = build_devmap()
    tap_index = 0
    for network in networks:
        manager = migrate_manager(network, neutronc)
        old_bridge = manager.get_old_bridge()
        new_bridge = manager.get_new_bridge()
        raw_device = network['device']

        #remove interfaces from bridge
        interfaces = get_interfaces_on_bridge(old_bridge)
        for interface in interfaces:
            if interface != raw_device and interface.startswith(manager.tap_prefix):
                print "removing interface %s from bridge %s" % (interface,
                                                                old_bridge)
                if not noop:
                    rm_dev_from_bridge(old_bridge, interface)
        if not device_exists(new_bridge):
            # Remove pyhsical interfce from bridge
            print "removing %s from %s" % (raw_device, old_bridge)
            if not noop:
                rm_dev_from_bridge(old_bridge, raw_device)
            #rename bridge
            print "Renaming brige %s to %s" % (old_bridge, new_bridge)
            if not noop:
                rename_net_dev(old_bridge, new_bridge)

        interfaces = get_interfaces_on_bridge(new_bridge)
        if raw_device not in interfaces:
            print "Add %s to %s" % (raw_device, new_bridge)
            if not noop:
                add_dev_to_bridge(new_bridge, raw_device)

        for instance in instances:
            mac_address = get_mac_db(cursor, instance, network['nova_name'])
            if not mac_address:
                continue
            if instance.status in ['SHUTOFF', 'SUSPENDED']:
                old_tap = None
            else:
                new_tap = manager.get_new_tap(instance, tap_index)
                tap_index += 1
                if not device_exists(new_tap):
                    #Rename tap
                    mac = mac_address.replace('fa:', 'fe:', 1)
                    old_tap = device_map[mac]
                    print "%s: Rename tap %s to %s" % (instance.id, old_tap, new_tap)
                    if not noop:
                        rename_net_dev(old_tap, new_tap)
                if new_tap not in interfaces:
                    # add interface to bridge
                    print "%s: Add tap %s to bridge %s" % (instance.id,
                                                           new_tap,
                                                           new_bridge)
                    if not noop:
                        add_dev_to_bridge(new_bridge, new_tap)

            if not has_virt_device(instance, new_tap):
                virt_switch_interface(noop, instance, mac_address,
                                      old_bridge, old_tap,
                                      new_bridge, new_tap)
    return errors


def virt_switch_interface(noop, instance, mac_address, old_bridge, old_tap,
                          new_bridge, new_tap):
    conn = libvirt.open()
    virt_name = getattr(instance, 'OS-EXT-SRV-ATTR:instance_name')
    virt_dom = conn.lookupByName(virt_name)

    virt_detach_interface(noop, virt_dom, mac_address, old_bridge, old_tap)
    print "%s: removing xml for %s" % (instance.id, old_tap)
    time.sleep(1)
    virt_attach_interface(noop, virt_dom, mac_address, new_bridge, new_tap)
    print "%s: adding xml for %s" % (instance.id, new_tap)
    conn.close()


def has_virt_device(instance, device):
    conn = libvirt.open()
    virt_name = getattr(instance, 'OS-EXT-SRV-ATTR:instance_name')
    virt_dom = conn.lookupByName(virt_name)
    devices = get_virt_interfaces(virt_dom)
    for d in devices:
        if 'dev' in d and d['dev'] == device:
            return True
    return False


def get_virt_interfaces(virt_dom):
    xml = virt_dom.XMLDesc()
    doc = None
    try:
        doc = etree.fromstring(xml)
    except Exception:
        return []
    interfaces = []
    ret = doc.findall('./devices/interface')
    for node in ret:
        interface = {}
        for child in list(node):
            iface_info = dict(child.attrib)
            interface.update(iface_info)
        interfaces.append(interface)
    return interfaces


def get_interfaces_on_bridge(bridge_name):
    if device_exists(bridge_name):
        bridge_interface_path = BRIDGE_INTERFACES_FS.replace(
            BRIDGE_NAME_PLACEHOLDER, bridge_name)
        return os.listdir(bridge_interface_path)
    else:
        return []


def get_neutron_bridge_name(network_id):
    return BRIDGE_NAME_PREFIX + network_id[0:11]


def get_neutron_tap_device_name(interface_id):
    return TAP_DEVICE_PREFIX + interface_id[0:11]


def get_nova_vnet_name(index):
    return "vnet%s" % index


def get_interface_xml(mac_address, bridge, interface):
    from nova.virt.libvirt import designer
    from nova.virt.libvirt.config import LibvirtConfigGuestInterface
    conf = LibvirtConfigGuestInterface()
    model = 'virtio'
    driver = None
    designer.set_vif_guest_frontend_config(conf, mac_address, model, driver)
    designer.set_vif_host_backend_bridge_config(conf, bridge, interface)
    return conf


def virt_attach_interface(noop, virt_dom, mac_address, bridge, interface):
    flags = libvirt.VIR_DOMAIN_AFFECT_CONFIG
    state = virt_dom.info()[0]
    if state == 1 or state == 3:
        flags |= libvirt.VIR_DOMAIN_AFFECT_LIVE
    cfg = get_interface_xml(mac_address, bridge, interface)
    cfg = cfg.to_xml()
    #print "Adding virt XML %s" % cfg
    if not noop:
        virt_dom.attachDeviceFlags(cfg, flags)


def virt_detach_interface(noop, virt_dom, mac_address, bridge, interface):
    flags = libvirt.VIR_DOMAIN_AFFECT_CONFIG
    state = virt_dom.info()[0]
    if state == 1 or state == 3:
        flags |= libvirt.VIR_DOMAIN_AFFECT_LIVE
    cfg = get_interface_xml(mac_address, bridge, interface)
    cfg = cfg.to_xml()
    #print "Removing virt XML %s" % cfg
    if not noop:
        virt_dom.detachDeviceFlags(cfg, flags)


def device_exists(device):
    """Check if ethernet device exists."""
    return os.path.exists('/sys/class/net/%s' % device)


def add_dev_to_bridge(bridge, dev):
    if device_exists(dev) and device_exists(bridge):
        try:
            processutils.execute('brctl', 'addif', bridge, dev,
                                 run_as_root=True,
                                 check_exit_code=[0, 2, 254])
        except processutils.ProcessExecutionError:
            print "ERROR adding %s to %s" % (dev, bridge)


def rm_dev_from_bridge(bridge, dev):
    if device_exists(dev) and device_exists(bridge):
        try:
            processutils.execute('brctl', 'delif', bridge, dev,
                                 run_as_root=True,
                                 check_exit_code=[0, 2, 254])
        except processutils.ProcessExecutionError:
            print "ERROR adding %s to %s" % (dev, bridge)


def net_dev_up(dev):
    if device_exists(dev):
        try:
            processutils.execute('ip', 'link', 'set', dev, 'up',
                                 run_as_root=True,
                                 check_exit_code=[0, 2, 254])
        except processutils.ProcessExecutionError:
            print "ERROR setting up %s" % dev


def net_dev_down(dev):
    if device_exists(dev):
        try:
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
            processutils.execute('ip', 'link', 'set', old, 'name', new,
                                 run_as_root=True,
                                 check_exit_code=[0, 2, 254])
            net_dev_up(new)
        except processutils.ProcessExecutionError:
            print "ERROR renaming "
    else:
        print "ERROR Rename: old name %s doesn't exist" % old


def collect_args():
    parser = argparse.ArgumentParser(description='novanet2neutron.')

    parser.add_argument('-f', '--for-realsies', action='store_true',
                        default=False, help="Actually do things")
    parser.add_argument('-d', '--direction', action='store',
                        default='neutron', required=True,
                        help="Either migrate to 'nova' or 'neutron'")
    parser.add_argument('-c', '--config', action='store',
                        default='compute.conf', help="Config file")
    return parser.parse_args()


def get_network(neutronc, net_id):
    network = neutronc.list_networks(id=net_id)['networks'][0]
    subnets = neutronc.list_subnets(network_id=network['id'])['subnets']
    for subnet in subnets:
        network['subnet_v%s' % subnet['ip_version']] = subnet['id']
    return network


def main():
    args = collect_args()
    common.load_config(CONF, args.config)
    noop = True
    if args.for_realsies:
        noop = False
    else:
        print "Running migration in noop mode, use -f to actually migrate things"
    direction = args.direction
    conn = MySQLdb.connect(
        host=CONF.get('db', 'host'),
        user=CONF.get('db', 'user'),
        passwd=CONF.get('db', 'password'),
        db=CONF.get('db', 'name'))

    cursor = MySQLdb.cursors.DictCursor(conn)

    host = socket.gethostname()
    novac = common.get_nova_client()
    neutronc = common.get_neutron_client()
    networks = []
    for section in CONF.sections():
        if section.startswith('network_'):
            network_id = CONF.get(section, 'neutron_net_id')
            network = get_network(neutronc, network_id)
            for option in ('device', 'bridge', 'nova_name'):
                network[option] = CONF.get(section, option)
            networks.append(network)

    instances = common.all_servers(novac, host=host)
    if direction == 'neutron':
        manager = NeutronMigration
    elif direction == 'nova':
        manager = NovaMigration
    else:
        print "unknown direction"
    print "Running checks"
    errors = migrate_interfaces(True, manager, neutronc, cursor,
                                networks, instances)
    if not noop and not errors:
        print "running for real"
        migrate_interfaces(False, manager, neutronc,
                           cursor, networks, instances)
    if errors:
        print "Cannot run due to errors"
    cursor.close()
    conn.close()


if __name__ == "__main__":
    main()
