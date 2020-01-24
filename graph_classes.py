# Storage in GB
# CPU in corenum
# RAM in GB
# Service_graph: {
# 	"id": "value",
# 	cost: integer,
# 	nodes: [{
# 		id: "value",
# 		type: string,
# 		required_CPU: integer,
# 		required_RAM: integer,
# 		required_STORAGE: integer,
# 		mapped_to: PHY_NODE,
#       mig_cost: int
# 	}],
# 	links: [{
# 		id: "value",
# 		required_delay: integer,
# 		required_bandwidth: integer,
# 		node1: VNF/SAP,
# 		node2: VNF/SAP,
# 		mapped_to: [PHY_LINK]
# 	}],
#   saps: [{id: "value"}]
# }
#
# Resource_graph: {
# 	id: "value",
#   fogs: [{id: "value", physical_nodes: [{PhysicalNode}]}]
# 	nodes: [{
# 		id: "value",
# 		CPU: {
# 			available: integer,
# 			max: integer
# 		},
# 		RAM: {
# 			available: integer,
# 			max: integer
# 		},
# 		STORAGE: {
# 			available: integer,
# 			max: integer
# 		},
# 		location: string,
# 		mapped_vnf: [{VNF}],
#       connected_links: [{Link}],
#       fog_cloud: string,
#       type: string
# 	}],
# 	links: [{
# 		id: "value",
# 		delay: integer,
# 		node1: PHY_NODE/SAP,
# 		node2: PHY_NODE/SAP,
# 		mapped_virtual_links: [VLINK]
# 	}],
#   saps: [{id: "value"}]
# }

import uuid
import json


class Fog:
    """

    """

    def __init__(self, id=None, compute_nodes=None, gws=None, saps=None):
        if id is None:
            self.id = str(uuid.uuid4())
        else:
            self.id = id
        if compute_nodes is None:
            compute_nodes = []
        self.compute_nodes = compute_nodes
        if saps is None:
            saps = []
        self.saps = saps
        if gws is None:
            gws = []
        self.gws = gws


class Node(object):

    def __init__(self, id=None, type=""):
        if id is None:
            self.id = str(uuid.uuid4())
        else:
            self.id = id

        self.type = type


class VNF(Node):
    """

    """

    def __init__(self, service_graph, cloud_cost=None, id=None, required_CPU=0, required_RAM=0, required_STORAGE=0,
                 mapped_to=None, connected_virtual_links=None):
        super(self.__class__, self).__init__(id, "VNF")
        self.required_CPU = required_CPU
        self.required_RAM = required_RAM
        self.required_STORAGE = required_STORAGE
        # mapped_to is a physical node, where the VNF is mapped to
        self.mapped_to = mapped_to
        if connected_virtual_links is None:
            connected_virtual_links = []
        self.connected_virtual_links = connected_virtual_links
        self.service_graph = service_graph
        self.cloud_cost = cloud_cost
        self.migrate_to = None
        self.mig_cost = 0


class PhysicalNode(Node):
    """

    """
    # type options: compute, gw, core_network, core_compute
    def __init__(self, id=None, type="PhysicalNode", cpu_max=0, cpu_available=0, ram_max=0, ram_available=0,
                 storage_max=0, storage_available=0, migr_coeff=1, mapped_VNFS=None, fog_cloud=None,
                 connected_physical_links=None, resource_cost=None):
        super(self.__class__, self).__init__(id, type)
        self.CPU = {'available': cpu_available, 'max': cpu_max}
        self.RAM = {'available': ram_available, 'max': ram_max}
        self.STORAGE = {'available': storage_available, 'max': storage_max}

        # mapped VNFs contains VNF objects
        if mapped_VNFS is None:
            mapped_VNFS = []
        self.mapped_VNFS = mapped_VNFS
        self.fog_cloud = fog_cloud

        if connected_physical_links is None:
            connected_physical_links = []
        self.connected_physical_links = connected_physical_links

        self.cost = {}
        if resource_cost is None:
            self.cost["cpu"] = 0
            self.cost["ram"] = 0
            self.cost["storage"] = 0
            self.cost["bandwidth"] = 0
        else:
            self.cost["cpu"] = resource_cost["cpu"]
            self.cost["ram"] = resource_cost["ram"]
            self.cost["storage"] = resource_cost["storage"]
            self.cost["bandwidth"] = resource_cost["bandwidth"]

        self.migration_coeff = migr_coeff


class SAP(Node):
    """

    """

    def __init__(self, id=None, connected_physical_links=None, connected_virtual_links=None, fog_cloud=None):
        if id is None:
            id = str(uuid.uuid4())
        self.fog_cloud = fog_cloud
        super(self.__class__, self).__init__(id, "SAP")

        if connected_physical_links is None:
            connected_physical_links = []
        self.connected_physical_links = connected_physical_links
        if connected_virtual_links is None:
            connected_virtual_links = []
        self.connected_virtual_links = connected_virtual_links


class Link(object):

    def __init__(self, id=None, type=""):
        if id is None:
            self.id = str(uuid.uuid4())
        else:
            self.id = id

        if type is "":
            self.type = "undefined"
        else:
            self.type = type


