import networkx as nx
from graph_classes import ServiceGraph, VNF, VirtualLink, SAP, PhysicalNode, ResourceGraph, Fog, PhysicalLink
import topology_gen
# from simulator import Simulator as dark
import dark
import copy
import random
import simulator


class NoCoreable(Exception):
    def __init__(self, msg):
        self.message = msg

    def __str__(self):
        return repr(self.value)


class NoNodeInSameFog(Exception):
    def __init__(self, msg):
        self.message = msg

    def __str__(self):
        return repr(self.value)


class NoCompatibleFog(Exception):
    def __init__(self, msg):
        self.message = msg

    def __str__(self):
        return repr(self.value)


class MigratingNotPossible(Exception):
    def __init__(self, msg):
        self.message = msg

    def __str__(self):
        return repr(self.value)


class DARKOrchestrator:
    """

    """

    def __init__(self, resource_graph=None, delay_matrix=None, migrate_cost=1, alpha=1, cpu_limit=10,
                 rollback_level=10):
        """

        :param resource_graph:
         :type resource_graph: ResourceGraph
        """
        self.migrate_cost = migrate_cost
        if resource_graph is None:
            resource_graph = topology_gen.generate_topology()
        self.__resource_graph = resource_graph
        self._running = copy.deepcopy(self.__resource_graph)
        self.__previous_resource_graph = None
        self._delay_matrix = delay_matrix

        self._core_network = None
        self._core_clouds = []
        for r in self._running.nodes:
            if r.type == "core_network":
                self._core_network = r
            if r.type == "core_cloud":
                self._core_clouds.append(r)
        self._previous_mappings = []
        self.service_graphs = []
        self._actual_service_graph = None
        self.alpha = alpha
        self.expense = 0
        self.cpu_limit = cpu_limit
        self.rollback_level = rollback_level
        self.mig_expense = 0
        self.strategy = 0
        # TODO: Should come from config
        self.corable_delay_limit = 100

    def MAP(self, service_graph, disable_migrating, choose_strategy=0):
        """

        :param service_graph:
         :type service_graph: ServiceGraph
        :return:
        """
        self.strategy = choose_strategy
        self._running = copy.deepcopy(self.__resource_graph)
        self._core_clouds = []
        for r in self._running.nodes:
            if r.type == "core_network":
                self._core_network = r
            if r.type == "core_cloud":
                self._core_clouds.append(r)
        everything_ok = True
        self._actual_service_graph = service_graph
        # service_graph backup
        service_graphs_backup = copy.deepcopy(self.service_graphs)
        self.service_graphs.append(service_graph)
        mapping = {'service_id': service_graph.id, 'mapping': []}
        mapped_vnodes = []
        self.expense = 0
        self.mig_expense = 0
        map_list = self._order_service_graph(service_graph)
        mapped_vnodes.append(next(x[0] if isinstance(x[0], SAP) else x[1] for x in map_list).id)
        i = 0
        rollback_num = 0
        need_migrate = False
        max_i = 0
        allow_migrate = False
        changed_sgs = []

        while i < len(map_list):
            previous_element, min_delay_link, actual_element, retry = map_list[i]
            service_graph = next(x for x in self.service_graphs if x.id == service_graph.id)
            self._actual_service_graph = service_graph
            if not isinstance(previous_element, SAP):
                previous_element = self._get_vnf_from_id(previous_element.id)
                if previous_element != map_list[i][0]:
                    tuple_to_list = list(map_list[i])
                    tuple_to_list[0] = previous_element
                    map_list[i] = tuple(tuple_to_list)
            if not isinstance(actual_element, SAP):
                actual_element = self._get_vnf_from_id(actual_element.id)
                if actual_element != map_list[i][2]:
                    tuple_to_list = list(map_list[i])
                    tuple_to_list[2] = actual_element
                    map_list[i] = tuple(tuple_to_list)
                if actual_element.mapped_to is not None:
                    mapped_vnodes.append(actual_element.id)
                    for i in range(len(service_graph.VNFS)):
                        if service_graph.VNFS[i].id == actual_element.id:
                            service_graph.VNFS[i] = actual_element

            if min_delay_link.node1 in mapped_vnodes and min_delay_link.node2 in mapped_vnodes:
                if isinstance(previous_element, SAP):
                    previous_element_host = previous_element.id
                else:
                    previous_element_host = previous_element.mapped_to
                if isinstance(actual_element, SAP):
                    actual_element_host = actual_element.id
                else:
                    actual_element_host = actual_element.mapped_to
                length, path = self._get_shortest_path_and_length(previous_element_host, actual_element_host)
                if min_delay_link.required_delay < self.corable_delay_limit:
                    for prev_map in self._previous_mappings:
                        if prev_map['service_id'] == actual_element.service_graph:
                            for y in prev_map['mapping']:
                                if y['vnf'].id == actual_element.id:
                                    y['coreable'] = False
                # FIXME: Bandwidth check
                if length <= min_delay_link.required_delay:
                    self._map_virtual_link(min_delay_link, service_graph)
                else:
                    need_migrate = True
                    allow_migrate = True
            else:
                if isinstance(actual_element, VNF):
                    try:
                        vnf_mapping = self._map_vnf(previous_element, actual_element, min_delay_link, retry)
                        self._map_virtual_link(min_delay_link, service_graph)
                        mapping['mapping'].append(vnf_mapping)
                        mapped_vnodes.append(actual_element.id)
                    except Exception as e:
                        if 'RETRY' not in e.message and 'COMPATIBLE NODE' not in e.message:
                            dark.log(e.message, 'ERROR')
                        # ROLLBACK OR MIGRATE
                        if 'RETRY' in e.message and not isinstance(previous_element, SAP):
                            t = list(map_list[i])
                            t[3] = 0
                            map_list[i] = tuple(t)
                            for j in range(len(map_list)):
                                if map_list[j][2].id == previous_element.id:
                                    if isinstance(map_list[j][0], SAP):
                                        need_migrate = True
                                        if i != max_i:
                                            for k in range(i, -1, -1):
                                                self._increase_bandwidth_previous_links(map_list[k][0],
                                                                                        map_list[k][2])
                                                if k > 0:
                                                    self._clear_previous_mapping(map_list[k][0], mapping)
                                            i = -1
                                            mapped_vnodes = [self._actual_service_graph.saps[0].id]
                                        else:
                                            allow_migrate = True
                                    elif (not need_migrate or i != max_i) and rollback_num < self.rollback_level:
                                        self._increase_bandwidth_previous_links(previous_element, actual_element)
                                        self._clear_previous_mapping(previous_element, mapping)
                                        t = list(map_list[j])
                                        t[3] += 1
                                        map_list[j] = tuple(t)
                                        i = j - 1
                                        if previous_element.id in mapped_vnodes:
                                            mapped_vnodes.remove(previous_element.id)
                                        rollback_num += 1
                                    else:
                                        need_migrate = True
                                        if i != max_i:
                                            for k in range(i, -1, -1):
                                                self._increase_bandwidth_previous_links(map_list[k][0],
                                                                                        map_list[k][2])
                                                if k > 0:
                                                    self._clear_previous_mapping(map_list[k][0], mapping)
                                            i = -1
                                            mapped_vnodes = [self._actual_service_graph.saps[0].id]
                                        else:
                                            allow_migrate = True
                                    break
                        elif not isinstance(previous_element, SAP):
                            succ_put_away = self._try_put_away_previous_vnf(previous_element, actual_element, mapping,
                                                                            min_delay_link)
                            if succ_put_away:
                                try:
                                    vnf_mapping = self._map_vnf(previous_element, actual_element, min_delay_link, retry)
                                    self._map_virtual_link(min_delay_link, service_graph)
                                    mapping['mapping'].append(vnf_mapping)
                                    mapped_vnodes.append(actual_element.id)
                                except:
                                    succ_put_away = False
                            if not succ_put_away:
                                if rollback_num < self.rollback_level:
                                    for j in range(len(map_list)):
                                        if map_list[j][2].id == previous_element.id:
                                            if isinstance(map_list[j][0], SAP):
                                                need_migrate = True
                                                if i != max_i:
                                                    for k in range(i, -1, -1):
                                                        t = list(map_list[k])
                                                        t[3] = 0
                                                        map_list[k] = tuple(t)
                                                        self._increase_bandwidth_previous_links(map_list[k][0],
                                                                                                map_list[k][2])
                                                        if k > 0:
                                                            self._clear_previous_mapping(map_list[k][0], mapping)
                                                    i = -1
                                                    mapped_vnodes = [self._actual_service_graph.saps[0].id]
                                                else:
                                                    allow_migrate = True
                                            else:
                                                self._increase_bandwidth_previous_links(previous_element,
                                                                                        actual_element)
                                                self._clear_previous_mapping(previous_element, mapping)
                                                t = list(map_list[j])
                                                t[3] += 1
                                                map_list[j] = tuple(t)
                                                i = j - 1
                                                if previous_element.id in mapped_vnodes:
                                                    mapped_vnodes.remove(previous_element.id)
                                                rollback_num += 1
                                            break
                                else:
                                    need_migrate = True
                                    allow_migrate = True
                        else:
                            need_migrate = True
                            if i != max_i:
                                for k in range(i, -1, -1):
                                    t = list(map_list[k])
                                    t[3] = 0
                                    map_list[k] = tuple(t)
                                    self._increase_bandwidth_previous_links(map_list[k][0],
                                                                            map_list[k][2])
                                    if k > 0:
                                        self._clear_previous_mapping(map_list[k][0], mapping)
                                i = -1
                                mapped_vnodes = [self._actual_service_graph.saps[0].id]
                            else:
                                allow_migrate = True
                else:
                    # THIS MEANS THE ACTUAL ELEMENT IS A SAP
                    phy_node = self._get_phy_node_from_id(actual_element.id)
                    l, p = self._get_shortest_path_and_length(self._get_phy_node_from_id(previous_element.mapped_to),
                                                              phy_node)
                    l = self._delay_matrix[
                        self._get_fog_from_phy_node(self._get_phy_node_from_id(previous_element.mapped_to)).id][
                        self._get_fog_from_phy_node(phy_node).id]
                    # TODO: BANDWIDTH CHECK
                    if l > min_delay_link.required_delay:
                        # We have to put the previous VNF away ---------------------------------------------------------
                        succ_put_away = self._try_put_away_previous_vnf(previous_element, actual_element, mapping,
                                                                        min_delay_link)
                        if not succ_put_away:
                            if rollback_num < self.rollback_level:
                                for j in range(len(map_list)):
                                    if map_list[j][2].id == previous_element.id:
                                        if isinstance(map_list[j][0], SAP):
                                            need_migrate = True
                                            if i != max_i:
                                                for k in range(i, -1, -1):
                                                    t = list(map_list[k])
                                                    t[3] = 0
                                                    map_list[k] = tuple(t)
                                                    self._increase_bandwidth_previous_links(map_list[k][0],
                                                                                            map_list[k][2])
                                                    if k > 0:
                                                        self._clear_previous_mapping(map_list[k][0], mapping)
                                                i = -1
                                                mapped_vnodes = [self._actual_service_graph.saps[0].id]
                                            else:
                                                allow_migrate = True
                                        else:
                                            self._increase_bandwidth_previous_links(previous_element, actual_element)
                                            self._clear_previous_mapping(previous_element, mapping)
                                            t = list(map_list[j])
                                            t[3] += 1
                                            map_list[j] = tuple(t)
                                            i = j - 1
                                            if previous_element.id in mapped_vnodes:
                                                mapped_vnodes.remove(previous_element.id)
                                            rollback_num += 1
                                        break
                            else:
                                need_migrate = True
                                if i != max_i:
                                    for k in range(i, -1, -1):
                                        t = list(map_list[k])
                                        t[3] = 0
                                        map_list[k] = tuple(t)
                                        self._increase_bandwidth_previous_links(map_list[k][0],
                                                                                map_list[k][2])
                                        if k > 0:
                                            self._clear_previous_mapping(map_list[k][0], mapping)
                                    i = -1
                                    mapped_vnodes = [self._actual_service_graph.saps[0].id]
                                else:
                                    allow_migrate = True
                                    # ----------------------------------------------------------------------------------
            if need_migrate and allow_migrate:
                try:
                    if isinstance(actual_element, SAP):
                        for j in range(len(map_list)):
                            if map_list[j][2].id == previous_element.id:
                                previous_element, min_delay_link, actual_element, retry = map_list[j]
                    vnf_mapping, ex, actual_element, previous_element, changed_sg_id = self._migrate(actual_element,
                                                                                                     previous_element,
                                                                                       self._previous_mappings,
                                                                                       disable_migrating)
                    if all(i for i in changed_sgs if i.id != changed_sg_id):
                        changed_sgs.append(self._get_service_graph_from_id(changed_sg_id))
                    service_graph = self.service_graphs[-1]
                    self.mig_expense += ex
                    mapping['mapping'].append(vnf_mapping)
                    mapped_vnodes.append(actual_element.id)
                    rollback_num = 0
                    need_migrate = False
                    allow_migrate = False
                    map_list[i][1].mapped_to = [x.id for x in self._running.links if
                                                map_list[i][1].id in x.mapped_virtual_links]
                    map_list[i][2].mapped_to = actual_element.mapped_to
                except Exception as e:
                    service_graph = self.service_graphs[-1]
                    if not isinstance(e, NoCoreable) and not \
                            isinstance(e, MigratingNotPossible) and not \
                            isinstance(e, NoCompatibleFog):
                        dark.log(e.message, 'WARNING')
                    everything_ok = False
                    break
            if everything_ok:
                i += 1
                if i > max_i:
                    max_i = i
            else:
                break
        sum_mapped_CPU = 0
        new_service = None
        if everything_ok:
            self._patch_mapping(mapping, service_graph)

            for sc in self._previous_mappings:
                service = self._get_service_graph_from_id(sc["service_id"])
                for vnf in service.VNFS:
                    sum_mapped_CPU += vnf.required_CPU

            new_service = self.service_graphs[-1]
        else:
            self.service_graphs = service_graphs_backup
        return everything_ok, self.expense, self.__resource_graph, sum_mapped_CPU, new_service, changed_sgs

    def __validate_mappings_in_case_of_using_chains(self, resource_graph, previous_resource_graph):
        # Check mapped service graphs --------------------------------------------------------------------------
        for prev_sc in self._previous_mappings:
            sc = self._get_service_graph_from_id(prev_sc["service_id"])
            for vlink in sc.VLinks:

                # Check network requirements
                req_bandwidth = vlink.required_bandwidth
                req_delay = vlink.required_delay
                phy_delay_path = 0
                fogs = set()
                for phylink_id in vlink.mapped_to:
                    phylink = next(x for x in resource_graph.links if x.id == phylink_id)
                    if vlink.id not in phylink.mapped_virtual_links:
                        return False, "vlink is not among the mapped vlinks of the physical link"
                    if (phylink.bandwidth["available"] + req_bandwidth) < req_bandwidth:
                        return False, "Phy link: '" + str(phylink.id) + "' has no available bandwidth (" + str(
                            phylink.bandwidth["available"] + req_bandwidth) + ") enough for the req (" + str(
                            req_bandwidth) + ") of mapped vlink:'" + str(vlink.id) + "'!"
                    if ("NETWORK" not in phylink.node1) and ("NETWORK" not in phylink.node2):
                        phy_delay_path += phylink.delay
                    else:
                        if "NETWORK" in phylink.node1:
                            fog = self._get_fog_from_phy_node(phylink.node2, for_validate=True)
                            fogs.add(fog.id)
                        else:
                            fog = self._get_fog_from_phy_node(phylink.node1, for_validate=True)
                            fogs.add(fog.id)
                fogs = list(fogs)
                if len(fogs) == 2:
                    phy_delay_path += self._delay_matrix[fogs[0]][fogs[1]]

                if phy_delay_path > req_delay:
                    return False, "Delay is bigger than required!"
                # Check resource requirements
                vnf1_id = vlink.node1
                vnf2_id = vlink.node2
                for vnf_id in [vnf1_id, vnf2_id]:
                    if not self._is_SAP_from_id(vnf_id):
                        vnf = self._get_vnf_from_id(vnf_id)
                        try:
                            phy_node = next(
                                x for x in resource_graph.nodes + resource_graph.saps if x.id == vnf.mapped_to)
                        except:
                            pass
                        if vnf.id not in phy_node.mapped_VNFS:
                            return False, "VNF is not among the mapped VNFS inside the physical node"
                        if phy_node.CPU["available"] + vnf.required_CPU < vnf.required_CPU:
                            return False, "Phy node doesn't contain free CPU enough"
                        if phy_node.RAM["available"] + vnf.required_RAM < vnf.required_RAM:
                            return False, "Phy node doesn't contain free RAM enough"
                        if phy_node.STORAGE["available"] + vnf.required_STORAGE < vnf.required_STORAGE:
                            return False, "Phy node doesn't contain free STORAGE enough"
        # -------------------------------------------------------------------------------------------------
        # Check links and nodes of resource graphs --------------------------------------------------------
        for phy_link in resource_graph.links:
            if phy_link.bandwidth['available'] < 0:
                return False, "On physical link: '" + str(
                    phy_link.id) + "' the available bandwidth is below than 0!"
            if phy_link.bandwidth['available'] > phy_link.bandwidth['max']:
                # TODO: Sure is it good if the cloud links are not decreased?
                if not self._is_cloud_link(phy_link):
                    return False, "On physical link: '" + str(
                        phy_link.id) + "' the available bandwidth is greater than the theoretical maximum!"
        for phy_node in resource_graph.nodes:
            if phy_node.CPU["available"] < 0:
                return False, "Something went wrong"
            if phy_node.RAM["available"] < 0:
                return False, "Something went wrong"
            if phy_node.STORAGE["available"] < 0:
                return False, "Something went wrong"
        if self.__previous_resource_graph is not None:
            for phy_link in resource_graph.links:
                prev_phy_link = next(x for x in self.__previous_resource_graph.links if phy_link.id == x.id)
                sum_changed_bandwidth = 0
                # if phy_link is not an inside fog link and not cloud link
                if ("NETWORK" in phy_link.node1) or ("NETWORK" in phy_link.node2):
                    if set(phy_link.mapped_virtual_links) != set(prev_phy_link.mapped_virtual_links):
                        added_vlink_ids = []
                        deleted_vlink_ids = []
                        for vlink in phy_link.mapped_virtual_links:
                            if vlink not in prev_phy_link.mapped_virtual_links:
                                added_vlink_ids.append(vlink)
                        for vlink in prev_phy_link.mapped_virtual_links:
                            if vlink not in phy_link.mapped_virtual_links:
                                deleted_vlink_ids.append(vlink)
                        for vlink in added_vlink_ids:
                            sum_changed_bandwidth += self._get_virtual_link_from_id(vlink).required_bandwidth
                        for vlink in deleted_vlink_ids:
                            sum_changed_bandwidth -= self._get_virtual_link_from_id(vlink).required_bandwidth
                        if not (phy_link.bandwidth["available"] == (
                                    prev_phy_link.bandwidth["available"] - sum_changed_bandwidth) or \
                                    phy_link.bandwidth["available"] == (
                                            prev_phy_link.bandwidth["available"] + sum_changed_bandwidth)):
                            return False, "The available BW of a phylink is not equal with the available BW from " \
                                          "the previous iterate + changed BW!"
                    if phy_link.bandwidth["available"] != prev_phy_link.bandwidth["available"]:
                        if set(phy_link.mapped_virtual_links) == set(prev_phy_link.mapped_virtual_links):
                            return False, "Mapped virtual links were not changed in phylink:'" + str(
                                phy_link.id) + "' however the available bandwidth did!"
                        else:
                            pass

            for phy_node in resource_graph.nodes:
                prev_phy_node = next(x for x in self.__previous_resource_graph.nodes if phy_node.id == x.id)
                sum_changed_CPU = 0
                sum_changed_RAM = 0
                sum_changed_STORAGE = 0
                if phy_node.mapped_VNFS != prev_phy_node.mapped_VNFS:
                    added_vnf_ids = []
                    deleted_vnf_ids = []
                    for vnf in phy_node.mapped_VNFS:
                        if vnf not in prev_phy_node.mapped_VNFS:
                            added_vnf_ids.append(vnf)
                    for vnf in prev_phy_node.mapped_VNFS:
                        if vnf not in phy_node.mapped_VNFS:
                            deleted_vnf_ids.append(vnf)
                    for vnf in added_vnf_ids:
                        sum_changed_CPU += self._get_vnf_from_id(vnf).required_CPU
                        sum_changed_RAM += self._get_vnf_from_id(vnf).required_RAM
                        sum_changed_STORAGE += self._get_vnf_from_id(vnf).required_STORAGE
                    for vnf in deleted_vnf_ids:
                        sum_changed_CPU -= self._get_vnf_from_id(vnf).required_CPU
                        sum_changed_RAM -= self._get_vnf_from_id(vnf).required_RAM
                        sum_changed_STORAGE -= self._get_vnf_from_id(vnf).required_STORAGE
                    if not (phy_node.CPU["available"] == (
                                                          prev_phy_node.CPU["available"] - sum_changed_CPU) or
                                                          phy_node.CPU["available"] == (
                                                          prev_phy_node.CPU["available"] + sum_changed_CPU)):
                        return False, "Number of mapped vnfs was changed on physical node:'" + str(
                            phy_node.id) + "' however the number of available CPUs of phy node was not!"
                    if not (phy_node.RAM["available"] == (
                                                          prev_phy_node.RAM["available"] - sum_changed_RAM) or
                                                          phy_node.RAM["available"] == (
                                                          prev_phy_node.RAM["available"] + sum_changed_RAM)):
                        return False, "Something went wrong"
                    if not (phy_node.STORAGE["available"] == (
                                                            prev_phy_node.STORAGE["available"] - sum_changed_STORAGE) or
                                                            phy_node.STORAGE["available"] == (
                                                            prev_phy_node.STORAGE["available"] + sum_changed_STORAGE)):
                        return False, "Something went wrong"

                if phy_node.CPU["available"] != prev_phy_node.CPU["available"]:
                    if phy_node.mapped_VNFS == prev_phy_node.mapped_VNFS:
                        return False, "Something went wrong"

                if phy_node.RAM["available"] != prev_phy_node.RAM["available"]:
                    if phy_node.mapped_VNFS == prev_phy_node.mapped_VNFS:
                        return False, "Something went wrong"

                if phy_node.STORAGE["available"] != prev_phy_node.STORAGE["available"]:
                    if phy_node.mapped_VNFS == prev_phy_node.mapped_VNFS:
                        return False, "Something went wrong"

        self.__previous_resource_graph = copy.deepcopy(resource_graph)
        # -------------------------------------------------------------------------------------------------
        return True, "Everything is awesome :)"

    def _clear_previous_mapping(self, previous_element, mapping):
        self._decrease_node_resource(previous_element.mapped_to, previous_element.required_CPU * -1,
                                     previous_element.required_RAM * -1,
                                     previous_element.required_STORAGE * -1)
        previous_element.mapped_to = None
        clear_element = next(x for x in mapping['mapping'] if x['vnf'].id == previous_element.id)
        mapping['mapping'].remove(clear_element)

    def _map_vnf(self, previous_element, actual_element, min_delay_link, retry):
        compatible_nodes, contains_core = self._get_compatible_nodes_for_vnf_v2(previous_element,
                                                                                actual_element, min_delay_link)
        dark.log('COMPATIBLE NODES FOR VNF: {} {}'.format(actual_element.id, [x.id for x in compatible_nodes]),
                          'DEBUG')
        if len(compatible_nodes) > 0:
            compatible_nodes = self.choose_from_available_nodes(compatible_nodes, actual_element, previous_element)
            if len(compatible_nodes) <= retry:
                raise Exception('RETRY HIGHER THAN NUMBER OF NODES')
            the_chosen_one = compatible_nodes[retry]
            dark.log('CHOSEN PHYSICAL NODE {}'.format(the_chosen_one), 'DEBUG')
            return_dict = {'vnf': actual_element, 'mapping_nodes': compatible_nodes,
                           'chosen': the_chosen_one, 'previous': previous_element,
                           'coreable': contains_core}
            actual_element.mapped_to = the_chosen_one
            self._decrease_node_resource(the_chosen_one, actual_element.required_CPU,
                                         actual_element.required_RAM, actual_element.required_STORAGE)
            if not isinstance(previous_element, SAP):
                prev = self._get_phy_node_from_id(previous_element.mapped_to)
            else:
                prev = previous_element
            return return_dict
        else:
            raise Exception('NO COMPATIBLE NODE FOUND')

    def nova_scheduler(self, service_graph, strategy):
        self._running = copy.deepcopy(self.__resource_graph)
        map_list = self._order_service_graph(service_graph)
        mapped_vnodes = []
        mapped_vnodes.append(next(x[0] if isinstance(x[0], SAP) else x[1] for x in map_list).id)
        i = 0
        sum_mapped_CPU = 0
        mapping = {'service_id': service_graph.id, 'mapping': []}
        sum_d = 0
        for p, l, a, r in map_list:
            sum_d += l.required_delay
        while i < len(map_list):
            previous_element, min_delay_link, actual_element, retry = map_list[i]
            if isinstance(actual_element, SAP):
                break
            compatible_nodes = []
            # DUMB NOVA
            if strategy == 1:
                compatible_nodes = self._filter_physical_nodes_by_resource(actual_element)
            # SMARTER NOVA
            if strategy == 2:
                compatible_nodes = self._filter_physical_nodes_by_resource(actual_element)
                for n in self._running.nodes:
                    dd = 0
                    if n.fog_cloud is not None and n in compatible_nodes:
                        l, path = self._get_shortest_path_and_length(mapped_vnodes[0], n)
                        for j in range(len(path)-1):
                            ll = self._get_link_between_two_phy_node(path[j], path[j+1])
                            if 'NETWORK' not in ll.node1 and 'NETWORK' not in ll.node2:
                                dd += ll.delay
                        if dd+self._delay_matrix[self._get_fog_from_phy_node(mapped_vnodes[0]).id][n.fog_cloud] > sum_d:
                            compatible_nodes.remove(n)
            # MORE SMARTER NOVA
            if strategy == 3:
                compatible_nodes = self._filter_physical_nodes_by_resource(actual_element)
                for n in self._running.nodes:
                    dd = 0
                    if n.fog_cloud is not None and n in compatible_nodes:
                        l, path = self._get_shortest_path_and_length(mapped_vnodes[0], n)
                        for j in range(len(path) - 1):
                            ll = self._get_link_between_two_phy_node(path[j], path[j + 1])
                            if 'NETWORK' not in ll.node1 and 'NETWORK' not in ll.node2:
                                dd += ll.delay
                        if dd + self._delay_matrix[self._get_fog_from_phy_node(mapped_vnodes[0]).id][
                            n.fog_cloud] > map_list[i][1].required_delay:
                            compatible_nodes.remove(n)
            if len(compatible_nodes) > 0:
                compatible_nodes = self.choose_for_nova(compatible_nodes)
                the_chosen_one = compatible_nodes[0]
                dark.log('CHOSEN PHYSICAL NODE {}'.format(the_chosen_one), 'DEBUG')
                return_dict = {'vnf': actual_element, 'mapping_nodes': compatible_nodes,
                               'chosen': the_chosen_one, 'previous': previous_element}
                actual_element.mapped_to = the_chosen_one
                # -----------------------------------------------------------------------------------------------------
                if not isinstance(previous_element, SAP):
                    fog2 = self._get_fog_from_phy_node(previous_element.mapped_to)
                else:
                    fog2 = self._get_fog_from_phy_node(previous_element)
                fog1 = self._get_fog_from_phy_node(the_chosen_one)
                gw1 = self._get_core_gw(fog1)
                gw2 = self._get_core_gw(fog2)
                if min_delay_link.required_delay < self._delay_matrix[fog1.id][fog2.id]:
                    dark.log("DELAY ERROR", "INFO")
                    return False, 0, self.__resource_graph, sum_mapped_CPU
                l1 = self._get_link_between_two_phy_node(self._core_network, gw1)
                l2 = self._get_link_between_two_phy_node(self._core_network, gw2)
                if min_delay_link.required_bandwidth > l1.bandwidth['available'] or min_delay_link.required_bandwidth > \
                        l2.bandwidth['available']:
                        dark.log("BW ERROR", "INFO")
                        return False, 0, self.__resource_graph, sum_mapped_CPU
                # -----------------------------------------------------------------------------------------------------
                l1.bandwidth['available'] -= min_delay_link.required_bandwidth
                l2.bandwidth['available'] -= min_delay_link.required_bandwidth
                self._decrease_node_resource(the_chosen_one, actual_element.required_CPU,
                                             actual_element.required_RAM, actual_element.required_STORAGE)
                rg_node = next(x for x in self._running.nodes if the_chosen_one == x.id)
                if actual_element.id not in rg_node.mapped_VNFS:
                    rg_node.mapped_VNFS.append(actual_element.id)
                mapping['mapping'].append(return_dict)
                i += 1
            else:
                dark.log("NO COMPATIBLE NODES", "INFO")
                return False, 0, self.__resource_graph, sum_mapped_CPU
        self._previous_mappings.append(mapping)
        self.service_graphs.append(service_graph)
        self.__resource_graph = self._running
        self._running = None
        for sc in self._previous_mappings:
            service = self._get_service_graph_from_id(sc["service_id"])
            for vnf in service.VNFS:
                sum_mapped_CPU += vnf.required_CPU
        return True, 0, self.__resource_graph, sum_mapped_CPU

    def choose_for_nova(self, compatible_nodes):
        ram_mult = 1.0
        disk_mult = 1.0
        nodes_with_weight = []
        for node in compatible_nodes:
            w = (float(node.RAM['available']) / float(node.RAM['max'])) * ram_mult + \
                (float(node.STORAGE['available']) / float(node.STORAGE['max'])) * disk_mult
            nodes_with_weight.append((node, w))
        compatible_nodes = [s[0].id for s in sorted(nodes_with_weight, key=lambda k: k[1], reverse=True)]
        return compatible_nodes

    def _check_previous_vlinks(self, previous_element, mn):
        """

        :param previous_element:
        :return:
        """
        for vl in self._actual_service_graph.VLinks:
            vn = None
            if vl.node1 == previous_element.id:
                vn = self._get_vnf_from_id(vl.node2)
            elif vl.node2 == previous_element.id:
                vn = self._get_vnf_from_id(vl.node1)
            if vn is not None and vn.mapped_to is not None:
                length, path = self._get_shortest_path_and_length(mn, self._get_phy_node_from_id(vn.mapped_to))
                length = self._delay_matrix[self._get_fog_from_phy_node(mn).id][
                    self._get_fog_from_phy_node(self._get_phy_node_from_id(vn.mapped_to)).id]
                if length > vl.required_delay:
                    return False
        return True

    def _try_put_away_previous_vnf(self, previous_element, actual_element, mapping, min_delay_link):
        """

        :param previous_element:
        :param mapping:
        :param min_delay_link:
        :return:
        """
        previous_mapping = next(x for x in mapping['mapping'] if x['vnf'].id == previous_element.id)
        succ_remap = False
        prev_map_node = previous_mapping['chosen']
        all_good = True
        if isinstance(actual_element, SAP):
            phy_node = self._get_phy_node_from_id(actual_element.id)
            for mn in previous_mapping['mapping_nodes']:
                if mn != previous_mapping['chosen']:
                    all_good = self._check_previous_vlinks(previous_element, mn)
                    if all_good:
                        ll, pp = self._get_shortest_path_and_length(mn, phy_node)
                        ll = self._delay_matrix[self._get_fog_from_phy_node(mn).id][
                            self._get_fog_from_phy_node(phy_node).id]
                        if ll <= min_delay_link.required_delay:
                            succ_remap = True
                            self._decrease_node_resource(prev_map_node, previous_element.required_CPU * -1,
                                                         previous_element.required_RAM * -1,
                                                         previous_element.required_STORAGE * -1)
                            self._increase_bandwidth_previous_links(previous_element, actual_element)
                            previous_element.mapped_to = mn
                            previous_mapping['chosen'] = mn
                            vlinks = self._get_virtual_links_from_vnf(previous_element)
                            for link in vlinks:
                                if len(link.mapped_to) > 0:
                                    self._map_virtual_link(link, self._actual_service_graph)
                            break
        else:
            for mn in previous_mapping['mapping_nodes']:
                if mn != previous_mapping['chosen']:
                    all_good = self._check_previous_vlinks(previous_element, mn)
                    if all_good:
                        prev_copy = copy.deepcopy(previous_element)
                        prev_copy.mapped_to = mn
                        com_nodes, contains_core = self._get_compatible_nodes_for_vnf_v2(prev_copy, actual_element,
                                                                                         min_delay_link)
                        if len(com_nodes) > 0:
                            succ_remap = True
                            self._decrease_node_resource(prev_map_node, previous_element.required_CPU * -1,
                                                         previous_element.required_RAM * -1,
                                                         previous_element.required_STORAGE * -1)
                            self._increase_bandwidth_previous_links(previous_element, actual_element)
                            previous_element.mapped_to = mn
                            previous_mapping['chosen'] = mn
                            self._decrease_node_resource(mn, previous_element.required_CPU,
                                                         previous_element.required_RAM,
                                                         previous_element.required_STORAGE)

                            vlinks = self._get_virtual_links_from_vnf(previous_element)
                            for link in vlinks:
                                if len(link.mapped_to) > 0:
                                    self._map_virtual_link(link, self._actual_service_graph)
                            break
        return succ_remap

    def _increase_bandwidth_previous_links(self, previous_element, actual_element):
        vlinks = self._get_virtual_links_from_vnf(previous_element)
        for link in vlinks:
            if len(link.mapped_to) > 0:
                vn1 = next(x for x in self._actual_service_graph.VNFS + self._actual_service_graph.saps
                           if link.node1 == x.id)
                vn2 = next(x for x in self._actual_service_graph.VNFS + self._actual_service_graph.saps
                           if link.node2 == x.id)
                if vn1.id != actual_element.id and vn2.id != actual_element.id:
                    bw = link.required_bandwidth
                    if isinstance(vn1, SAP):
                        node_from = self._get_phy_node_from_id(vn1.id)
                        node_to = self._get_phy_node_from_id(vn2.mapped_to)
                    elif isinstance(vn2, SAP):
                        node_from = self._get_phy_node_from_id(vn1.mapped_to)
                        node_to = self._get_phy_node_from_id(vn2.id)
                    else:
                        node_from = self._get_phy_node_from_id(vn1.mapped_to)
                        node_to = self._get_phy_node_from_id(vn2.mapped_to)
                    self._increase_bandwidth_at_inter_fog_links(node_from, node_to, bw)
                    for phy_link_id in link.mapped_to:
                        self._get_phy_link_from_id(phy_link_id).mapped_virtual_links.remove(link.id)
                    link.mapped_to = []

    def _order_service_graph(self, service_graph):
        """

        :param service_graph:
        :return:
        """
        return_list = []
        mapped_vnodes = [service_graph.saps[0].id]
        dark.log('Mapped Virtual Nodes: {}'.format(str([x for x in mapped_vnodes])), 'DEBUG')
        mapped_vlinks = []
        dark.log('Mapped Virtual Links: {}'.format(str([x for x in mapped_vlinks])), 'DEBUG')

        available_vlinks = self._get_available_vlinks(service_graph, mapped_vnodes, mapped_vlinks)
        dark.log('AVAILABLE VIRTUAL LINKS: {}'.format(str(available_vlinks)), 'DEBUG')
        min_delay_link = available_vlinks.pop(0)
        dark.log('STRICTEST VIRTUAL LINK FOR DELAY: {} WITH DELAY {}'.format(min_delay_link.id,
                                                                             str(min_delay_link.required_delay)),
                 'DEBUG')
        dark.log('MAPPED VIRTUAL LINK LIST: {}'.format(str([x for x in mapped_vlinks])), 'DEBUG')
        while len(mapped_vnodes) != len(service_graph.saps + service_graph.VNFS) and \
                        len(mapped_vlinks) != len(service_graph.VLinks):
            if min_delay_link.node1 in mapped_vnodes and min_delay_link.node2 in mapped_vnodes:
                previous_element = next(x for x in service_graph.VNFS + service_graph.saps if
                                        x.id == min_delay_link.node1)
                actual_element = next(x for x in service_graph.VNFS + service_graph.saps if
                                      x.id == min_delay_link.node2)
                mapped_vlinks.append(min_delay_link.id)
            else:
                if min_delay_link.node1 in mapped_vnodes:
                    previous_element = next(x for x in service_graph.VNFS + service_graph.saps if
                                            x.id == min_delay_link.node1)
                    actual_element = next(x for x in service_graph.VNFS + service_graph.saps if
                                          x.id == min_delay_link.node2)
                elif min_delay_link.node2 in mapped_vnodes:
                    previous_element = next(x for x in service_graph.VNFS + service_graph.saps if
                                            x.id == min_delay_link.node2)
                    actual_element = next(x for x in service_graph.VNFS + service_graph.saps if
                                          x.id == min_delay_link.node1)
                else:
                    dark.log('MIN DELAY LINK DOESN\'T CONTAINS ANY NODE FROM MAPPED NODES', 'ERROR')
                    raise Exception
                mapped_vlinks.append(min_delay_link.id)
                mapped_vnodes.append(actual_element.id)
            return_list.append((previous_element, min_delay_link, actual_element, 0))
            available_vlinks = self._get_available_vlinks(service_graph, mapped_vnodes, mapped_vlinks)
            if len(available_vlinks) == 0:
                break
            dark.log('AVAILABLE VIRTUAL LINKS: {}'.format(str(available_vlinks)), 'DEBUG')
            min_delay_link = available_vlinks.pop(0)
        return return_list

    def choose_from_available_nodes(self, compatible_nodes, actual_element, previous_element):
        """

        :param compatible_nodes:
        :param actual_element:
        :param previous_element:
        :return:
        """
        # random
        fogs = set([x.fog_cloud for x in compatible_nodes])

        # CPU
        cpu = 0
        fog_cpu = 0
        return_node = None
        fog_list = []
        if None in fogs:
            fogs.remove(None)
        for ff in fogs:
            max_cpu = 0
            ava_cpu = 0
            c = 0
            f = self._get_fog_from_id(ff)
            for n in f.compute_nodes:
                max_cpu += self._get_phy_node_from_id(n).CPU['max']
                ava_cpu += self._get_phy_node_from_id(n).CPU['available']
            c = ava_cpu / max_cpu
            fog_list.append({'fog': ff, 'cpu': c, 'nodes': []})
        fog_list = sorted(fog_list, key=lambda l: l['cpu'], reverse=True)
        for fog in fog_list:
            for tn in compatible_nodes:
                if tn.fog_cloud == fog['fog']:
                    fog['nodes'].append({'node': tn.id, 'cpu': tn.CPU['available'] / tn.CPU['max']})
            fog['nodes'] = sorted(fog['nodes'], key=lambda l: l['cpu'], reverse=True)
        return_list = []
        for fog in fog_list:
            return_list += [x['node'] for x in fog['nodes']]
        for x in compatible_nodes:
            if x in self._core_clouds:
                if self.strategy == 0:
                    return_list.append(x.id)
                elif self.strategy == 1:
                    return_list.insert(0, x.id)
                elif self.strategy == 2 and self.cpu_limit > actual_element.required_CPU:
                    return_list.insert(0, x.id)
                elif self.strategy == 3 and self.cpu_limit < actual_element.required_CPU:
                    return_list.insert(0, x.id)
                else:
                    return_list.append(x.id)
        if isinstance(previous_element, SAP):
            prev_fog = self._get_fog_from_phy_node(previous_element)
        else:
            prev_fog = self._get_fog_from_phy_node(previous_element.mapped_to)
        if any(x in return_list for x in prev_fog.compute_nodes):
            nodes_in_prev_fog = [x for x in prev_fog.compute_nodes if x in return_list]
            for n in nodes_in_prev_fog:
                return_list.insert(0, return_list.pop(return_list.index(n)))
        return return_list

    def _get_connected_SAPS(self, vnf):
        neighbors = self._get_vnf_neighbors(vnf)
        SAP_list = []

        for neighbor in neighbors:
            if self._is_SAP_from_id(neighbor.id):
                SAP_list.append(neighbor)

        return SAP_list

    def _is_bigger_VNF(self, vnf_a, vnf_b):
        """
        Return TRUE if vnf_b is bigger than vnf_a in terms of compute resources (CPU, RAM, storage)
        :param vnf_a:
        :param vnf_b:
        :return:
        """
        if vnf_a.required_CPU <= vnf_b.required_CPU and \
           vnf_a.required_RAM <= vnf_b.required_RAM and \
           vnf_a.required_STORAGE <= vnf_b.required_STORAGE:
            return True
        else:
            return False

    def _insert_phy_node_list_according_CPU_free_spaces(self, node_list, phy_node):
        for i in range(0, len(node_list)):
            if node_list[i].CPU["available"] <= phy_node.CPU["available"]:
                node_list.insert(i, phy_node)
                return
        node_list.append(phy_node)

    def _delete_vlink_from_resource_graph(self, vlink):
        """
        Delete vlink from physical links and increase their available BWs.
        :param vlink:
        :return:
        """
        for plink_id in vlink.mapped_to:
            plink = self._get_phy_link_from_id(plink_id)
            try:
                plink.mapped_virtual_links.remove(vlink.id)
            except:
                pass
            if ("NETWORK" in plink.node1) or ("NETWORK" in plink.node2):
                plink.bandwidth["available"] += vlink.required_bandwidth
        vlink.mapped_to = []

    def _delete_vnf_from_resource_graph(self, vnf):
        """
        Delete vnf from physical node and increase its available compute resources.
        :param vnf:
        :return:
        """
        # VNF got fog?
        phy_nod, asd = self._get_physical_and_fog_from_virtual_node(vnf)
        phy_nod.mapped_VNFS.remove(vnf.id)
        phy_nod.CPU["available"] += vnf.required_CPU
        phy_nod.RAM["available"] += vnf.required_RAM
        phy_nod.STORAGE["available"] += vnf.required_STORAGE
        vnf.mapped_to = None

    def _is_phy_node_applicable_for_VNF(self, phy_node, vnf):
        """
        Return TRUE if free spaces of phy_node is enough for requirements of VNF
        """

        if vnf.required_CPU <= phy_node.CPU["available"] and \
           vnf.required_RAM <= phy_node.RAM["available"] and \
           vnf.required_STORAGE <= phy_node.STORAGE["available"]:
            return True
        return False

    def _map_vlinks_of_vnf_for_migrate(self, vnf):
        """
        Maps virtual links of the given vnf. PLEASE NOTE if the return value FALSE then the mapping was not successful.
        In this case you have to set back the used resources of links to the original.
        :param vnf:
        :return:
        """

        for vlink_id in vnf.connected_virtual_links:
            vlink = self._get_virtual_link_from_id(vlink_id)
            vlink.mapped_to = []
            sg = self._get_service_graph_from_virtual_link(vlink)
            ll = self._map_virtual_link(vlink, sg)

            sum_delay = 0
            fogs = set()
            for l_id in ll:
                pl = self._get_phy_link_from_id(l_id)
                if vlink.id not in pl.mapped_virtual_links:
                    pl.mapped_virtual_links.append(vlink_id)
                if pl.bandwidth["available"] < 0:
                    return False
                if ("NETWORK" not in pl.node1) and ("NETWORK" not in pl.node2):
                    sum_delay += pl.delay
                else:
                    if "NETWORK" in pl.node1:
                        fog = self._get_fog_from_phy_node(pl.node2)
                        fogs.add(fog.id)
                    else:
                        fog = self._get_fog_from_phy_node(pl.node1)
                        fogs.add(fog.id)
            fogs = list(fogs)
            if len(fogs) == 2:
                try:
                    sum_delay += self._delay_matrix[fogs[0]][fogs[1]]
                except Exception as e:
                    dark.log(
                        "There is no FOG:" + fogs[0] + " and FOG:" + str(fogs[1]) + " pair in the DELAY MATRIX!",
                        'ERROR', True)
                    raise Exception
            if sum_delay > vlink.required_delay:
                return False

        return True

    def _map_vlink_for_migrate(self, vlink):
        """
        Map the given virtual link. PLEASE NOTE if the return value FALSE then the mapping was not successful.
        In this case you have to set back the used resources of links to the original.
        :param vlink:
        :return:
        """
        if isinstance(vlink, str):
            vlink = self._get_virtual_link_from_id(vlink)

        vlink.mapped_to = []
        sg = self._get_service_graph_from_virtual_link(vlink)
        ll = self._map_virtual_link(vlink, sg)

        fogs = set()
        sum_delay = 0
        for l_id in ll:
            pl = self._get_phy_link_from_id(l_id)
            if vlink.id not in pl.mapped_virtual_links:
                pl.mapped_virtual_links.append(vlink.id)
            if pl.bandwidth["available"] < 0:
                return False
            if ("NETWORK" not in pl.node1) and ("NETWORK" not in pl.node2):
                sum_delay += pl.delay
            else:
                if "NETWORK" in pl.node1:
                    fog = self._get_fog_from_phy_node(pl.node2)
                    fogs.add(fog.id)
                else:
                    fog = self._get_fog_from_phy_node(pl.node1)
                    fogs.add(fog.id)
        fogs = list(fogs)
        if len(fogs) == 2:
            try:
                sum_delay += self._delay_matrix[fogs[0]][fogs[1]]
            except Exception as e:
                dark.log(
                    "There is no FOG:" + fogs[0] + " and FOG:" + str(fogs[1]) + " pair in the DELAY MATRIX!", 'ERROR',
                    True)
                raise Exception
        if sum_delay > vlink.required_delay:
            return False

        return True

    def _map_vnf_for_migrate(self, vnf, phy_node):
        """
        This method maps vnf to given phy_node.
        :param vnf:
        :param phy_node:
        :return:
        """

        prev_vnf_mapped_to = vnf.mapped_to
        phy_node.mapped_VNFS.append(vnf.id)
        vnf.mapped_to = phy_node.id
        phy_node.CPU["available"] -= vnf.required_CPU
        phy_node.RAM["available"] -= vnf.required_RAM
        phy_node.STORAGE["available"] -= vnf.required_STORAGE

        if phy_node.CPU["available"] < 0 or phy_node.RAM["available"] < 0 or phy_node.STORAGE["available"] < 0:
            phy_node.mapped_VNFS.remove(vnf.id)
            vnf.mapped_to = prev_vnf_mapped_to
            phy_node.CPU["available"] += vnf.required_CPU
            phy_node.RAM["available"] += vnf.required_RAM
            phy_node.STORAGE["available"] += vnf.required_STORAGE
            return False

        return True

    def _try_to_migrate(self, migrating_vnf, actual_vnf, phy_node_for_migrating_vnf, phy_node_for_actual_vnf,
                        previous_element):
        # del vlinks
        for vlink_id in migrating_vnf.connected_virtual_links:
            vlink = self._get_virtual_link_from_id(vlink_id)
            self._delete_vlink_from_resource_graph(vlink)

        # del vnf
        self._delete_vnf_from_resource_graph(migrating_vnf)

        # map migrating VNF
        vnf_map_return = self._map_vnf_for_migrate(migrating_vnf, phy_node_for_migrating_vnf)
        if not vnf_map_return:
            return False
        else:

            # map vlinks of migrable VNF
            vlink_map_return = self._map_vlinks_of_vnf_for_migrate(migrating_vnf)
            if not vlink_map_return:
                return False
            else:

                # Map actual_vnf
                vnf_map_return = self._map_vnf_for_migrate(actual_vnf, phy_node_for_actual_vnf)
                if not vnf_map_return:
                    return False
                else:

                    # Map vlink between actual_vnf and previous_element
                    vlink = self._get_virtual_link_between_two_vnf(actual_vnf, previous_element)
                    vlink_map_return = self._map_vlink_for_migrate(vlink)
                    if not vlink_map_return:
                        return False

                    return True

    def _migrate(self, actual_vnf, previous_element, prev_mappings, disable_migrating):
        """
        This method find one or more already mapped vnfs to migrate them to another fog infrastructure. With this
        migrating virtual compute and link resources will release from the physical resources thus the actual vnf
        be able to mapped.

        :return:
        """
        dark.log('START TRYING MIGRATE ', 'INFO')
        # Disable migrating is True when you used the orchestrator without migrating option
        if disable_migrating:
            raise RuntimeError

        # Collect corable VNFs and physical nodes contains coreable VNFs. Now corable VNFs = migratable VNFs
        corable_vnfs = []
        for req in prev_mappings:
            for vnf in req["mapping"]:
                if vnf['coreable']:
                    corable_vnfs.append(vnf["vnf"])

        if corable_vnfs == []:
            dark.log("Migrating failed. There is no corable VNF in the resource graph", "INFO")
            raise NoCoreable("Migrating failed. There is no corable VNF in the resource graph")

        temp_corable = []
        if isinstance(previous_element, SAP):
            temp_corable += [corable_vnfs.pop(corable_vnfs.index(x)) for x in corable_vnfs if
                             self._get_phy_node_from_id(x.mapped_to).fog_cloud == previous_element.fog_cloud]
        else:
            temp_corable += [corable_vnfs.pop(corable_vnfs.index(x)) for x in corable_vnfs if
                             self._get_phy_node_from_id(x.mapped_to).fog_cloud == self._get_phy_node_from_id(
                                 previous_element.mapped_to).fog_cloud]
        corable_vnfs = temp_corable+corable_vnfs

        # Find compatible fogs for migrating:
        # If the actual vnf would be mapped into these fogs then the requirements
        # between previous and actual vnf would be complianced
        fogs = []
        for vnf in corable_vnfs:
            fog = self._get_phy_node_from_id(vnf.mapped_to).fog_cloud
            if fog not in fogs:
                fogs.append(fog)

        iter=0
        vnf_iter = 0
        for vnf in corable_vnfs:

            # Step 1
            migrating_vnf = vnf
            if self._is_bigger_VNF(actual_vnf, migrating_vnf):
                if vnf_iter > 10:
                    break
                vnf_iter += 1
                possible_node_for_actual, possible_fog_for_actual = self._get_physical_and_fog_from_virtual_node(
                    migrating_vnf)

                # Step 2
                possible_nodes_for_migrable_vnf = []
                for fog in self._running.fogs:
                    for node_id in fog.compute_nodes:
                        node = self._get_phy_node_from_id(node_id)
                        if self._is_phy_node_applicable_for_VNF(node, migrating_vnf):
                            self._insert_phy_node_list_according_CPU_free_spaces(possible_nodes_for_migrable_vnf, node)

                if possible_nodes_for_migrable_vnf == []:
                    dark.log("THERE IS NO POSSIBLE NODES FOR MIGRABLE VNF", 'WARNING')

                node_iter = 0
                for node in possible_nodes_for_migrable_vnf:

                    if node_iter > 5:
                         break

                    node_iter += 1
                    iter += 1
                    dark.log("TRY"+str(iter)+":"+str(vnf_iter)+":"+str(node_iter)+" MIGRATE OPTION", 'INFO')
                    # init
                    node = next(x for x in self._running.nodes if x.id == node.id)
                    migrating_vnf = self._get_vnf_from_id(migrating_vnf.id)
                    possible_node_for_actual = self._get_phy_node_from_id(possible_node_for_actual.id)
                    actual_vnf = self._get_vnf_from_id(actual_vnf.id)

                    # Backup plans
                    copied_original_running = copy.deepcopy(self._running)
                    copied_original_sgs = copy.deepcopy(self.service_graphs)
                    try:
                        was_mig_succ = self._try_to_migrate(migrating_vnf, actual_vnf, node,
                                                            possible_node_for_actual, previous_element)
                    except Exception as e:
                        dark.log(e.message, 'ERROR')

                    if not was_mig_succ:
                        self._running = copied_original_running
                        self.service_graphs = copied_original_sgs
                    else:
                        return_dict = {'vnf': actual_vnf, 'mapping_nodes': [actual_vnf.mapped_to],
                                       'chosen': actual_vnf.mapped_to, 'previous': previous_element,
                                       'coreable': False}
                        cost = 1
                        dark.log(
                            "Migration was successful :)", 'INFO', log_traceback=False)
                        return return_dict, cost, actual_vnf, previous_element, migrating_vnf.service_graph
        dark.log("Migration was failed", 'WARNING', log_traceback=False)
        raise MigratingNotPossible("Migration was failed")

    def _get_vnf_neighbors(self, vnf):
        neighbors = []
        for vlink_id in vnf.connected_virtual_links:
            vlink = self._get_virtual_link_from_id(vlink_id)
            if vlink.node1 == vnf.id:
                if self._is_SAP_from_id(vlink.node2):
                    neighbors.append(self._get_SAP_from_id(vlink.node2))
                else:
                    neighbors.append(self._get_vnf_from_id(vlink.node2))
            elif vlink.node2 == vnf.id:
                if self._is_SAP_from_id(vlink.node1):
                    neighbors.append(self._get_SAP_from_id(vlink.node1))
                else:
                    neighbors.append(self._get_vnf_from_id(vlink.node1))

        return neighbors

    def _is_interFog_link(self, phy_link):
        """

        :param phy_link:
        :return:
        """
        if phy_link.node1 == self._core_network.id or phy_link.node2 == self._core_network.id:
            return True
        return False

    def _is_cloud_link(self, phy_link):
        """

        :param phy_link:
        :return:
        """
        if self._running is not None:
            if "cloud" in self._get_phy_node_from_id(phy_link.node1).type or "cloud" in self._get_phy_node_from_id(
                    phy_link.node2).type:
                return True
        else:
            node1 = next(x for x in self.__resource_graph.nodes + self.__resource_graph.saps if x.id == phy_link.node1)
            node2 = next(x for x in self.__resource_graph.nodes + self.__resource_graph.saps if x.id == phy_link.node2)
            if node1.type == "core_cloud" or node2.type == "core_cloud":
                return True

        return False

    def _delete_unnecessary_bws(self, deleted_bandwidth):
        # Black magic: set back the original available bandwidth (Relax, the code below will decrease it :))
        for deleted_help_structure in deleted_bandwidth:
            plink = self._get_phy_link_from_id(deleted_help_structure["from_phy_link_id"])
            plink.bandwidth["available"] += deleted_help_structure["deleted_bw"]

    def _check_link_mapping(self):
        if any(plink.bandwidth['available'] < 0 for plink in self._running.links):
            return False
        else:
            return True

    def _get_service_graph_from_virtual_link(self, link):
        if self._is_SAP_from_id(link.node1):
            return self._get_service_graph_from_id(self._get_vnf_from_id(link.node2).service_graph)
        else:
            return self._get_service_graph_from_id(self._get_vnf_from_id(link.node1).service_graph)

    def _get_SAP_from_id(self, id):
        return next(sap for sap in self.__resource_graph.saps if sap.id == id)

    def _is_SAP_from_id(self, id):
        for sap in self.__resource_graph.saps:
            if sap.id == id:
                return True
        return False

    def _get_service_graph_from_id(self, sg_id):
        return next(sg for sg in self.service_graphs if sg.id == sg_id)

    def _get_virtual_link_from_id(self, vlink_id):

        for sg in self.service_graphs:
            for vlink in sg.VLinks:
                if vlink.id == vlink_id:
                    return vlink
        return None

    def _get_phy_link_from_id(self, link_id):
        for link in self._running.links:
            if link.id == link_id:
                return link
        return None

    def _get_vnfs_from_fog(self, fog):
        vnf_id_list = []
        if isinstance(fog, str):
            fog = self._get_fog_from_id(fog)
        for phy_node in fog.compute_nodes:
            vnf_id_list += self._get_phy_node_from_id(phy_node).mapped_VNFS
        vnf_list = []
        for vnf_id in vnf_id_list:
            vnf = self._get_vnf_from_id(vnf_id)
            if vnf == None:
                return None
            vnf_list.append(vnf)
        return vnf_list

    def _get_virtual_links_from_vnf(self, vnf):
        virtual_links = []
        if isinstance(vnf, str):
            vnf = self._get_vnf_from_id(vnf)
        for l in self._actual_service_graph.VLinks:
            if l.node1 == vnf.id or l.node2 == vnf.id:
                virtual_links.append(l)
        return virtual_links

    def _map_virtual_link(self, min_delay_link, service_graph):
        """

        :param min_delay_link:
        :param service_graph:
        :return:
        """
        virtual_list = service_graph.VNFS + service_graph.saps
        vnf1, vnf2 = self.get_vnfs_from_virtual_link(min_delay_link, service_graph)
        node1, fog1 = self._get_physical_and_fog_from_virtual_node(vnf1)
        node2, fog2 = self._get_physical_and_fog_from_virtual_node(vnf2)
        length, path = self._get_shortest_path_and_length(node1, node2)
        length = self._delay_matrix[self._get_fog_from_phy_node(node1).id][self._get_fog_from_phy_node(node2).id]
        link_list = []
        for l in self._running.links:
            if min_delay_link.id in l.mapped_virtual_links:
                l.mapped_virtual_links.remove(min_delay_link.id)
        for i in range(len(path) - 1):
            phy_link = self._get_link_between_two_phy_node(path[i], path[i + 1])
            # TODO:
            phy_link.mapped_virtual_links.append(min_delay_link.id)
            link_list.append(phy_link.id)
        self._decrease_bandwidth_at_inter_fog_links(node1, node2,
                                                    min_delay_link.required_bandwidth)
        min_delay_link.mapped_to = link_list
        return link_list

    def get_vnfs_from_virtual_link(self, link, service_graph):
        """

        :param link:
        :param service_graph:
        :return:
        """
        v1 = next(x for x in service_graph.VNFS + service_graph.saps if link.node1 == x.id)
        v2 = next(x for x in service_graph.VNFS + service_graph.saps if link.node2 == x.id)
        return v1, v2

    def _decrease_node_resource(self, phy_node, cpu, ram, storage):
        """

        :param phy_node:
        :param cpu:
        :param ram:
        :param storage:
        :return:
        """
        if isinstance(phy_node, str):
            phy_node = self._get_phy_node_from_id(phy_node)
        phy_node.CPU['available'] -= cpu
        phy_node.RAM['available'] -= ram
        phy_node.STORAGE['available'] -= storage

    def _increase_bandwidth_at_inter_fog_links(self, phy_node, prev, bw):
        """

        :param phy_node:
        :param previous_element:
        :param min_delay_link:
        :return:
        """
        dark.log('INCREASE THE BANDWIDTH BETWEEN INTER FOG LINKS', 'DEBUG')
        fog_from = None
        fog_to = None
        if isinstance(phy_node, str):
            phy_node = self._get_phy_node_from_id(phy_node)
        if isinstance(prev, str):
            prev = self._get_phy_node_from_id(prev)
        physical_from = prev
        if phy_node.id == physical_from.id:
            return True
        fog_from = self._get_fog_from_id(physical_from.fog_cloud)
        fog_to = self._get_fog_from_id(phy_node.fog_cloud)
        if fog_from is not None and fog_to is not None and fog_from.id != fog_to.id:
            link_from = self._get_link_between_two_phy_node(self._get_core_gw(fog_from), self._core_network)
            link_from.bandwidth['available'] += bw
            link_to = self._get_link_between_two_phy_node(self._get_core_gw(fog_to), self._core_network)
            link_to.bandwidth['available'] += bw
        elif fog_from is None:
            link_to = self._get_link_between_two_phy_node(self._get_core_gw(fog_to), self._core_network)
            link_to.bandwidth['available'] += bw
        elif fog_to is None:
            link_to = self._get_link_between_two_phy_node(self._get_core_gw(fog_from), self._core_network)
            link_to.bandwidth['available'] += bw

    def _decrease_bandwidth_at_inter_fog_links(self, phy_node, prev, bw):
        """

        :param phy_node:
        :param prev:
        :param bw:
        :return:
        """
        dark.log('DECREASE THE BANDWIDTH BETWEEN INTER FOG LINKS', 'DEBUG')
        fog_from = None
        fog_to = None
        if isinstance(phy_node, str):
            phy_node = self._get_phy_node_from_id(phy_node)
        if isinstance(prev, str):
            prev = self._get_phy_node_from_id(prev)
        if phy_node.id == prev.id:
            return True
        fog_from = self._get_fog_from_id(prev.fog_cloud)
        fog_to = self._get_fog_from_id(phy_node.fog_cloud)

        # TODO: Sure is it good if we doesn't decrease the links from core to clouds?
        if fog_from == None and fog_to == None:
            return True

        elif fog_from is not None and fog_to is not None and fog_from.id != fog_to.id:
            link_from = self._get_link_between_two_phy_node(self._get_core_gw(fog_from), self._core_network)
            link_from.bandwidth['available'] -= bw
            link_to = self._get_link_between_two_phy_node(self._get_core_gw(fog_to), self._core_network)
            link_to.bandwidth['available'] -= bw
        elif fog_from is None:
            link_to = self._get_link_between_two_phy_node(self._get_core_gw(fog_to), self._core_network)
            link_to.bandwidth['available'] -= bw
        elif fog_to is None:
            link_to = self._get_link_between_two_phy_node(self._get_core_gw(fog_from), self._core_network)
            link_to.bandwidth['available'] -= bw

        # TODO: Sure is it good if we doesn't decrease the links from core to clouds?
        if any(x.bandwidth['available'] < 0 for x in self._running.links) or \
                any(x.bandwidth['available'] > x.bandwidth['max'] and not self._is_cloud_link(x) for x in
                    self._running.links):
            print('OOOOOPS')

    def _patch_mapping(self, mapping, service_graph):
        """

        :param mapping:
        :param service_graph:
        :return:
        """
        for m in mapping['mapping']:
            rg_node = next(x for x in self._running.nodes if m['chosen'] == x.id)
            if m["vnf"].id not in rg_node.mapped_VNFS:
                rg_node.mapped_VNFS.append(m["vnf"].id)
        for link in service_graph.VLinks:
            for physical in link.mapped_to:
                rg_link = next(x for x in self._running.links if x.id == physical)
                if link.id not in rg_link.mapped_virtual_links:
                    rg_link.mapped_virtual_links.append(link.id)
        self._previous_mappings.append(mapping)
        self.expense += self.mig_expense
        self.__resource_graph = self._running
        self._running = None

    def _get_vnf_from_id(self, id):
        """

        :param id:
        :return:
        """
        for sg in self.service_graphs:
            for vnf in sg.VNFS:
                if vnf.id == id:
                    return vnf
        return None

    def _get_phy_node_from_id(self, node_id):
        """

        :param node_id:
        :return:
        """
        try:
            return next(x for x in self._running.nodes + self._running.saps if x.id == node_id)
        except Exception as e:
            dark.log(e.message, 'ERROR', True)

    def _get_compatible_nodes_for_vnf_v2(self, previous_element, actual_element, min_delay_link):
        """

        :param previous_element:
         :type previous_element:VNF/SAP
        :param actual_element:
         :type actual_element:VNF
        :param min_delay_link:
         :type min_delay_link: VirtualLink
        :return:
        """
        good_node_list = []
        bad_indexes = set()
        nodes_complete_resource_requirements = self._filter_physical_nodes_by_resource(actual_element)
        available_fogs = set([f.fog_cloud for f in nodes_complete_resource_requirements])
        inter_fog_links = []
        link_fogs = set()
        physical_from, fog_from = self._get_physical_and_fog_from_virtual_node(previous_element)
        if fog_from is not None:
            fog_from_core_gw = self._get_core_gw(fog_from)
            from_link = self._get_link_between_two_phy_node(fog_from_core_gw, self._core_network)
        else:
            from_link = self._get_link_between_two_phy_node(self._core_network, physical_from)

        if from_link.bandwidth['available'] >= min_delay_link.required_bandwidth:
            for f in available_fogs:
                if fog_from is not None:
                    if f != fog_from.id and \
                                    self._get_link_between_two_phy_node(self._get_core_gw(f),
                                                                        self._core_network).bandwidth[
                                        'available'] < min_delay_link.required_bandwidth:
                        for i in range(len(nodes_complete_resource_requirements)):
                            if nodes_complete_resource_requirements[i].fog_cloud == f:
                                bad_indexes.add(i)
                else:
                    if self._get_link_between_two_phy_node(self._get_core_gw(f),
                                                           self._core_network).bandwidth['available'] < \
                            min_delay_link.required_bandwidth:
                        for i in range(len(nodes_complete_resource_requirements)):
                            if nodes_complete_resource_requirements[i].fog_cloud == f:
                                bad_indexes.add(i)
        else:
            for i in range(len(nodes_complete_resource_requirements)):
                if not nodes_complete_resource_requirements[i].fog_cloud or \
                        nodes_complete_resource_requirements[i].fog_cloud != fog_from:
                    bad_indexes.add(i)

        for i in range(len(nodes_complete_resource_requirements)):
            l, p = self._get_shortest_path_and_length(physical_from, nodes_complete_resource_requirements[i])
            l = self._delay_matrix[self._get_fog_from_phy_node(physical_from).id][
                self._get_fog_from_phy_node(nodes_complete_resource_requirements[i]).id]
            for k in range(len(p)-1):
                path_link = self._get_link_between_two_phy_node(p[k], p[k+1])
                if 'NETWORK' not in path_link.node1 and 'NETWORK' not in path_link.node2:
                    l += path_link.delay
            if l > min_delay_link.required_delay:
                bad_indexes.add(i)

        for i in range(len(nodes_complete_resource_requirements)):
            if i not in bad_indexes:
                good_node_list.append(nodes_complete_resource_requirements[i])
        contains_core = False
        if min_delay_link.required_delay >= self.corable_delay_limit:
            contains_core = True

        return good_node_list, contains_core

    def _get_shortest_path_and_length(self, start, end):
        """

        :param start:
        :param end:
        :return: length, path
        """
        G = nx.Graph()
        G.add_nodes_from([n.id for n in self._running.nodes])
        G.add_nodes_from([s.id for s in self._running.saps])
        G.add_weighted_edges_from([(l.node1, l.node2, l.delay) for l in self._running.links])

        if isinstance(start, str):
            start_node = start
        else:
            start_node = start.id
        if isinstance(end, str):
            end_node = end
        else:
            end_node = end.id
        return nx.bidirectional_dijkstra(G, start_node, end_node)

    def _get_phy_nodes_from_link(self, link):
        """

        :param link:
        :return:
        """
        if isinstance(link, str):
            link = next(l for l in self._running.links if l.id == link)
        n1 = next(x for x in self._running.nodes if x.id == link.node1)
        n2 = next(x for x in self._running.nodes if x.id == link.node2)
        return n1, n2

    def _get_path_from_node_to_core_network(self, physical_from):
        """

        :param physical_from:
        :return:
        """
        fog = self._get_fog_from_phy_node(physical_from)
        core_gw = self._get_core_gw(fog)
        path = []
        path.append(self._get_link_between_two_phy_node(physical_from, core_gw))
        path.append(self._get_link_between_two_phy_node(core_gw, self._core_network))
        return path

    def _get_path_from_node_to_core_cloud(self, physical_from, core_cloud_to):
        """

        :param physical_from:
        :param core_cloud_to:
        :return:
        """
        fog = self._get_fog_from_phy_node(physical_from)
        core_gw = self._get_core_gw(fog)
        path = []
        path.append(self._get_link_between_two_phy_node(physical_from, core_gw))
        path.append(self._get_link_between_two_phy_node(core_gw, self._core_network))
        path.append(self._get_link_between_two_phy_node(self._core_network, core_cloud_to))
        return path

    def _get_virtual_link_between_two_vnf(self, node1, node2):
        if not isinstance(node1, SAP):
            for x in self.service_graphs:
                for y in x.VNFS:
                    if y.id == node1.id:
                        service_graph = x
                        break
        else:
            for x in self.service_graphs:
                for y in x.VNFS:
                    if y.id == node2.id:
                        service_graph = x
                        break
        for link in service_graph.VLinks:
            if (link.node1 == node1.id and link.node2 == node2.id) or (
                            link.node1 == node2.id and link.node2 == node1.id):
                return link
        return None

    def _get_link_between_two_phy_node(self, node1, node2):
        """

        :param node1:
        :param node2:
        :return:
        """
        if not isinstance(node1, str):
            node1 = node1.id
        if not isinstance(node2, str):
            node2 = node2.id
        if isinstance(node1, str) and isinstance(node2, str):
            try:
                return next(x for x in self._running.links if (x.node1 == node1 and x.node2 == node2) or
                            (x.node1 == node2 and x.node2 == node1))
            except:
                pass

    def _get_core_gw(self, fog):
        """
        :param fog:
        :return:
        """
        if isinstance(fog, Fog):
            return next(
                self._get_phy_node_from_id(x) for x in fog.gws if 'CORE-gateway' in self._get_phy_node_from_id(x).type)
        else:
            ff = self._get_fog_from_id(fog)
            return next(
                self._get_phy_node_from_id(x) for x in ff.gws if 'CORE-gateway' in self._get_phy_node_from_id(x).type)

    def _get_sap_gw(self, fog):
        """

        :param fog:
        :return:
        """
        if isinstance(fog, Fog):
            return next(x for x in self._running.nodes if x.type == 'SAP-gateway' and x.id in fog.gws)
        else:
            ff = next(i for i in self._running.fogs if i.id == fog)
            return next(x for x in self._running.nodes if x.type == 'SAP-gateway' and x.id in ff.gws)

    def _get_fog_from_phy_node(self, physical_node, for_validate=False):
        """

        :param physical_node:
        :return:
        """

        if for_validate:
            self._running = self.__resource_graph
        if isinstance(physical_node, PhysicalNode):
            return next(x for x in self._running.fogs if physical_node.id in x.compute_nodes + x.gws + x.saps)
        elif isinstance(physical_node, str):
            return next(x for x in self._running.fogs if physical_node in x.compute_nodes + x.gws + x.saps)
        elif isinstance(physical_node, SAP):
            link = next(x for x in self._running.links if x.node1 == physical_node.id or
                        x.node2 == physical_node.id)
            if link.node1 == physical_node.id:
                return next(x for x in self._running.fogs if link.node2 in x.compute_nodes + x.gws + x.saps)
            else:
                return next(x for x in self._running.fogs if link.node1 in x.compute_nodes + x.gws + x.saps)

    def _get_physical_and_fog_from_virtual_node(self, previous_element):
        """

        :param previous_element:
        :return: phy_node, fog
        """
        fog_from = None
        if isinstance(previous_element, SAP):
            return previous_element, self._get_fog_from_id(previous_element.fog_cloud)
        else:
            physical_from = self._get_phy_node_from_id(previous_element.mapped_to)
            fog_from = self._get_fog_from_id(physical_from.fog_cloud)
        if physical_from is None:
            dark.log('COULDN\'T FIND PHYSICAL NODE', 'ERROR')
            raise Exception

        return physical_from, fog_from

    def _get_fog_from_id(self, fog_id):
        try:
            return next(x for x in self._running.fogs if x.id == fog_id)
        except Exception as e:
            dark.log(e.message, 'ERROR', True)

    def _filter_physical_nodes_by_resource(self, actual_element):
        """

        :param actual_element:
        :return:
        """
        dark.log('FILTERING PHYSICALNODES BY RESOURCES', 'DEBUG')
        nodes = [x for x in self._running.nodes if (x.CPU['available'] >= actual_element.required_CPU and
                                                    x.RAM['available'] >= actual_element.required_RAM and
                                                    x.STORAGE['available'] >= actual_element.required_STORAGE)]
        return nodes

    @staticmethod
    def _get_available_vlinks(service_graph, mapped_vnodes, mapped_vlinks):
        dark.log('GETTING AVAILABLE VIRTUAL LINKS', 'DEBUG')
        available_vlinks = []
        for element in mapped_vnodes:
            for link in service_graph.VLinks:
                if (link.node1 == element or link.node2 == element) and link.id not in mapped_vlinks:
                    available_vlinks.append(link)

        available_vlinks = sorted(available_vlinks, key=lambda l: l.required_delay, reverse=True)
        return available_vlinks

    def migrate(self):
        pass

    def delete(self):
        pass


if __name__ == '__main__':
    dark_orchestrator = DARKOrchestrator()
