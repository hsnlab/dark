#!/usr/bin/env python

import os
import argparse
import sys
import json
import time
from keystoneauth1 import loading
from keystoneauth1 import session
from novaclient import client


class AZConfig(object):
    CLOUD_NODE = "CLOUD"
    EDGE_NODE = "FOG"
    CPU_LIMIT = 5    # Below this limit,
    PREFIX = "compute"

    def __init__(self, conf="./config.json"):
        self.config = self.load_config(conf)
        self.VERSION = self.config["VERSION"]
        self.USERNAME = self.config["OS_USERNAME"]
        self.PASSWORD = self.config["OS_PASSWORD"]
        self.PROJECT_NAME = self.config["OS_PROJECT_NAME"]
        self.AUTH_URL = self.config["OS_AUTH_URL"]

    def load_config(self, config_file):
        try:
            f = open(config_file, 'r')
        except IOError:
            print("Config file:" + config_file + " not found!")
            sys.exit()
        else:
            conf = json.load(f)
            f.close()
        return conf

    def keystone_auth(self, domain="default", project="default"):
        loader = loading.get_plugin_loader('password')
        auth = loader.load_from_options(auth_url=self.AUTH_URL, username=self.USERNAME, password=self.PASSWORD,
                                        project_name=self.PROJECT_NAME, user_domain_name=domain,
                                        project_domain_name=project)
        sess = session.Session(auth=auth)
        nova = client.Client(self.VERSION, session=sess)
        return nova

    def collect_os_compute_nodes(self, nova):
        sys.argv = ['']
        hypervisors = [hyp for hyp in nova.hypervisors.list() if hyp.status == "enabled" and hyp.state == "up"]
        # FIXME: Should we check if hypervisor is a compute?
        nodes = []
        for hyp in hypervisors:
            host = hyp.service['host']
            zone = next(i.zoneName for i in nova.availability_zones.list() if host in i.hosts.keys())
            node = {"hypervisor": hyp.hypervisor_hostname,
                    "host": host,
                    "zone": zone,
                    "cpu": hyp.vcpus,
                    "ram": hyp.memory_mb,
                    "storage": hyp.local_gb,
                    "host_ip": hyp.host_ip}
            nodes.append(node)
        return nodes

    def clear_azs(self, nova):
        aggregates = nova.aggregates.list()
        for agg in aggregates:
            for host in agg.hosts:
                nova.aggregates.remove_host(agg.id, host)
            nova.aggregates.delete(agg.id)

    def configure_azs(self, nova, nodes):
        cloud_num = 1
        fog_num = 1
        for node in nodes:
            if node['zone'] == "nova":
                if node['cpu'] > self.CPU_LIMIT:
                    aggr = 'HA-cloud-{}'.format(cloud_num)
                    az = self.CLOUD_NODE + "-{}".format(cloud_num)
                    cloud_num += 1
                else:
                    aggr = 'HA-fog-{}'.format(fog_num)
                    az = self.EDGE_NODE + "-{}".format(fog_num)
                    fog_num += 1
                zone = nova.aggregates.create(name=aggr, availability_zone=az)
                nova.aggregates.add_host(zone.id, node['host'])

    def configure_azs_from_resource_graph(self, nova, resource_graph):
        """

        :param nova:
        :param resource_graph:
        :return:
        """
        for fog in resource_graph.fogs:
            az = fog.id
            node_name = fog.compute_nodes[0]
            aggr = 'HA' + node_name
            zone = nova.aggregates.create(name=aggr, availability_zone=az)
            nova.aggregates.add_host(zone.id, node_name)

    def dump_result(self, result, fname='results.json'):
        with open(fname, 'wb') as outfile:
            outfile.write(json.dumps(result, indent=4, ensure_ascii=False).encode('utf8'))

    def generate_hosts(self, nova):
        res = []
        hosts = [hyp for hyp in nova.hypervisors.list() if hyp.status == "enabled" and hyp.state == "up"]
        for host in hosts:
            host_name = host.service['host']
            zone = next(i.zoneName for i in nova.availability_zones.list() if host_name in i.hosts.keys())
            res.append({
                "zone": zone,
                "host": host_name,
                "cpu": host.vcpus,
                "ram": host.memory_mb,
                "storage": host.local_gb
            })
        return res

    def run(self, clear=False, resource_graph=None):
        nova = self.keystone_auth()
        if clear:
            self.clear_azs(nova)
        if not resource_graph:
            nodes = self.collect_os_compute_nodes(nova)
            self.configure_azs(nova, nodes)
        else:
            self.configure_azs_from_resource_graph(nova, resource_graph)
        return self.generate_hosts(nova)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Availability Zone installer')
    parser.add_argument('--config_path', '-c', type=str,
                        default='./config.json',
                        help='Path to OpenStack config file')

    args = parser.parse_args()
    zones = AZConfig(args.config_path)
    res = zones.run(True)
