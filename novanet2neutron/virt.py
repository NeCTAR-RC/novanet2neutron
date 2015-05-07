""" Helper methods to manage libvirt related stuff, mainly pulled from nova
"""

import ConfigParser
import libvirt
from lxml import etree
import time

CONF = ConfigParser.ConfigParser()


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
