# Copyright 2017 Mark Szalay, David Haja


import argparse
import random
from graph_classes import VNF
from graph_classes import ServiceGraph
from graph_classes import VirtualLink
from graph_classes import SAP
import json
import sys
import networkx as nx
import uuid

# delay = us
# bandwidth = Mbps
# CPU = core
# RAM = GB
# STORAGE = GB


def chain_gen(args):
    """

    :param args:
    :return:
    """
    service_chain_list = []

    with open(args.resource_graph) as resource_json:
        resource_graph = json.load(resource_json)

    comment = "Type: %s, Min_VNF: %s, Max_VNF: %s, Req_num: %s, Resource_Graph: %s" % (
        args.type, args.min_vnf, args.max_vnf, args.req_num, resource_graph['id'])

    for i in range(0, args.req_num):
        vnf_num = random.randint(args.min_vnf, args.max_vnf)
        sap_num = random.randint(1, 2)
        print("--- Service " + str(i) + " ---")
        service_graph = ServiceGraph(comment=comment)
        saps = []
        for sap in resource_graph['saps']:
            saps.append(SAP(id=sap["id"]))

        SAP1 = random.choice(saps)
        service_graph.saps.append(SAP1)
        vnf = VNF(service_graph.id, required_CPU=random.randint(1, 4), required_RAM=random.randint(1, 8),
                  required_STORAGE=random.randint(10, 1000))
        service_graph.VNFS.append(vnf)

        vlink = VirtualLink(SAP1.id, vnf.id, required_delay=random.randint(5000, 100000),
                            required_bandwidth=random.randint(1000, 10000))
        service_graph.VLinks.append(vlink)
        service_graph.VNFS[-1].connected_virtual_links.append(vlink.id)
        service_graph.saps[-1].connected_virtual_links.append(vlink.id)

        # For more VNF and virtual_links
        for j in range(0, vnf_num-1):
            # TODO: define required params for VNF as parameters of the python script
            service_graph.VNFS.append(VNF(service_graph.id, required_CPU=random.randint(1, 4),
                                          required_RAM=random.randint(1, 8), required_STORAGE=random.randint(10, 1000)))
            vlink = VirtualLink(service_graph.VNFS[-2].id, service_graph.VNFS[-1].id,
                                required_delay=random.randint(5000, 100000),
                                required_bandwidth=random.randint(1000, 10000))
            service_graph.VLinks.append(vlink)
            service_graph.VNFS[-2].connected_virtual_links.append(vlink.id)
            service_graph.VNFS[-1].connected_virtual_links.append(vlink.id)

        if sap_num == 2:
            SAP2 = random.choice(saps)
            if len(saps) > 1:
                while SAP1 == SAP2:
                    SAP2 = random.choice(saps)
                service_graph.saps.append(SAP2)
                vlink = VirtualLink(service_graph.VNFS[-1].id, service_graph.saps[-1].id,
                                    required_delay=random.randint(5000, 100000),
                                    required_bandwidth=random.randint(1000, 10000))
                service_graph.VLinks.append(vlink)
                service_graph.VNFS[-1].connected_virtual_links.append(vlink.id)
                service_graph.saps[-1].connected_virtual_links.append(vlink.id)
        service_chain_list.append(service_graph)
    return service_chain_list


def get_required_CPU_for_fogNode():
    # CPU = core
    return random.randint(1, 4)


def get_required_RAM_for_fogNode():
    # RAM = GB
    return random.randint(1, 8)


def get_required_STORAGE_for_fogNode():
    # STORAGE = GB
    return random.randint(1, 8)


def get_required_delay_for_link_between_sap_and_fog():
    # delay = us
    return random.randint(5000, 20000)


def get_required_bandwidth_for_link_between_sap_and_fog():
    # bandwidth = Mbps
    return random.randint(100, 1000)


def get_required_CPU_for_cloudNode():
    # CPU = core
    return random.randint(4, 10)


def get_required_RAM_for_cloudNode():
    # RAM = GB
    return random.randint(4, 16)


