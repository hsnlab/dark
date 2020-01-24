#!/usr/bin/env python

# Copyright 2017 Mark Szalay, David Haja, Marton Szabo

import orchestrator as DARK
import json
import graph_classes
import logging
import networkx as nx
import time
import os
from flask import request as flask_request
from flask import jsonify
from flask import Flask
from logging.handlers import RotatingFileHandler
import threading
from threading import Thread
import sys
if sys.version_info < (3, 0):
    import measurement.openstackvmtp as meas
import topology_gen as gen
import traceback
import argparse
import sys
import subprocess

app = Flask(__name__)
handler = RotatingFileHandler('foo.log')

app.logger.addHandler(handler)
app.logger.setLevel(logging.DEBUG)


class DarkSystem:
    status = None
    request_queue = []

    def __init__(self, static, enable_deploy, delaym_path, topology_path):

        self.topo = self.load_topo_data(static, delaym_path, topology_path)
        self.resource_graph = self.topo[0]
        self.delay_matrix = self.topo[1]

        self.orchestrator = DARK.DARKOrchestrator(self.resource_graph, self.delay_matrix)

        self.deploy = enable_deploy
        if enable_deploy:
            import OpenStack
            self.physical_infra = OpenStack.OpenStack()

        self.status = "Ready for deploying"

    def load_topo_files(self, delaym_path, topology_path):
        try:
            with open(delaym_path) as delay_matrix_json:
                delay_matrix = json.load(delay_matrix_json)
        except IOError as e:
            print("Provide delay file among the fogs! Use the --d flag! For more info: --help")
            sys.exit()
        try:
            with open(topology_path) as rg_json:
                resource_dict = json.load(rg_json)
        except IOError as e:
            print("Provide description file of the topology! Use the --topology flag! For more info: --help")
            sys.exit()
        resource_graph = graph_classes.ResourceGraph.read_from_dict(resource_dict)
        return delay_matrix, resource_graph

    def load_topo_data(self, static, delaym_path, topology_path):

        if static:
            delay_matrix, resource_graph = self.load_topo_files(delaym_path, topology_path)
        else:
            log("Starting topology generation...", "INFO")
            if sys.version_info >= (3, 0):
                cmd = subprocess.call('python measurement/openstackvmtp.py', shell=True)
                delay_matrix, resource_graph = self.load_topo_files(delaym_path, topology_path)
            else:
                measure = meas.VmtpMeasurement()
                result = measure.run()
                resource_graph = gen.generate_topology(result[0])
                gen.save_topology(resource_graph)
                delay_matrix = result[1]
            log("Topology generation done!", "INFO")

        self.status = "Initialization"
        return resource_graph, delay_matrix

    def start_orchestration(self, network_service):
        expense = 0
        log("____________Start DARK service deployer___________", "INFO")
        log("Load incoming service requests, id: " + str(network_service.id), "INFO")

        if len([i.id for i in self.orchestrator.service_graphs if i.id == network_service.id]) > 0:
            return "Failed", "Requested service ID is already running"
        if len(network_service.saps) > 1:
            vl, vp = get_shortest_path_and_length(network_service.saps[0], network_service.saps[1], network_service)
            rl, rp = get_shortest_path_and_length(network_service.saps[0], network_service.saps[1], self.resource_graph)
        if len(network_service.saps) > 1 and rl > vl:
            log("{} is a not valid service ".format(network_service.id), "INFO")
        else:
            # Mapping
            try:
                start_timestamp = time.time()
                log("START TIME of mapping: " + str(start_timestamp) + "\n", "INFO")
                success, actual_exp, resource_after_seed, sum_mapped_cpu, new_service, changed_sgs = self.orchestrator.MAP(
                    network_service, False)
                # If the mapping was successful
                if success:
                    expense += actual_exp
                    log("####### Mapping Service " + str(network_service.id) + " success", "INFO")
                    # Call OpenStack's API
                    if self.deploy:
                        srv_num = len(self.orchestrator.service_graphs)
                        self.physical_infra.deploy(new_service, srv_num, changed_sgs)
                    return "successful", ""
                # if the mapping was not successful
                else:
                    end_failed_timestamp = time.time()
                    log("####### Mapping Service " + str(network_service.id) + " failed ## TimeStamp: " + str(
                            end_failed_timestamp) + " #######", "WARNING", log_traceback=False)
                    return "failed", ""
            except Exception as e:
                log("####### Mapping Service " + str(network_service.id) + " failed ## TimeStamp: " + str(
                    time.time()) + " #######", "ERROR")
                log(traceback.format_exc(), "ERROR")
                return "failed", "Exception happened"

    def deploy_services(self):
        while True:
            try:
                if len(self.request_queue) > 0:
                    request = self.request_queue.pop()
                    dark.status = "Deploying service request: {}".format(request['id'])
                    network_service = graph_classes.ServiceGraph.read_from_dict(service_graph_dict=request,
                                                                                resource_graph=dark.resource_graph)
                    deploying, msg = dark.start_orchestration(network_service)
                    time.sleep(10)
                    dark.status = "Ready for deploying"
            except Exception as e:
                log(e.message, "ERROR")

    def main(self):
        app.run(host=os.getenv('IP', '0.0.0.0'),
                port=int(os.getenv('PORT', 8080)))