class ServiceGraph:
    """

    """

    def __init__(self, id=None, VNFS=None, VLinks=None, comment="", saps=None):
        if id is None:
            self.id = str(uuid.uuid4())
        else:
            self.id = id
        if VNFS is None:
            VNFS = []
        if VLinks is None:
            VLinks = []
        if saps is None:
            saps = []
        self.VNFS = VNFS
        self.VLinks = VLinks
        self.comment = comment
        self.saps = saps

    @staticmethod
    def read_from_dict(service_graph_dict, resource_graph=None):

        VNF_list = []
        for i in service_graph_dict['VNFS']:
            vnf = VNF(i["service_graph"], None, i['id'], i['required_CPU'], i["required_RAM"], i["required_STORAGE"],
                      i["mapped_to"], i["connected_virtual_links"])
            VNF_list.append(vnf)

        sap_list = []
        for i in service_graph_dict["saps"]:
            sap = SAP(id=i["id"], connected_virtual_links=i["connected_virtual_links"])
            if resource_graph is not None:
                for x in resource_graph.saps:
                    if sap.id == x.id:
                        sap.connected_physical_links = x.connected_physical_links
                        sap.fog_cloud = x.fog_cloud
            sap_list.append(sap)

        VLink_list = []
        for i in service_graph_dict["VLinks"]:
            vlink = VirtualLink(i["node1"], i["node2"], i["id"], i["required_delay"], i["required_bandwidth"],
                                i["mapped_to"])
            VLink_list.append(vlink)

        service_graph = ServiceGraph(service_graph_dict["id"], VNF_list, VLink_list,
                                     service_graph_dict["comment"], sap_list)

        return service_graph


class VirtualLink(Link):
    """

    """

    def __init__(self, node1, node2, id=None, required_delay=0, required_bandwidth=0, mapped_to=None):
        super(self.__class__, self).__init__(id, "VirtualLink")

        self.required_delay = required_delay
        self.required_bandwidth = required_bandwidth

        # mapped_to is a list containing physical links
        if mapped_to is None:
            mapped_to = []
        self.mapped_to = mapped_to
        self.node1 = node1
        self.node2 = node2

    def __str__(self):
        return json.dumps(self, default=lambda o: o.__dict__, sort_keys=True, indent=4)

    def __repr__(self):
        return self.id


class ResourceGraph:
    """

    """

    def __init__(self, id=None, nodes=None, links=None, saps=None, fogs=None):
        if id is None:
            self.id = str(uuid.uuid4())
        else:
            self.id = id
        # nodes contains PhysicalNode objects
        if nodes is None:
            nodes = []
        self.nodes = nodes
        # links contains PhysicalLink objects
        if links is None:
            links = []
        self.links = links
        # saps contains SAP objects
        if saps is None:
            saps = []
        self.saps = saps
        if fogs is None:
            fogs = []
        self.fogs = fogs

    def toJSON(self):
        return json.dumps(self, default=lambda o: o.__dict__, sort_keys=True, indent=4)

    @staticmethod
    def read_from_dict(input_dict):
        node_list = []
        for i in input_dict['nodes']:
            node_list.append(PhysicalNode(id=i['id'], cpu_max=i['CPU']['max'], cpu_available=i['CPU']['available'],
                                          ram_max=i['RAM']['max'], ram_available=i['RAM']['available'],
                                          storage_max=i['STORAGE']['max'], storage_available=i['STORAGE']['available'],
                                          connected_physical_links=i['connected_physical_links'],
                                          fog_cloud=i['fog_cloud'], type=i['type'], mapped_VNFS=i['mapped_VNFS'],
                                          resource_cost=i['cost']))

        sap_list = []
        for i in input_dict["saps"]:
            sap_list.append(SAP(id=i["id"], connected_physical_links=i['connected_physical_links'],
                                fog_cloud=i['fog_cloud']))

        link_list = []
        for i in input_dict["links"]:
            bw = i['bandwidth']
            avail_bw = bw["available"]
            max_bw = bw["max"]
            temp_list = node_list + sap_list
            ph_link = PhysicalLink(node1=i['node1'], node2=i['node2'], id=i['id'], delay=i['delay'], bandwidth=max_bw,
                                   mapped_virtual_links=i['mapped_virtual_links'])
            link_list.append(ph_link)

        fogs = []
        for i in input_dict['fogs']:
            fog = Fog(i['id'], i['compute_nodes'], i['gws'], i['saps'])
            fogs.append(fog)

        return ResourceGraph(input_dict["id"], node_list, link_list, sap_list, fogs)


class PhysicalLink(Link):
    """

    """

    def __init__(self, node1, node2, id=None, delay=0, bandwidth=0, mapped_virtual_links=None):
        super(self.__class__, self).__init__(id, "PhysicalLink")

        self.delay = delay
        self.bandwidth = {'available': bandwidth, 'max': bandwidth}

        # mapped_virtual_links contains VirtualLink objects
        if mapped_virtual_links is None:
            mapped_virtual_links = []
        self.mapped_virtual_links = mapped_virtual_links

        self.node1 = node1
        self.node2 = node2