def get_required_STORAGE_for_cloudNode():
    # STORAGE = GB
    return random.randint(10, 200)


def get_required_delay_for_link_between_fog_and_cloud():
    # delay = us
    return random.randint(50000, 1000000)


def get_strict_delay():
    # delay = us
    return random.randint(8000, 10000)


def get_slight_delay():
    # delay = us
    return random.randint(80000, 150000)


def get_required_bandwidth_for_link_between_fog_and_cloud():
    # bandwidth = Mbps
    return random.randint(100, 500)


def realistc_chain_gen():
    service_chain_list = []
    with open(args.resource_graph) as resource_json:
        resource_graph = json.load(resource_json)
    comment = "Type: %s, Min_VNF: %s, Max_VNF: %s, Req_num: %s, Resource_Graph: %s" % (
        args.type, args.min_vnf, args.max_vnf, args.req_num, resource_graph['id'])
    for i in range(0, args.req_num):
        service_graph = ServiceGraph(comment=comment)
        saps = []
        for sap in resource_graph['saps']:
            saps.append(SAP(id=sap["id"]))
        SAP1 = random.choice(saps)
        service_graph.saps.append(SAP1)
        fog_node = VNF(service_graph.id, required_CPU=get_required_CPU_for_fogNode(),
                       required_RAM=get_required_RAM_for_fogNode(),
                       required_STORAGE=get_required_STORAGE_for_fogNode())
        service_graph.VNFS.append(fog_node)

        vlink = VirtualLink(SAP1.id, fog_node.id, required_delay=get_required_delay_for_link_between_sap_and_fog(),
                            required_bandwidth=get_required_bandwidth_for_link_between_sap_and_fog())
        service_graph.VLinks.append(vlink)
        service_graph.VNFS[-1].connected_virtual_links.append(vlink.id)
        service_graph.saps[-1].connected_virtual_links.append(vlink.id)

        cloud_node = VNF(service_graph.id, required_CPU=get_required_CPU_for_cloudNode(),
                         required_RAM=get_required_RAM_for_cloudNode(),
                         required_STORAGE=get_required_STORAGE_for_cloudNode())
        service_graph.VNFS.append(cloud_node)
        vlink2 = VirtualLink(fog_node.id, cloud_node.id,
                             required_delay=get_required_delay_for_link_between_fog_and_cloud(),
                             required_bandwidth=get_required_bandwidth_for_link_between_fog_and_cloud())
        service_graph.VLinks.append(vlink2)
        service_graph.VNFS[-1].connected_virtual_links.append(vlink2.id)
        service_graph.VNFS[-2].connected_virtual_links.append(vlink2.id)

        service_chain_list.append(service_graph)

    return service_chain_list


if __name__ == '__main__':
    print("Generating Service Chains")

    parser = argparse.ArgumentParser(description='Service Graph generator for DARK algorithm')

    parser.add_argument("-t", "--type", type=str,
                        help="chain, realistic_chain", default="chain")

    parser.add_argument("--min_vnf", type=int,
                        help='Minimal number of VNFs', default=random.randint(1, 2))

    parser.add_argument("--max_vnf", type=int,
                        help='Maximal number of VNFs', default=random.randint(2, 3))

    parser.add_argument("--req_num", type=int,
                        help='Number of generated requests', default=random.randint(10, 50))

    parser.add_argument("-r", "--resource_graph", type=str,
                        help='Input resource graph because of the SAPs')

    parser.add_argument("--output_file", type=str,
                        help='Output file name', default='requests.json')

    args = parser.parse_args()

    if not args.resource_graph:
        print("Please use -r or --resource_graph flag")
        sys.exit()
    if args.type == "chain":
        srv_chain = chain_gen(args)
    elif args.type == "realistic_chain":
        srv_chain = realistc_chain_gen()
    else:
        print("Please use -t flag with chain or realistic_chain")
        sys.exit()

    with open(str(args.output_file), 'w') as outfile:
        outfile.write(json.dumps(srv_chain, default=lambda o: o.__dict__, indent=4))
