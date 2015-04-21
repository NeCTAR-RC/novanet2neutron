#!/usr/bin/env python

import argparse
import ConfigParser
import MySQLdb

from novanet2neutron import common


CONF = ConfigParser.ConfigParser()

CREATE_TABLE_SQL = """
CREATE TABLE `network_migration_info` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `uuid` varchar(36) DEFAULT NULL,
  `network_name` varchar(255) DEFAULT NULL,
  `availability_zone` varchar(255) DEFAULT NULL,
  `ip_v4` varchar(39) DEFAULT NULL,
  `ip_v6` varchar(39) DEFAULT NULL,
  `host` varchar(255) DEFAULT NULL,
  `mac_address` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`id`)
 ) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8;
"""


def add_instance(cursor, instance):
    if instance.status == 'ERROR':
        return
    zone = getattr(instance, 'OS-EXT-AZ:availability_zone', None)
    host = getattr(instance, 'OS-EXT-SRV-ATTR:host', None)

    data = {
        'uuid': instance.id,
        'host': host,
        'availability_zone': zone,
        'ip_v6': None,
        'ip_v4': None,
    }

    for network_name, addresses in instance.addresses.items():
        if not addresses:
            continue
        data['network_name'] = network_name

        for a in addresses:
            data['mac_address'] = a.get('OS-EXT-IPS-MAC:mac_addr')
            if a['version'] == 4:
                ip_v4 = a.get('addr')
                data['ip_v4'] = ip_v4
            elif a['version'] == 6:
                ip_v6 = a.get('addr')
                data['ip_v6'] = ip_v6

        sql = """INSERT INTO network_migration_info set
        uuid='%(uuid)s', network_name='%(network_name)s',
        availability_zone='%(availability_zone)s',
        ip_v4='%(ip_v4)s', ip_v6='%(ip_v6)s', host='%(host)s',
        mac_address='%(mac_address)s'""" % data
        cursor.execute(sql)
        cursor.connection.commit()


def collect_args():
    parser = argparse.ArgumentParser(description='novanet2neutron.')

    parser.add_argument('-c', '--config', action='store',
                        default='novanet2neutron.conf', help="Config file")
    return parser.parse_args()


def main():
    args = collect_args()
    common.load_config(CONF, args.config)

    novac = common.get_nova_client()
    instances = common.all_servers(novac)

    conn = MySQLdb.connect(
        host=CONF.get('db', 'host'),
        user=CONF.get('db', 'user'),
        passwd=CONF.get('db', 'password'),
        db=CONF.get('db', 'name'))
    cursor = conn.cursor()
    try:
        cursor.execute('DROP TABLE network_migration_info')
    except:
        pass
    cursor.execute(CREATE_TABLE_SQL)
    conn.commit()
    count = 0
    for i in instances:
        add_instance(cursor, i)
        if count > 50:
            conn.commit()
            count = 0
        else:
            count += 1
    conn.commit()
    cursor.close()
    conn.close()


if __name__ == "__main__":
    main()
