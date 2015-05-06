===============================================
Scripts to migrate from nova-network -> Neutron
===============================================

These scripts will migrate an install a simple flat nova-network setup to Neutron.
It will use linuxbridge plugin.

"simple" and "flat" meaning one or more shared provider networks (neutron speak)

It currently only supports 1 or 2 networks per compute node but it should be simple to extend.
It assumes that the control pane will be unavailable during the migration. 
Instance traffic will be largely unaffected with a ~5 second downtime while renaming
the interfaces. The nova-api-metadata service will also be stopped during the migration

Steps to migrate
================

Prep
----

* Setup neutron DB and server
* Collect all you network information
* install neutron ml2 linuxdridge on compute nodes. (ensure stopped)

Gameday
-------
* Lock down APIs - Ensure users can't access nova and neutron or anything that would in turn touch nova or neutron (eg. trove). Compute nodes and control infrastructure will still need access.
* Run the 'generate_network_data.py' script. This will collect all network data and store in a DB table. This is required as duing the migration the network information coming from the API may disapear as instance info_cache network_info changes.
* Enable Neutron endpoints in keystone
* Change compute driver on all your hypervisors to fake.FakeDriver and setup necessary configs in nova to use neutron
* Stop nova-network and nova-api-metadata everywhere
* Run 'migrate-control.py' script, this will create the networks and subnets in neutron and also create all the ports. It will then simulate interface attaches (This is where the fake driver comes in)
* Run migrate-secgroup.py script
* Start network node services neutron-*(metadata, dhcp, linuxbridge)
* install neutron ml2 linuxdridge on compute nodes. (ensure stopped)
* Run 'migrate-compute.py' script - This will rename the interfaces the way neutron expects them to be.
* Set compute driver back to libvirt and start neutron-linux-bridge
* Clear iptables and restart nova-compute and neutron-linuxbridge
* (May be needed) Add rule for metadata iptables -t nat -I PREROUTING -d 169.254.169.254/32 -p tcp -m tcp --dport 80 -j DNAT --to-destination <metadata_host>:80 - this may be needed depending on how your metadata works
* killall nova dnsmasq process


Gotchas
=======

* You can't migrate instances in suspended state, this is because the libvirt xml imformation is stored in binary in the .save file
* IPv6 hasn't been tested yet.