def log(message, level, log_traceback=True):
    if level == "DEBUG":
        app.logger.debug(message)

    elif level == "INFO":
        app.logger.info(message)

    elif level == "WARNING":
        app.logger.warning(message)

    elif level == "ERROR":
        app.logger.error(message)

    elif level == "CRITICAL":
        app.logger.critical(message)


def get_shortest_path_and_length(start, end, graph):
    """

    :param start:
    :param end:
    :param graph:
    :return: length, path
    """
    G = nx.Graph()
    if isinstance(graph, graph_classes.ServiceGraph):
        G.add_nodes_from([n.id for n in graph.VNFS])
        G.add_nodes_from([s.id for s in graph.saps])
        G.add_weighted_edges_from([(l.node1, l.node2, l.required_delay) for l in graph.VLinks])
    elif isinstance(graph, graph_classes.ResourceGraph):
        G.add_nodes_from([n.id for n in graph.nodes])
        G.add_nodes_from([s.id for s in graph.saps])
        G.add_weighted_edges_from([(l.node1, l.node2, l.delay) for l in graph.links])

    if isinstance(start, str) and isinstance(end, str):
        return nx.bidirectional_dijkstra(G, start, end)
    else:
        if isinstance(start, str):
            return nx.bidirectional_dijkstra(G, start, end.id)
        elif isinstance(end, str):
            return nx.bidirectional_dijkstra(G, start.id, end)
        else:
            return nx.bidirectional_dijkstra(G, start.id, end.id)


def save_topology(rg, file_name):
    if not os.path.isdir("results"):
        os.makedirs("results")
    with open(file_name, 'w') as outfile:
        outfile.write(rg.toJSON())
    return True


@app.route("/")
def hello():
    return "Hello DARK user!"


@app.route('/api/v1.0/deploy_service', methods=['POST'])
def deploy_request():

    if len([i['id'] for i in dark.request_queue if i['id'] == flask_request.json['id']]) > 0:
        return jsonify({'deploying status': 'It is already in the waiting queue'}), 400
    else:
        dark.request_queue.append(flask_request.json)
        return jsonify({'deploying status': 'In progress'}), 202


@app.route('/api/v1.0/resource_graph', methods=['GET'])
def get_rg():
    json_str = dark.orchestrator._running.toJSON()
    return json.loads(json.dumps(json_str, sort_keys=True, indent=4))


@app.route('/api/v1.0/dark_status', methods=['GET'])
def get_dark_status():
    return jsonify({'orchestrator status': dark.status}), 201


@app.route('/api/v1.0/deployed_services', methods=['GET'])
def get_deployed_requests():
    service_ids = [i.id for i in dark.orchestrator.service_graphs]
    return jsonify({'deployed services': service_ids}), 201


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='DARK Orchestrator')
    parser.add_argument('--simulation', '-s', action='store_true', default=False,
                        help='Set this flag for simulations only (Running DARK without deploying VMs)')
    parser.add_argument('--delay_matrix', '-d', type=str,
                        default='delay_mtx.json',
                        help='Path to Delay Matrix file (measured delays between fogs)')
    parser.add_argument('--topology', '-t', type=str,
                        default='topology.json',
                        help='Path to Network Topology file (fogs and clouds)')

    args = parser.parse_args()

    log("=== DARK orchestrator ===", "INFO")

    if args.simulation:
        dark = DarkSystem(True, False, args.delay_matrix, args.topology)
    else:
        # FIXME: Models should be in a model dir
        if os.path.isfile(args.delay_matrix) and os.path.isfile(args.topology):
            dark = DarkSystem(False, True, args.delay_matrix, args.topology)
        else:
            print("First time of DARK running... (It could be some minutes to configure OpenStack and generate delay"
                  " and bandwidth models)")

            # Configuring AZs in OpenStack
            print("\tConfiguring Availability Zones (Fogs/Edges and Clouds) in OpenStack...\n")
            cmd = subprocess.call('./measurement/az_setup.py -c ./measurement/config.json', shell=True)

            dark = DarkSystem(False, True, 'delay_mtx.json', './measurement/topology.json')

    try:
        # Start deploying thread
        Thread(target=dark.deploy_services).start()
        # Start REST API thread
        dark.main()
    except KeyboardInterrupt:
        # Quit
        sys.exit()

