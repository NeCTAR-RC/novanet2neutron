#!/usr/bin/env python

import argparse
import ConfigParser
import MySQLdb

from novanet2neutron import common

CONF = ConfigParser.ConfigParser()


def add_port(neutronc, host, ip_address, network_id, subnet_id):
    body_value = {
        "port": {
            "name": "nova-network reserved for %s" % host,
            "fixed_ips": [
                {
                    "subnet_id": subnet_id,
                    "ip_address": ip_address,
                }],
            "network_id": network_id,
        }
    }
    try:
        port = neutronc.create_port(body=body_value)['port']
        print "added port %s for %s ID: %s" % (ip_address, host, port['id'])
    except Exception, e:
        print e


def add_ports(cursor, neutronc, fixed_ips):
    for ip in fixed_ips:
        network_id = ip['network_id']
        cidr = get_network_cidr(cursor, network_id)
        host = ip['host']
        address = ip['address']

        subnet = neutronc.list_subnets(cidr=cidr)['subnets'][0]

        network_id = subnet['network_id']
        subnet_id = subnet['id']

        add_port(neutronc, host, address, network_id, subnet_id)


def get_network_cidr(cursor, network_id):
    sql = "SELECT * from networks WHERE id = '%s'" % network_id
    cursor.execute(sql)
    network = cursor.fetchone()

    return network['cidr']


def get_hyperisor_fixed_ips(cursor):
    sql = "SELECT * from fixed_ips WHERE host IS NOT NULL"
    cursor.execute(sql)
    fixed_ips = cursor.fetchall()
    return fixed_ips


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
    fixed_ips = get_hyperisor_fixed_ips(cursor)

    url = CONF.get('creds', 'auth_url')
    username = CONF.get('creds', 'username')
    password = CONF.get('creds', 'password')
    tenant = CONF.get('creds', 'tenant_name')

    neutronc = common.get_neutron_client(username=username,
                                         password=password,
                                         tenant=tenant,
                                         url=url)
    add_ports(cursor, neutronc, fixed_ips)
    cursor.close()
    conn.close()
if __name__ == "__main__":
    main()
