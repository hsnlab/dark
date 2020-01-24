import random
import argparse
from graph_classes import ResourceGraph, PhysicalLink, PhysicalNode, SAP, Fog
import networkx as nx
import matplotlib.pyplot as plt


# delay = us
# bandwidth = Mbps
# CPU = core
# RAM = GB
# STORAGE = GB


def generate_topology(num_servers, num_fogs=random.randint(5, 10), num_clouds=2):
    rg = ResourceGraph()
    core_network = PhysicalNode(type="core_network")
    core_network.id += "NETWORK"
    rg.nodes.append(core_network)

    for i in range(num_clouds):

        cloud_cost = {"cpu": random.randint(1, 5) * 100, "ram": random.randint(1, 5) * 100,
                      "storage": random.randint(1, 5), "bandwidth": random.randint(1, 5) * 0.1}

        cloud_fog = Fog()
        cloud_fog.id += "CLOUD"

        fog_core_gw = PhysicalNode(fog_cloud=cloud_fog.id, type="CORE-gateway-cloud")
        fog_core_gw.id += "GW"
        cloud_fog.gws.append(fog_core_gw.id)
        rg.nodes.append(fog_core_gw)

        gw_core_link = PhysicalLink(delay=random.randint(10000, 15000), bandwidth=100000, node1=fog_core_gw.id,
                                    node2=core_network.id)
        rg.links.append(gw_core_link)
        fog_core_gw.connected_physical_links.append(gw_core_link.id)
        core_network.connected_physical_links.append(gw_core_link.id)

        for j in range(num_servers):
            # Create Physical node object
            temp_node = PhysicalNode(cpu_max=999999, cpu_available=999999, ram_max=999999, ram_available=999999,
                                     storage_max=999999, storage_available=999999, fog_cloud=cloud_fog.id,
                                     type="core_cloud", resource_cost=cloud_cost)
            temp_node.id += "CLOUD"
            # Append to resource graph nodes list
            rg.nodes.append(temp_node)
            # Append node to fog
            cloud_fog.compute_nodes.append(temp_node.id)

            # create link between edge node and fog cloud gw
            edge_to_core = PhysicalLink(delay=random.randint(100, 200), bandwidth=1000, node1=temp_node.id,
                                        node2=fog_core_gw.id)
            rg.links.append(edge_to_core)
            fog_core_gw.connected_physical_links.append(edge_to_core.id)
            temp_node.connected_physical_links.append(edge_to_core.id)

        for j in range(num_servers-1):
            for k in range(j + 1, num_servers):
                edge_to_edge = PhysicalLink(delay=random.randint(100, 200), bandwidth=1000,
                                            node1=cloud_fog.compute_nodes[j], node2=cloud_fog.compute_nodes[k])
                for n in rg.nodes:
                    if n.id == cloud_fog.compute_nodes[j]:
                        n.connected_physical_links.append(edge_to_edge.id)
                    elif n.id == cloud_fog.compute_nodes[k]:
                        n.connected_physical_links.append(edge_to_edge.id)
                rg.links.append(edge_to_edge)
        rg.fogs.append(cloud_fog)

    rams = [64, 128, 256]
    stors = [5120, 10240, 20480, 30720, 40960, 51200, 61440, 71680, 81920]

    for f in range(num_fogs):
        temp_fog = Fog()

        fog_sap_gw = PhysicalNode(fog_cloud=temp_fog.id, type="SAP-gateway")
        fog_sap_gw.id += "GW"
        temp_fog.gws.append(fog_sap_gw.id)
        rg.nodes.append(fog_sap_gw)

        fog_core_gw = PhysicalNode(fog_cloud=temp_fog.id, type="CORE-gateway")
        fog_core_gw.id += "GW"
        temp_fog.gws.append(fog_core_gw.id)
        rg.nodes.append(fog_core_gw)

        gw_core_link = PhysicalLink(delay=random.randint(10000, 15000), bandwidth=40000, node1=fog_core_gw.id,
                                    node2=core_network.id)
        rg.links.append(gw_core_link)
        fog_core_gw.connected_physical_links.append(gw_core_link.id)
        core_network.connected_physical_links.append(gw_core_link.id)
        # create SAP object
        temp_SAP = SAP(fog_cloud=temp_fog.id)
        # Add to resource graph saps list
        temp_SAP.id += 'SAP'
        rg.saps.append(temp_SAP)
        temp_fog.saps.append(temp_SAP.id)
        # Create link between newly created sap and physical node
        gw_to_SAP = PhysicalLink(delay=random.randint(100, 200), bandwidth=1000, node1=fog_sap_gw.id, node2=temp_SAP.id)
        # add link to resource graph links list
        rg.links.append(gw_to_SAP)
        fog_sap_gw.connected_physical_links.append(gw_to_SAP.id)
        temp_SAP.connected_physical_links.append(gw_to_SAP.id)

        gw_to_gw = PhysicalLink(delay=random.randint(100, 200), bandwidth=1000, node1=fog_sap_gw.id,
                                node2=fog_core_gw.id)
        rg.links.append(gw_to_gw)
        fog_sap_gw.connected_physical_links.append(gw_to_gw.id)
        fog_core_gw.connected_physical_links.append(gw_to_gw.id)

        num_nodes = num_servers
        for i in range(num_nodes):
            # Create Physical node object
            cpu = random.randint(24, 30)
            ram = rams[random.randint(0, 2)]
            storage = stors[random.randint(0, len(stors) - 1)]
            temp_node = PhysicalNode(cpu_max=cpu, cpu_available=cpu, ram_max=ram, ram_available=ram,
                                     storage_max=storage, storage_available=storage, fog_cloud=temp_fog.id,
                                     type="compute")
            # Append to resource graph nodes list
            rg.nodes.append(temp_node)
            # Append node to fog
            temp_fog.compute_nodes.append(temp_node.id)

            # create link between edge node and fog cloud gw
            edge_to_core = PhysicalLink(delay=random.randint(100, 200), bandwidth=1000, node1=temp_node.id,
                                        node2=fog_core_gw.id)
            rg.links.append(edge_to_core)
            fog_core_gw.connected_physical_links.append(edge_to_core.id)
            temp_node.connected_physical_links.append(edge_to_core.id)

            # create link between edge node and sap gw
            edge_to_sap = PhysicalLink(delay=random.randint(100, 200), bandwidth=1000, node1=temp_node.id,
                                       node2=fog_sap_gw.id)
            rg.links.append(edge_to_sap)
            fog_sap_gw.connected_physical_links.append(edge_to_sap.id)
            temp_node.connected_physical_links.append(edge_to_sap.id)

        for j in range(num_nodes-1):
            for k in range(j + 1, num_nodes):
                edge_to_edge = PhysicalLink(delay=random.randint(100, 200), bandwidth=1000,
                                            node1=temp_fog.compute_nodes[j], node2=temp_fog.compute_nodes[k])
                for n in rg.nodes:
                    if n.id == temp_fog.compute_nodes[j]:
                        n.connected_physical_links.append(edge_to_edge.id)
                    elif n.id == temp_fog.compute_nodes[k]:
                        n.connected_physical_links.append(edge_to_edge.id)
                rg.links.append(edge_to_edge)

        rg.fogs.append(temp_fog)
    return rg


