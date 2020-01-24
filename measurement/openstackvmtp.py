#!/usr/bin/env python

import os
import argparse
import sys
import json
from vmtp import vmtp
from keystoneauth1 import loading
from keystoneauth1 import session
from novaclient import client


class VmtpMeasurement(object):
    CLOUD_NODE = "CLOUD"
    FOG_NODE = "FOG"
    USER = "ubuntu@"
    DIR_PATH = os.path.dirname(os.path.realpath(__file__))

    def __init__(self, conf="config.json"):
        self.config = self.load_config(conf)
        self.VERSION = self.config["VERSION"]
        self.USERNAME = self.config["OS_USERNAME"]
        self.PASSWORD = self.config["OS_PASSWORD"]
        self.PROJECT_NAME = self.config["OS_PROJECT_NAME"]
        self.AUTH_URL = self.config["OS_AUTH_URL"]

    def load_config(self, config_file):
        path = os.path.join(self.DIR_PATH, config_file)
        try:
            f = open(path, 'r')
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
        hypervisors = [hyp for hyp in nova.hypervisors.list() if hyp.status == "enabled"]
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

    def get_measurement_ips(self, nodes):
        zones = []
        for node in nodes:
            if node["zone"] not in zones:
                zones.append((node["zone"], node["host_ip"]))
        return zones

    def calc_avg_results(self, results):
        size = len(results)
        bw = 0
        rtt = 0
        for result in results:
            bw += result["throughput_kbps"]
            rtt += result["rtt_ms"]
        bw = bw / size
        rtt = rtt / size
        return bw, rtt / 2

    def perform_measurement(self, srv, zone):
        filename = srv[0] + "_" + zone[0] + ".json"
        filename = os.path.join(self.DIR_PATH, filename)
        try:
            f = open(filename, 'r')
        except IOError:
            print("Running measurement between " + srv[0] + " and " + zone[0])
            opts = argparse.Namespace()
            opts.hosts = [self.USER + srv[1], self.USER + zone[1]]
            opts.protocols = "T"
            opts.json = filename
            sys.argv = ['']
            ret = vmtp.run_vmtp(opts)
        else:
            ret = json.load(f)
            f.close()
        return ret

    def collect_all_delay_and_bw(self, measurements):
        final_res = []
        for meas in measurements:
            results = meas[2]["flows"][1]["results"]
            bw, delay = self.calc_avg_results(results)
            final_res.append({"src": meas[0][0], "dst": meas[1][0], "bw": bw, "delay": delay})
        return final_res

    def measure_all_zones(self, zones):
        zoneNum = len(zones)
        if zoneNum < 2:
            raise RuntimeError("Not enough zones! At least 2 zones are necessary to perform the measurement.")
        measurements = []
        for i in range(0, zoneNum - 1):
            for j in range(i + 1, zoneNum):
                res = self.perform_measurement(zones[i], zones[j])
                measurements.append((zones[i], zones[j], res))
        result = self.collect_all_delay_and_bw(measurements)
        return result

    def generate_delay_matrix(self, mtx):
        fogs = set()
        for fog_element in mtx:
            fogs.add(str(fog_element["src"]))
            fogs.add(str(fog_element["dst"]))

        fogs = list(fogs)
        delay_matrix = dict()
        for fog1 in fogs:
            delay_list = dict()
            for fog2 in fogs:
                for fog_element in mtx:
                    if fog1 == fog2:
                        delay_list[fog2] = 0
                        break
                    elif (fog_element["src"] == fog1 and fog_element["dst"] == fog2) or (
                            fog_element["src"] == fog2 and fog_element["dst"] == fog1):
                        delay_list[fog2] = fog_element["delay"] * 1000
                        break
            delay_matrix[fog1] = delay_list
        return delay_matrix

    def dump_result(self, result, fname='measure.json'):
        with open(fname, 'wb') as outfile:
            outfile.write(json.dumps(result, indent=4, ensure_ascii=False).encode('utf8'))

    def run(self):
        nova = self.keystone_auth()
        nodes = self.collect_os_compute_nodes(nova)
        zone_ips = self.get_measurement_ips(nodes)
        measurements = self.measure_all_zones(zone_ips)
        delay_mtx = self.generate_delay_matrix(measurements)
        self.dump_result(nodes, 'nodes.json')
        self.dump_result(delay_mtx, 'delay_mtx.json')
        return nodes, delay_mtx


if __name__ == "__main__":
    meas = VmtpMeasurement()
    meas.run()
