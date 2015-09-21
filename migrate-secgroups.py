#!/usr/bin/env python

import MySQLdb
import uuid
import argparse
import ConfigParser

from novanet2neutron import common

CONF = ConfigParser.ConfigParser()


neutron_group_sql = """
INSERT into securitygroups set tenant_id='%(project_id)s', name='%(name)s', id='%(uuid)s', description='%(description)s'"""

neutron_rule_sql = """
INSERT into securitygrouprules set tenant_id='%(project_id)s', security_group_id='%(security_group_id)s', id='%(uuid)s', remote_group_id='%(group_id)s',
direction='%(direction)s', ethertype='%(ethertype)s', protocol='%(protocol)s', port_range_min='%(from_port)s', port_range_max='%(to_port)s', remote_ip_prefix='%(cidr)s'
"""

neutron_binding_sql = """
INSERT into securitygroupportbindings set port_id='%(port_id)s', security_group_id='%(group_id)s'
"""

neutron_default_group_sql = """
INSERT INTO default_security_group set tenant_id='%(tenant_id)s', security_group_id='%(group_id)s'
"""


def generate_uuid():
    return str(uuid.uuid4())


def execute(cursor, sql):
    sql = sql.replace("'None'", 'NULL')
    print sql
    cursor.execute(sql)


def create_default_mapping(cursor, group_id, tenant_id):
    data = {'group_id': group_id, 'tenant_id': tenant_id}
    execute(cursor, neutron_default_group_sql % data)


def create_default_rules(cursor, group):
    rule = {
        'project_id': group['project_id'],
        'security_group_id': group['uuid'],
        'direction': 'egress',
        'group_id': None,
        'protocol': None,
        'from_port': None,
        'to_port': None,
        'cidr': None,
    }
    for ethertype in ['IPv4', 'IPv6']:
        rule['ethertype'] = ethertype
        rule['uuid'] = generate_uuid()
        execute(cursor, neutron_rule_sql % rule)

    if group['name'] == 'default':
        create_default_mapping(cursor, group['uuid'],
                               group['project_id'])
        rule['direction'] = 'ingress'
        rule['group_id'] = group['uuid']
        for ethertype in ['IPv4', 'IPv6']:
            rule['uuid'] = generate_uuid()
            rule['ethertype'] = ethertype
            execute(cursor, neutron_rule_sql % rule)
    cursor.connection.commit()


def migrate_groups(nova_cursor, neutron_cursor):
    mappings = {}
    nova_cursor.execute("SELECT * from security_groups where deleted = 0")
    groups = nova_cursor.fetchall()
    for group in groups:
        if group['project_id'] is None:
            continue
        group_uuid = generate_uuid()
        group['uuid'] = group_uuid
        mappings[group['id']] = {'uuid': group_uuid,
                                 'project_id': group['project_id']}
        execute(neutron_cursor, neutron_group_sql % group)
        neutron_cursor.connection.commit()
        create_default_rules(neutron_cursor, group)
    return mappings


def migrate_rules(nova_cursor, neutron_cursor, mappings):
    for id, group_data in mappings.items():
        nova_cursor.execute("SELECT * from security_group_rules where deleted = 0 and parent_group_id = %s" % id)
        rules = nova_cursor.fetchall()
        for rule in rules:
            rule['project_id'] = group_data['project_id']
            rule['uuid'] = generate_uuid()
            rule['security_group_id'] = group_data['uuid']
            rule['direction'] = 'ingress'
            rule['ethertype'] = 'IPv4'
            if rule['cidr'] and ':' in rule['cidr']:
                rule['ethertype'] = 'IPv6'
            if rule['group_id']:
                rule['group_id'] = mappings[rule['group_id']]['uuid']

            if rule['to_port'] == -1:
                rule['to_port'] = 'None'
            if rule['from_port'] == -1:
                rule['from_port'] = 'None'
            execute(neutron_cursor, neutron_rule_sql % rule)


def get_ports(neutron_cursor, instance_uuid):
    neutron_cursor.execute("SELECT * from ports where device_id = '%s'" % instance_uuid)
    ports = neutron_cursor.fetchall()
    port_ids = []
    for port in ports:
        port_ids.append(port['id'])
    return port_ids


def migrate_bindings(nova_cursor, neutron_cursor, mappings):
    nova_cursor.execute("SELECT * from security_group_instance_association where deleted = 0")
    nova_bindings = nova_cursor.fetchall()
    for nb in nova_bindings:
        ports = get_ports(neutron_cursor, nb['instance_uuid'])
        binding = {'group_id': mappings[nb['security_group_id']]['uuid']}
        for port in ports:
            binding['port_id'] = port
            execute(neutron_cursor, neutron_binding_sql % binding)
        neutron_cursor.connection.commit()


def delete_neutron_existing(cursor):
    cursor.execute("DELETE from securitygroupportbindings")
    cursor.execute("DELETE from securitygrouprules")
    cursor.execute("DELETE from securitygroups")
    cursor.execute("DELETE from default_security_group")
    cursor.connection.commit()


def collect_args():
    parser = argparse.ArgumentParser(description='novanet2neutron.')

    parser.add_argument('-c', '--config', action='store',
                        default='novanet2neutron.conf', help="Config file")
    return parser.parse_args()


def main():
    args = collect_args()
    common.load_config(CONF, args.config)

    nova_conn = MySQLdb.connect(
        host=CONF.get('db', 'host'),
        user=CONF.get('db', 'user'),
        passwd=CONF.get('db', 'password'),
        db=CONF.get('db', 'name'))

    nova_cursor = MySQLdb.cursors.DictCursor(nova_conn)
    neutron_conn = MySQLdb.connect(
        host=CONF.get('neutron_db', 'host'),
        user=CONF.get('neutron_db', 'user'),
        passwd=CONF.get('neutron_db', 'password'),
        db=CONF.get('neutron_db', 'name'))
    neutron_cursor = MySQLdb.cursors.DictCursor(neutron_conn)
    delete_neutron_existing(neutron_cursor)
    mappings = migrate_groups(nova_cursor, neutron_cursor)
    migrate_rules(nova_cursor, neutron_cursor, mappings)
    neutron_conn.commit()
    migrate_bindings(nova_cursor, neutron_cursor, mappings)
    neutron_conn.commit()
    nova_cursor.close()
    nova_conn.close()
    neutron_cursor.close()
    neutron_conn.close()

if __name__ == "__main__":
    main()
