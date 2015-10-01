import sqlite3
import netifaces

import common
import utils


CREATE_TABLE_SQL = """
CREATE TABLE `network_migration_info` (
  `uuid` varchar(36) DEFAULT NULL,
  `network_name` varchar(255) DEFAULT NULL,
  `availability_zone` varchar(255) DEFAULT NULL,
  `ip_v4` varchar(39) DEFAULT NULL,
  `ip_v6` varchar(39) DEFAULT NULL,
  `host` varchar(255) DEFAULT NULL,
  `mac_address` varchar(255) DEFAULT NULL,
  `status` varchar(255) DEFAULT NULL,
  `task_state` varchar(255) DEFAULT NULL,
  `port_id` varchar(36) DEFAULT NULL,
  `nova_tap_name` varchar(255) DEFAULT NULL,
  `neutron_tap_name` varchar(255) DEFAULT NULL
 );
"""

INSERT_SQL = """
INSERT INTO `network_migration_info` VALUES (
  '%(uuid)s',
  '%(network_name)s',
  '%(availability_zone)s',
  '%(ip_v4)s',
  '%(ip_v6)s',
  '%(host)s',
  '%(mac_address)s',
  '%(status)s',
  '%(task_state)s',
  '%(port_id)s',
  '%(nova_tap_name)s',
  '%(neutron_tap_name)s')
;
"""


def populate_offline_cache(source_cursor, nclient, instances, networks):

    conn = sqlite3.connect('offline-cache.db')
    cursor = conn.cursor()
    try:
        cursor.execute("DROP TABLE network_migration_info")
        print "Dropped previous offline cache"
    except:
        pass
    print "Creating offline cache"
    cursor.execute(CREATE_TABLE_SQL)

    for i in instances:
        for n in networks:
            data = common.get_db_data(source_cursor, i, n['nova_name'])
            if data is None:
                continue
            neutron_tap, port_id = get_new_tap(nclient, i, n)
            data['neutron_tap_name'] = neutron_tap
            data['port_id'] = port_id
            mac = data['mac_address'].replace('fa:', 'fe:', 1)
            nova_tap = get_devname(mac)
            data['nova_tap_name'] = nova_tap
            sql = INSERT_SQL % data
            cursor.execute(sql)
            conn.commit()
    conn.commit()
    print "Offline cache created"
    return cursor


def get_new_tap(neutron_client, instance, network):
    ports = neutron_client.list_ports(device_id=instance.id,
                                      network_id=network['id'])
    if not ports['ports']:
        print "%s ERROR no neutron port found, cannot migrate" % instance.id
        return None
    if len(ports['ports']) != 1:
        print "%s ERROR multiple neutron ports found, cannot migrate" % instance.id
        return None
    port_id = ports['ports'][0].get('id')
    new_tap = utils.get_neutron_tap_device_name(port_id)
    return new_tap, port_id


def get_devname(mac_address):
    for device in netifaces.interfaces():
        try:
            mac = netifaces.ifaddresses(device)[netifaces.AF_LINK][0]['addr']
        except:
            continue
        if mac == mac_address:
            return device
    print "Failed to find device for %s" % mac_address
    return None
