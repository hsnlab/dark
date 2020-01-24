import argparse
import sys
import orchestrator as DARK
import json
from collections import namedtuple
import graph_classes
import logging
import traceback
import networkx as nx
import time
import random
import sys
import os
import threading


class Simulator:
    """

    """

    debug = None

    def __init__(self, log_file=None, resource_graph=None, delay_matrix=None):
        """

        :param log_file:
        :param resource_graph:
        :param delay_matrix:
        """
        self._resource_graph = resource_graph
        self._delay_matrix = delay_matrix
        self.orchestrator = DARK.DARKOrchestrator(resource_graph, delay_matrix)
        self.log_file = log_file
        self.deploy_queue = []
        logging.basicConfig(filename=self.log_file, level=logging.INFO)
        fileh = logging.FileHandler(log_file, 'a')
        fileh.setLevel(logging.INFO)
        log = logging.getLogger()  # root logger
        for hdlr in log.handlers[:]:  # remove all old handlers
            if isinstance(hdlr, logging.FileHandler):
                log.removeHandler(hdlr)
        log.addHandler(fileh)

    @staticmethod
    def log(message, level, log_traceback=True):

        if level == "DEBUG":
            # if Simulator.debug:
            print("DEBUG:\t\t " + message)
            logging.debug(message)
        elif level == "INFO":
            logging.info(message)
            print("INFO:\t\t " + message)
        elif level == "WARNING":
            logging.warning(message)
            if log_traceback:
                print(traceback.print_exc())
            print("WARNING:\t\t " + message)
        elif level == "ERROR":
            logging.error(message)
            if log_traceback:
                print(traceback.print_exc())
            print("ERROR:\t\t " + message)
        elif level == "CRITICAL":
            logging.critical(message)
            if log_traceback:
                print(traceback.print_exc())
            print("CRITICAL:\t\t " + message)

    def run(self, log_file, resource_graph, service_list_name, enable_debug, disable_migrating, choose_strategy,
            enable_deploy, manual):
        """

        :param log_file:
        :param resource_graph_name:
        :param service_list_name:
        :param enable_debug:
        :return:
        """
        file = open(log_file + "_result", "w")
        if enable_deploy:
            import OpenStack
            physical_infra = OpenStack.OpenStack(log_file)
            deploy_thread = None

        expense = 0
        self.log("____________Start DARK service deployer___________", "INFO")
        self.log("Service requests: " + str(service_list_name), "INFO")

        # Read service list from json file
        with open(service_list_name) as service_json:
            service_list = json.load(service_json)

        self.log("Number of services: " + str(len(service_list)), "INFO")
        self.log("Number of VNFS: " + str(sum([len(x['VNFS']) for x in service_list])), "INFO")
        self.log("Resource_graph: " + str(resource_graph.id), "INFO")
        self.log("______________________________________________", "INFO")

        # For every service
        service_num = 1
        mapped_service_num = 0
        first_failed = 0
        resource_after_seed = None
        number_of_failed = 0
        file.write("START MAPPING SERVICES " + str(time.time()) + "\n")
        sum_mapping = 0
        for service_dict in service_list:
            if manual:
                input('Continue?')
            service = graph_classes.ServiceGraph.read_from_dict(service_graph_dict=service_dict,
                                                                resource_graph=resource_graph)

            self.log("Load incoming service requests, id: " + str(service.id), "INFO")
            if len(service.saps) > 1:
                vl, vp = self._get_shortest_path_and_length(service.saps[0], service.saps[1], service)
                rl, rp = self._get_shortest_path_and_length(service.saps[0], service.saps[1], resource_graph)
            if len(service.saps) > 1 and rl > vl:
                self.log("{} is a not valid service ".format(service.id), "INFO")
            else:
                # Mapping
                try:
                    start_timestamp = time.time()
                    self.log("####### Mapping Service " + str(service_num) + " ## TimeStamp: " +
                             str(start_timestamp) + " #######", "INFO")
                    file.write("service_id: " + str(service.id) + "\n")
                    file.write("request_count: " + str(service_num) + "\n")
                    file.write("start_timestamp: " + str(start_timestamp) + "\n")
                    if choose_strategy != 0:
                        start_map_timestamp = time.time()
                        file.write("start_map_timestamp: " + str(start_map_timestamp) + "\n")
                        success, actual_exp, resource_after_seed, sum_mapped_cpu = self.orchestrator.nova_scheduler(
                            service, choose_strategy)
                    else:
                        start_map_timestamp = time.time()
                        file.write("start_map_timestamp: " + str(start_map_timestamp) + "\n")
                        success, actual_exp, resource_after_seed, sum_mapped_cpu, new_service, changed_sgs = \
                            self.orchestrator.MAP(service, disable_migrating)
                    if success:
                        end_successed_map_timestamp = time.time()
                        expense += actual_exp
                        mapped_service_num += 1
                        self.log("####### Mapping Service " + str(service_num) + " success ## TimeStamp: " +
                                 str(end_successed_map_timestamp) + " #########", "INFO")
                        self.log("####### Mapped services: %i #########\n" % mapped_service_num, "INFO")
                        file.write("mapped_request_count: " + str(mapped_service_num) + "\n")
                        file.write("mapped_cpu_count: " + str(sum_mapped_cpu) + "\n")
                        file.write("end_successed_map_timestamp: " + str(end_successed_map_timestamp) + "\n")

                        # Call OpenStack's API
                        if enable_deploy:
                            self.deploy_queue.append(new_service)
                            if not deploy_thread or not deploy_thread.isAlive():
                                deploy_thread = threading.Thread(target=physical_infra.watch_stacks,
                                                                 args=[log_file + "_result"])
                                deploy_thread.start()
                            physical_infra.deploy_as_stack(new_service, service_num, changed_sgs,
                                                           self._resource_graph.fogs)
                            service_num += 1
                        if not enable_deploy:
                            end_successed_timestamp = time.time()
                            file.write("end_successed_timestamp: " + str(end_successed_timestamp) + "\n")
                            service_num += 1
                            file.write("full_duration: " + str(end_successed_timestamp - start_timestamp) + "\n")
                        file.write("map_duration: " + str(end_successed_map_timestamp - start_map_timestamp) + "\n")
                        sum_mapping += (end_successed_map_timestamp - start_map_timestamp)
                    else:
                        if first_failed == 0:
                            first_failed = service_num
                        end_failed_timestamp = time.time()
                        self.log("####### Mapping Service " + str(service_num) + " failed ## TimeStamp: " + str(
                            end_failed_timestamp) + " #######", "WARNING", log_traceback=False)
                        self.log("####### Mapped services: %i #########\n" % mapped_service_num, "INFO")
                        file.write("mapped_request_count: " + str(mapped_service_num) + "\n")
                        file.write("mapped_cpu_count: " + str(sum_mapped_cpu) + "\n")
                        file.write("end_failed_timestamp: " + str(end_failed_timestamp) + "\n")
                        service_num += 1
                        number_of_failed += 1
                    file.write("\n")
                except Exception as e:
                    if first_failed == 0:
                        first_failed = service_num
                    self.log(str(e), "ERROR")
                    self.log("####### Mapping Service " + str(service_num) + " failed ## TimeStamp: " + str(
                        time.time()) + " #######", "ERROR")
                    self.log("####### Mapped services: %i #########\n" % mapped_service_num, "ERROR")
                    file.write("ERROR" + "\n")
                    break

        file.write("TOTAL MAPPING TIME: " + str(sum_mapping) + "\n")
        if enable_deploy:
            physical_infra.finished = True
        else:
            file.write("END MAPPING SERVICES: " + str(time.time()) + "\n")
        file.close()
        if '\\' in service_list_name:
            if not disable_migrating:
                self.save_topology(resource_after_seed,
                                   'results\\' + service_list_name.split('\\')[1].split('.')[0] + '_strategy' + str(
                                       choose_strategy) + '_final.json')
            else:
                self.save_topology(resource_after_seed,
                                   'results\\' + service_list_name.split('\\')[1].split('.')[0] + '_strategy' + str(
                                       choose_strategy) + '_final_wo.json')
        elif '/' in service_list_name:
            if not disable_migrating:
                self.save_topology(resource_after_seed,
                                   'results/' + service_list_name.split('/')[1].split('.')[0] + '_strategy' + str(
                                       choose_strategy) + '_final.json')
            else:
                self.save_topology(resource_after_seed,
                                   'results/' + service_list_name.split('/')[1].split('.')[0] + '_strategy' + str(
                                       choose_strategy) + '_final_wo.json')
        else:
            if not disable_migrating:
                self.save_topology(resource_after_seed,
                                   'results/' + service_list_name.split('.')[0] + '_strategy' + str(
                                       choose_strategy) + '_final.json')
            else:
                self.save_topology(resource_after_seed,
                                   'results/' + service_list_name.split('.')[0] + '_strategy' + str(
                                       choose_strategy) + '_final_wo.json')

        self.log("___________First failed: %i ___________" % first_failed, "INFO")
        # self.log("_______Actual Total Expense: %i _______" % expense, "INFO")
        self.log("_____ SUM Mapped services: %i _________" % mapped_service_num, "INFO")
        # self.log("___________End of simulating___________", "INFO")
        if enable_deploy:
            if deploy_thread and deploy_thread.isAlive():
                deploy_thread.join()

    def save_topology(self, rg, file_name):
        if not os.path.isdir("results"):
            os.makedirs("results")
        with open(file_name, 'w') as outfile:
            outfile.write(rg.toJSON())
        return True

    def _get_shortest_path_and_length(self, start, end, graph):
        """

        :param start:
        :param end:
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

    def run_deploy(self, physical_infra, log_file_name, service_num):
        while len(self.deploy_queue) > 0:
            with open(log_file_name + "_deploy_result", "a+") as lfile:
                lfile.write("request_count: " + str(service_num) + "\n")
                service = self.deploy_queue.pop(0)
                start_deploy_timestamp = time.time()
                lfile.write("start_deploy_timestamp: " + str(start_deploy_timestamp) + "\n")
                physical_infra.deploy(service[0], service[1], service[2])
                end_successed_deploy_timestamp = time.time()
                lfile.write("end_successed_deploy_timestamp: " + str(end_successed_deploy_timestamp) + "\n")
                lfile.write("deploy_duration: " + str(end_successed_deploy_timestamp - start_deploy_timestamp) + "\n\n")


if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Simulator for DARK mapping algorithm')
    parser.add_argument("-l", "--log_file", type=str,
                        help="Output log file name")
    parser.add_argument("-r", "--resource_graph", type=str,
                        help="Resource graph json file")
    parser.add_argument("-dm", "--delay_matrix", type=str,
                        help="Delay matrix json file")
    parser.add_argument("-s", "--service_list", type=str,
                        help="Service list json file")
    parser.add_argument("-d", "--debug", action="store_true",
                        help="Enable debug output")
    parser.add_argument("-wo", "--without_migrating", action="store_true",
                        help="Disable vnf migrating")
    parser.add_argument("--deploy", action="store_true",
                        help="Enable deploy to the OpenStack")
    parser.add_argument("-c", "--choose_strategy", type=int,
                        help="Node ordering strategy", default=0)
    parser.add_argument("-m", "--manual", action="store_true",
                        help="Manual execution", default=False)
    args = parser.parse_args()

    if not args.log_file:
        print("Please use -l flag or -h for help!")
        sys.exit()
    if not args.resource_graph:
        print("Please use -r flag or -h for help!")
        sys.exit()
    if not args.service_list:
        print("Please use -s flag or -h for help!")
        sys.exit()

    with open(args.resource_graph) as resource_json:
        resource_dict = json.load(resource_json)
    resource_graph = graph_classes.ResourceGraph.read_from_dict(resource_dict)

    print("Loading delay matrix...")
    if args.delay_matrix:
        # Read delay matrix from json file
        with open(args.delay_matrix) as delay_matrix_json:
            loaded_delay_matrix = json.load(delay_matrix_json)

        fogs = set()
        for fog_element in loaded_delay_matrix:
            fogs.add(str(fog_element["src"]))
            fogs.add(str(fog_element["dst"]))

        fogs = list(fogs)
        delay_matrix = dict()
        for fog1 in fogs:
            sys.stdout.write('.')
            sys.stdout.flush()
            delay_list = dict()
            for fog2 in fogs:
                for fog_element in loaded_delay_matrix:
                    if fog1 == fog2:
                        delay_list[fog2] = 0
                        break
                    elif (fog_element["src"] == fog1 and fog_element["dst"] == fog2) or (
                            fog_element["src"] == fog2 and fog_element["dst"] == fog1):
                        delay_list[fog2] = fog_element["delay"]
                        # delay_list[fog2] = 1
                        break
            delay_matrix[fog1] = delay_list

    else:
        print("Please use -dm flag or -h for help!")
        sys.exit()

    s = Simulator(log_file=args.log_file, resource_graph=resource_graph, delay_matrix=delay_matrix)
    s.run(args.log_file, resource_graph, args.service_list, args.debug, args.without_migrating, args.choose_strategy,
          args.deploy, args.manual)