def save_topology(rg, file_name='topology.json'):
    with open(file_name, 'w') as outfile:
        outfile.write(rg.toJSON())
    return True


def show_topology(topology, export):
    G = nx.Graph()
    G.add_nodes_from(nodes=[x.id for x in topology.saps])
    G.add_nodes_from(nodes=[x.id for x in topology.nodes])
    G.add_edges_from((x.node1, x.node2) for x in topology.links)
    cm = []
    for node in G:
        if 'SAP' in node:
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


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Topology Generator')

    parser.add_argument('--fogs', '-f', action='store', dest='num_fogs', type=int,
                        default=random.randint(5, 10),
                        help='Set number of fog clouds')

    parser.add_argument('--clouds', '-c', action='store', dest='num_clouds', type=int,
                        default=2,
                        help='Set number of clouds')

    parser.add_argument('--servers', '-fs', action='store', dest='num_servers_in_fogs', type=int,
                        default=random.randint(5, 10),
                        help='Set number of fog servers inside fogs')

    parser.add_argument('--save', '-s', action='store', dest='save', type=bool,
                        default=True,
                        help='Set if you want to save the topology to file')

    parser.add_argument('--export', '-e', action='store', dest='export', type=bool,
                        default=False,
                        help='Set if you want to export the resource graph')

    parser.add_argument('--file', action='store', dest='file_name', type=str,
                        default='topology.json',
                        help='Set json filename where topology will be saved')

    arg_results = parser.parse_args()

    topology = generate_topology(arg_results.num_servers_in_fogs, arg_results.num_fogs, arg_results.num_clouds)
    if arg_results.save:
        save_topology(topology, arg_results.file_name)
