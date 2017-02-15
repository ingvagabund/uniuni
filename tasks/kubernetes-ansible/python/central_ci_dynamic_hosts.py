#!/usr/bin/python

'''
    Ansible dynamic inventory script for central CI
   returns json of provisioned hosts
'''

import json
import os

if "RESOURCE_FILE" in os.environ:
	RESOURCE_FILE = os.environ["RESOURCE_FILE"]
else:
	RESOURCE_FILE = "resources.json"

JSON_DATA = None

# If RESOURCE_FILE is not found in current working directory
# try CI-specific jenkins path
# assumes filename is RESOURCE_FILE in both cases
if not os.path.isfile(RESOURCE_FILE):
    THIS_DIR = os.path.dirname(os.path.abspath(__file__))
    RESOURCE_FILE = THIS_DIR + '/../../' + RESOURCE_FILE
    if not os.path.isfile(RESOURCE_FILE):
        print "Cannot find resource file in current working directory or " \
              "'%s'" % (RESOURCE_FILE)
        exit(1)

JSON_DATA = json.load(open(RESOURCE_FILE))

HOSTS = {'cihosts': {
    'hosts': [],
    'vars': {}}}

OS_HOST = 'openshift_hostname'
OS_PUBLIC_HOST = 'openshift_public_hostname'

if "LOCAL" in os.environ:
    vars = {"ansible_connection": "local"}
else:
    vars = {}

for host in JSON_DATA['resources']:
    if host:
        # Openstack resources
        if 'ip' in host:
            HOSTS['cihosts']['hosts'].append(host['ip'])
            HOSTS[host['name']] = {'hosts': [host['ip']], 'vars': vars}
        # Beaker resources
        if 'system' in host:
            HOSTS['cihosts']['hosts'].append(host['system'])
            HOSTS[host['system']] = {'hosts': [host['system']], 'vars': vars}

        # add metadata
        if 'metadata' in host:
            for key, val in host['metadata'].iteritems():
                if 'ansible-group' in key:
                    for group in val:
                        if group not in HOSTS:
                            HOSTS[group] = {'hosts': [], 'vars': {}}
                            HOSTS[group]['hosts'] = [host['ip']]
                        else:
                            HOSTS[group]['hosts'].append(host['ip'])
                        for key, val in host['metadata'].iteritems():
                            if OS_PUBLIC_HOST not in key and \
                                OS_HOST not in key and \
                                    'ansible-group' not in key and \
                                    'openshift_node_labels' not in key:
                                HOSTS[group]['vars'][key] = val

                # add all vars to the host
                else:
                    if 'openshift_hostname' in key:
                        if 'private_ip' in host:
                            HOSTS[host['name']]['vars'][OS_HOST] \
                                = host['private_ip']
                        if 'ip' in host:
                            HOSTS[host['name']]['vars'][OS_PUBLIC_HOST] \
                                = host['ip']
                        if 'system' in host:
                            HOSTS[host['name']]['vars'][OS_HOST] \
                                = host['system']
                            HOSTS[host['name']]['vars'][OS_PUBLIC_HOST] \
                                = host['system']
                    else:
                        HOSTS[host['name']]['vars'][key] = val

print json.dumps(HOSTS)
