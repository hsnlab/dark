import random
import argparse
import sys
import json

from graph_classes import ResourceGraph, PhysicalLink, PhysicalNode, SAP, Fog
import networkx as nx
import matplotlib.pyplot as plt

# delay = us
# bandwidth = Mbps
# CPU = core
# RAM = GB
# STORAGE = GB


def generate_topology(nodes):
    rg = ResourceGraph()
    core_network = PhysicalNode(type="core_network")
    core_network.id += "NETWORK"
    rg.nodes.append(core_network)
    fogs = {}

    for node in nodes:
        if node["zone"].startswith("asdasddf"):
            pass
        else:
            if node["zone"] not in fogs:
                temp_fog = Fog(id=node["zone"])
                if "FOG" in node["zone"]:
                    fog_sap_gw = PhysicalNode(fog_cloud=temp_fog.id, type="SAP-gateway")
                    fog_sap_gw.id += "GW"
                    temp_fog.gws.append(fog_sap_gw.id)
                    rg.nodes.append(fog_sap_gw)

                    fog_core_gw = PhysicalNode(fog_cloud=temp_fog.id, type="CORE-gateway")
                    fog_core_gw.id += "GW"
                    temp_fog.gws.append(fog_core_gw.id)
                    rg.nodes.append(fog_core_gw)

                elif "CLOUD" in node["zone"]:
                    fog_core_gw = PhysicalNode(fog_cloud=temp_fog.id, type="CORE-gateway-cloud")
                    fog_core_gw.id += "GW"
                    temp_fog.gws.append(fog_core_gw.id)
                    rg.nodes.append(fog_core_gw)
                    fog_sap_gw = None
                
                fogs[node["zone"]] = (temp_fog, fog_sap_gw, fog_core_gw)

                gw_core_link = PhysicalLink(delay=random.randint(10000, 15000), bandwidth=40000, node1=fog_core_gw.id,
                                            node2=core_network.id)
                rg.links.append(gw_core_link)
                fog_core_gw.connected_physical_links.append(gw_core_link.id)
                core_network.connected_physical_links.append(gw_core_link.id)

                if "FOG" in node["zone"]:
                    # create SAP object
                    temp_SAP = SAP(fog_cloud=temp_fog.id)
                    # Add to resource graph saps list
                    temp_SAP.id += 'SAP'
                    rg.saps.append(temp_SAP)
                    temp_fog.saps.append(temp_SAP.id)
                    # Create link between newly created sap and physical node
                    gw_to_SAP = PhysicalLink(delay=random.randint(100, 200), bandwidth=1000, node1=fog_sap_gw.id,
                                             node2=temp_SAP.id)
                    # add link to resource graph links list
                    rg.links.append(gw_to_SAP)
                    fog_sap_gw.connected_physical_links.append(gw_to_SAP.id)
                    temp_SAP.connected_physical_links.append(gw_to_SAP.id)

                    gw_to_gw = PhysicalLink(delay=random.randint(100, 200), bandwidth=1000, node1=fog_sap_gw.id,
                                            node2=fog_core_gw.id)
                    rg.links.append(gw_to_gw)
                    fog_sap_gw.connected_physical_links.append(gw_to_gw.id)
                    fog_core_gw.connected_physical_links.append(gw_to_gw.id)
                
                rg.fogs.append(temp_fog)
            # Create Physical node object
            cpu = node["cpu"]
            ram = node["ram"]
            storage = node["storage"]
            if "FOG" in node["zone"]:
                cloud_cost = None
                cloud_type = "compute"
            elif "CLOUD" in node["zone"]:
                cloud_cost = {"cpu": random.randint(1, 5) * 100, "ram": random.randint(1, 5) * 100,
                              "storage": random.randint(1, 5), "bandwidth": random.randint(1, 5) * 0.1}
                cloud_type = "core_cloud"
            temp_node = PhysicalNode(cpu_max=cpu, cpu_available=cpu, ram_max=ram, ram_available=ram,
                                     storage_max=storage, storage_available=storage, fog_cloud=node["zone"],
                                     type=cloud_type, resource_cost=cloud_cost, id=node["host"])
            fog_core_gw = fogs[node["zone"]][2]
            fog_sap_gw = fogs[node["zone"]][1]
            temp_fog = fogs[node["zone"]][0]
            # Append to resource graph nodes list
            rg.nodes.append(temp_node)
            
            # create link between edge node and fog cloud gw
            edge_to_core = PhysicalLink(delay=random.randint(100, 200), bandwidth=1000, node1=temp_node.id,
                                        node2=fog_core_gw.id)
            rg.links.append(edge_to_core)
            fog_core_gw.connected_physical_links.append(edge_to_core.id)
            temp_node.connected_physical_links.append(edge_to_core.id)
            if "FOG" in node["zone"]:
                # create link between edge node and sap gw
                edge_to_sap = PhysicalLink(delay=random.randint(100, 200), bandwidth=1000, node1=temp_node.id,
                                           node2=fog_sap_gw.id)
                rg.links.append(edge_to_sap)
                fog_sap_gw.connected_physical_links.append(edge_to_sap.id)
                temp_node.connected_physical_links.append(edge_to_sap.id)

            for comp in temp_fog.compute_nodes:
                edge_to_edge = PhysicalLink(delay=random.randint(100, 200), bandwidth=1000,
                                            node1=comp, node2=temp_node.id)
                for n in rg.nodes:
                    if n.id == comp:
                        n.connected_physical_links.append(edge_to_edge.id)
                    elif n.id == temp_node.id:
                        n.connected_physical_links.append(edge_to_edge.id)

                rg.links.append(edge_to_edge)
            # Append node to fog
            temp_fog.compute_nodes.append(temp_node.id)
    return rg


