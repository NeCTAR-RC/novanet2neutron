#!/usr/bin/env python

import argparse
import ConfigParser
import MySQLdb

from novanet2neutron import common

CONF = ConfigParser.ConfigParser()


def get_instances(cursor):
    sql = "SELECT uuid from instances WHERE deleted = 0"
    cursor.execute(sql)
    instances = cursor.fetchall()
    return instances

def add_system_metadata(cursor, instance):
    sql = """INSERT INTO instance_system_metadata SET created_at=NOW(), 
    instance_uuid='%s', instance_system_metadata.key='nectar_suspend_disabled', 
    value='1', deleted=0""" % instance['uuid']
    cursor.execute(sql)
    cursor.connection.commit()

def collect_args():
    parser = argparse.ArgumentParser(description='novanet2neutron.')

    parser.add_argument('-c', '--config', action='store',
                        default='compute.conf', help="Config file")
    return parser.parse_args()


def main():
    args = collect_args()
    common.load_config(CONF, args.config)

    conn = MySQLdb.connect(
        host=CONF.get('nova_db', 'host'),
        user=CONF.get('nova_db', 'user'),
        passwd=CONF.get('nova_db', 'password'),
        db=CONF.get('nova_db', 'name'))

    cursor = MySQLdb.cursors.DictCursor(conn)
    instances = get_instances(cursor)
    for instance in instances:
        add_system_metadata(cursor, instance)
    conn.commit()
    cursor.close()
    conn.close()
if __name__ == "__main__":
    main()