def save_topology(rg, file_name='topology.json'):
    with open(file_name, 'w') as outfile:
        outfile.write(rg.toJSON())
    return True


def show_topology(topology, export):
    G = nx.Graph()
    print('Fogs: ' + str(len(topology.fogs)))
    print('Nodes: ' + str(len(topology.nodes)))
    print('SAPs: ' + str(len(topology.saps)))
    print('Links: ' + str(len(topology.links)))
    G.add_nodes_from(nodes=[x.id for x in topology.saps])
    G.add_nodes_from(nodes=[x.id for x in topology.nodes])
    G.add_edges_from((x.node1, x.node2) for x in topology.links)
    cm = []
    for node in G:
        if 'SAP' in node.upper():
            cm.append('blue')
        elif 'GW' in node:
            cm.append('green')
        elif 'NETWORK' in node:
            cm.append('yellow')
        else:
            cm.append('red')
    nx.draw(G, node_color=cm, cmap=plt.get_cmap('jet'), node_size=10)
    plt.show()
    if export:
        plt.savefig("graph.png", format="PNG")
    return G


def load_nodes(file_name):
    with open(file_name, 'r') as infile:
        nodes = json.load(infile)
    return nodes


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Topology Generator')
    parser.add_argument('--nodes', '-n', action='store', dest='nodes', type=str,
                        default="nodes.json",
                        help='Load nodes from file')
    parser.add_argument('--save', '-s', action='store', dest='save', type=bool,
                        default=False,
                        help='Set if you want to save the topology to file')
    parser.add_argument('--export', '-e', action='store', dest='export', type=bool,
                        default=False,
                        help='Set if you want to export the resource graph')
    parser.add_argument('--file', action='store', dest='file_name', type=str,
                        default='topology.json',
                        help='Set json filename where topology will be saved')
    arg_results = parser.parse_args()

    nodes = load_nodes(arg_results.nodes)

    topology = generate_topology(nodes)

    graph = show_topology(topology=topology, export=arg_results.export)
    if arg_results.save:
        save_topology(topology, arg_results.file_name)
