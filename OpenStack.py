from __future__ import print_function
from novaclient import client as novaclient
from neutronclient.v2_0 import client as neutronclient
from glanceclient import Client as glance_client
from keystoneauth1.identity import v3
from keystoneauth1 import session
import time
import json
import requests
import ast
import sys
import os
import subprocess
import logging
import heatclient
from heatclient.client import Client as Heat_Client
from keystoneauth1 import loading
from novaclient import client
import copy
import networking_sfc
from keystoneclient.v3 import client as keystoneclient

# TODO: Reading these from config file
OS_URL = 'http://controller'
AUTH_URL = 'http://controller:35357/v3'
USERNAME = 'admin'
PASSWORD = 'openstack'
DOMAIN = 'default'
PROJECT_NAME = 'admin'
PROJECT_ID = '0060dba59d564b47b2157bd576e64e36'
NOVA_VERSION = 2
GLANCE_VERSION = 3
GLANCE_ENDPOINT = 'http://controller:9292'
CIRROS_ID = '77de9465-2ef6-4836-b05a-13b24d74e167'
VERSION = "2.5"


class OpenStack:
    """

    """

    def __init__(self, log_file=None):
        self.session = self._get_auth_session()
        self.nova = novaclient.Client(version=NOVA_VERSION, session=self.session)
        self.neutron = neutronclient.Client(session=self.session)
        self.glance = glance_client('2', session=self.session)
        self.heat = Heat_Client('1', session=self.session)
        images = self.glance.images.list()
        self.hypervisors = self.get_hypervisors()
        self.flavors = self.get_flavors()
        self.networks = self.get_networks()
        self.zones = self.nova.availability_zones.list()
        self.services = {}
        self.sfc_queue = []
        self.finished = False
        self.log_file = log_file
        self.network_id = self.set_network('DARK-net', '192.168.0.0/16')
        if log_file is not None:
            logging.basicConfig(filename=self.log_file, level=logging.INFO)

    @staticmethod
    def log(message, level):
        if level == "DEBUG":
            logging.debug(message)
        elif level == "INFO":
            logging.info(message)
        elif level == "WARNING":
            logging.warning(message)
        elif level == "ERROR":
            logging.error(message)
        elif level == "CRITICAL":
            logging.critical(message)

    def _get_auth_session(self):
        """

        :return:
        """
        loader = loading.get_plugin_loader('password')
        auth = loader.load_from_options(auth_url=AUTH_URL, username=USERNAME, password=PASSWORD,
                                        project_name=PROJECT_NAME, user_domain_name=DOMAIN,
                                        project_domain_name=DOMAIN)
        sess = session.Session(auth=auth)
        nova = client.Client(VERSION, session=sess)
        return sess

    def get_hypervisors(self):
        """

        :return:
        """
        hyper_list = self.nova.hypervisors.list()
        print([h._info['service']['host'] for h in hyper_list if h.state == 'up'])
        return hyper_list

    def get_flavors(self):
        """

        :return:
        """
        return self.nova.flavors.list()

    def set_flavor(self, name, ram, vcpus, disk):
        """

        :return:
        """

        flavor = self.nova.flavors.create(name, ram, vcpus, disk, flavorid='auto', ephemeral=0, swap=0, rxtx_factor=1.0,
                                          is_public=True)
        return flavor

    def get_networks(self):
        """

        :return:
        """
        return self.neutron.list_networks()['networks']

    def set_network(self, name, net_prefix):
        """

        :return:
        """

        network = {'name': name+"_NETWORK", 'admin_state_up': True}
        net = self.neutron.create_network({'network': network})
        subnet_body = {"subnet": {"network_id": net["network"]["id"], "ip_version": 4, "cidr": net_prefix}}
        subnet = self.neutron.create_subnet(subnet_body)
        return net["network"]["id"]

    def get_instance_status(self, id):
        servers = self.nova.servers.list(search_opts={'all_tenants': 1})
        for server in servers:
            if server.id == id:
                return server.status
        return None

    def get_physical_hypervisor_of_VNF(self,id):
        servers = self.nova.servers.list(search_opts={'all_tenants': 1})
        for server in servers:
            if server.name == id:
                return server._info['OS-EXT-SRV-ATTR:hypervisor_hostname'], server.id
        return None

    def create_instance(self, image, flavor, name, availability_zone, ports):
        """

        :return:
        """

        server = {'name': name, 'flavorRef': flavor.id, 'imageRef': image,
                  'networks': [{'port': p} for p in ports], 'availability_zone': availability_zone}
        data = {'server': server}
        header = self.session.get_auth_headers()
        header['content-type'] = 'application/json'
        response = requests.post(OS_URL+':8774/v2.1/' + PROJECT_ID + '/servers', data=json.dumps(data),
                                 headers=header, timeout=10)
        return response

    def create_port(self, network_id):
        """

        :return:
        """
        port = self.neutron.create_port(body={'port': {'network_id': network_id}})
        return port['port']

    def create_port_pair(self, port1_id, name):
        """

        :return:
        """
        portpair = self.neutron.create_port_pair(body={'port_pair': {'ingress': port1_id,
                                                                     'egress': port1_id,
                                                                     'name': name}})
        return portpair

    def create_port_pair_group(self, pp, name):
        """

        :param pp:
        :param name:
        :return:
        """
        pg = self.neutron.create_port_pair_group(body={'port_pair_group':
                                                       {'port_pairs': [pp['port_pair']['id']], 'name': name}})
        return pg

    def create_port_chain(self, port_pair_groups, name):
        """

        :param port_pair_groups:
        :param name:
        :return:
        """
        port_pair_group_ids = [pg['port_pair_group']['id'] for pg in port_pair_groups]
        pc = self.neutron.create_port_chain(body={'port_chain':
                                                  {'port_pair_groups': port_pair_group_ids, 'name': name}})
        return pc

    def create_network(self, net_name):
        """

        :param net_name:
        :return:
        """
        network = {'name': net_name, 'admin_state_up': True}
        self.neutron.create_network({'network': network})

    def create_subnet(self):
        """

        :return:
        """
        raise NotImplementedError

    def attach_network_to_router(self):
        """

        :return:
        """
        raise NotImplementedError

    def convert_topology_to_DARK_RG(self):
        """

        :return:
        """
        raise NotImplementedError

    def get_avail_zone_from_hypervisor(self, host):
        """

        :param host:
        :return:
        """
        for zone in self.zones:
            for hypervisor in zone.hosts:
                if host == hypervisor:
                    return zone.zoneName
        return None

    def get_avail_zone_from_fog(self, fog_id):
        """

        :param fog_id:
        :return:
        """
        for zone in self.zones:
            if zone.zoneName == fog_id:
                return zone.zoneName
        return None

    def load_services_from_file(self):
        """
        :return
        """
        if os.path.isfile('saved_services'):
            with open('saved_services', 'r') as f:
                return json.load(f)
        else:
            return {}

    def write_services_to_file(self, service_dict):
        """
        :return
        """
        with open('saved_services', 'w') as f:
            json.dump(service_dict, f)

    def delete_service(self, service_to_delete):
        """
        :return:
        """
        try:
            # Deleting from OpenStack
            for instance in self.services[service_to_delete]["instances"]:
                self.nova.servers.delete(instance)

            for pc in self.services[service_to_delete]["pcs"]:
                self.neutron.delete_port_chain(pc)

            for pg in self.services[service_to_delete]["pgs"]:
                self.neutron.delete_port_pair_group(pg)

            for pp in self.services[service_to_delete]["pps"]:
                self.neutron.delete_port_pair(pp)

            for port in self.services[service_to_delete]["ports"]:
                self.neutron.delete_port(port)

            for network in self.services[service_to_delete]["networks"]:
                self.neutron.delete_network(network)

            # Deleting from dictionary
            self.services.pop(service_to_delete)

            # Saving the modified dictionary to file
            self.write_services_to_file(self.services)
        except:
            pass

    def deploy(self, new_service, net_iter, changed_services, fogs):
        """

        :return:
        """
        start_deploy_timestamp = time.time()
        print("*********************************************************************************")
        print("START DEPLOY SERVICE: " + str(new_service.id))
        
        if new_service.id not in self.services:
            self.services[new_service.id] = {}
            self.services[new_service.id]["instances"] = []
            self.services[new_service.id]["pps"] = []
            self.services[new_service.id]["ports"] = []
            self.services[new_service.id]["pcs"] = []
            self.services[new_service.id]["pgs"] = []
            self.services[new_service.id]["networks"] = []

        # Migrations if it's neccesary
        for service in changed_services:
            for vnf in service.VNFS:
                hypervisor, vm_id = self.get_physical_hypervisor_of_VNF(vnf.id)
                if vnf.mapped_to != hypervisor:
                    self.migrate(vm_id, vnf)

        # Create network for NS
        net = "192.168.{}.{}/24".format(str(net_iter/254), str(net_iter%254))
        print("CREATE NETWORK FOR NS:", end='')
        network_id = self.set_network(str(new_service.id), net)
        print(" DONE")

        self.services[new_service.id]["networks"].append(network_id)

        flavor_num = 0
        sfc_queue_item = {new_service.id: {'deploy_start': start_deploy_timestamp, 'items': []}}
        for vm in new_service.VNFS:
            print("CREATE VNF: " + str(vm.id))
            # Get flavors
            flavor, flavor_num = self.get_or_set_flavor(vm, flavor_num)
            # Create ports for VNF
            p1 = self.create_port(network_id)

            self.services[new_service.id]["ports"].append(p1["id"])

            # Create instance
            zone = self.get_avail_zone_from_hypervisor(vm.mapped_to)
            if zone is None:
                zone = self.get_avail_zone_from_fog(next(x.id for x in fogs if vm.mapped_to in x.compute_nodes))
            response = self.create_instance(image=CIRROS_ID, ports=[p1['id']],
                                            name=str(vm.id), availability_zone=str(zone), flavor=flavor)
            if response.status_code == 500:
                response = self.retry(vm, p1, flavor, zone)
            instance = ast.literal_eval(response.text)
            instance_id = instance["server"]["id"]

            sfc_queue_item[new_service.id]['items'].append({'p1': p1, 'vm': vm, 'instance_id': instance_id})
            print("VNF is building")
            print("VNF is ACTIVE.")
        self.sfc_queue.append(sfc_queue_item)
        return True

    def deploy_as_stack(self, new_service, net_iter, changed_services, fogs):
        """

        :return:
        """
        start_deploy_timestamp = time.time()
        print("*********************************************************************************")
        print("START DEPLOY SERVICE: " + str(new_service.id))

        if new_service.id not in self.services:
            self.services[new_service.id] = {}
            self.services[new_service.id]["instances"] = []

        # FIXME
        try:
            # Migrations if it's neccesary
            for service in changed_services:
                for vnf in service.VNFS:
                    hypervisor, vm_id = self.get_physical_hypervisor_of_VNF(vnf.id)
                    if vnf.mapped_to != hypervisor:
                        self.migrate(vm_id, vnf)
        except Exception as e:
            print(e.message)

        with open('heat_templates/template', 'r') as f:
            default_template = f.read().split('\n')

        already_placed_vnf_ids = [y for x in self.services.keys() for y in self.services[x]['instances']]
        if len(new_service.VNFS) > 1 or (len(new_service.VNFS) == 1 and
                                         new_service.VNFS[0].id not in already_placed_vnf_ids):
            self.deploy_new_stack(default_template, new_service, fogs, start_deploy_timestamp,
                                  already_placed_vnf_ids)

    def deploy_new_stack(self, default_template, new_service, fogs, start_deploy_timestamp,
                         already_placed_vnf_ids):
        port_template = self.get_object_template_from_default_template(default_template, type='OS::Neutron::Port',
                                                                       end='# port_end')
        port_pair_template = self.get_object_template_from_default_template(default_template,
                                                                            type='OS::Neutron::PortPair',
                                                                            end='# port_pair_end')
        port_pair_group_template = self.get_object_template_from_default_template(default_template,
                                                                                  type='OS::Neutron::PortPairGroup',
                                                                                  end='# port_pair_group_end')
        port_chain_template = self.get_object_template_from_default_template(default_template,
                                                                             type='OS::Neutron::PortChain',
                                                                             end='# port_chain_end')
        instance_template = self.get_object_template_from_default_template(default_template, type='OS::Nova::Server',
                                                                           end='# instance_end')
        instances = []
        ports = []
        port_pairs = []
        port_pair_groups = []
        flavor_num = 0
        already_placed_ppg_names = []
        for vm in new_service.VNFS:
            if vm.id in already_placed_vnf_ids:
                already_placed_ppg_names.append(str(vm.id)+'_PPG')
            else:
                self.services[new_service.id]["instances"].append(vm.id)
                # Get flavor
                flavor, flavor_num = self.get_or_set_flavor(vm, flavor_num)

                # Create port for VNF
                port = copy.deepcopy(port_template)
                self.change_value_in_template(port, 'port', vm.id+'_PORT')
                self.add_value_in_template(port, 'name:', ' '+vm.id+'_PORT')

                self.add_value_in_template(port, 'network:', ' '+self.network_id)

                ports.append(port)

                # Create instance
                zone = self.get_avail_zone_from_hypervisor(vm.mapped_to)
                if zone is None:
                    zone = self.get_avail_zone_from_fog(next(x.id for x in fogs if vm.mapped_to in x.compute_nodes))
                instance = copy.deepcopy(instance_template)
                self.change_value_in_template(instance, 'instance', vm.id)
                self.add_value_in_template(instance, 'name:', ' '+vm.id)
                self.add_value_in_template(instance, 'flavor:', ' '+flavor.id)
                self.add_value_in_template(instance, 'availability_zone:', ' '+zone)
                self.add_value_in_template(instance, 'port:', ' { get_resource: '+vm.id+'_PORT'+' }')
                self.add_value_in_template(instance, 'image:', ' '+CIRROS_ID)
                self.add_value_in_template(instance, 'depends_on:', ' '+vm.id + '_PORT')
                instances.append(instance)

                # Create PortPair for VNF
                port_pair = copy.deepcopy(port_pair_template)
                self.change_value_in_template(port_pair, 'port_pair', vm.id+'_PP')
                self.add_value_in_template(port_pair, 'name:', ' '+vm.id+'_PP')
                self.add_value_in_template(port_pair, 'ingress:', ' { get_resource: '+vm.id+'_PORT'+' }')
                self.add_value_in_template(port_pair, 'egress:', ' { get_resource: '+vm.id+'_PORT'+' }')
                self.add_value_in_template(port_pair, 'depends_on:', ' ' + vm.id)
                port_pairs.append(port_pair)

                # Create PortPairGroup for VNF
                port_pair_group = copy.deepcopy(port_pair_group_template)
                self.change_value_in_template(port_pair_group, 'port_pair_group', vm.id + '_PPG')
                self.add_value_in_template(port_pair_group, 'name:', ' '+vm.id + '_PPG')
                self.add_value_in_template(port_pair_group, 'port_pairs:', ' '+'[{}]'.format(' { get_resource: '+vm.id +
                                                                                             '_PP'+' }'))
                self.add_value_in_template(port_pair_group, 'depends_on:', ' '+vm.id + '_PP')
                port_pair_groups.append(port_pair_group)

        self.change_value_in_template(port_chain_template, 'port_chain', new_service.id+'_PC')
        self.add_value_in_template(port_chain_template, 'name:', ' '+new_service.id+'_PC')
        ppg_names = [' { get_resource: '+str(y.split(':')[-1])+' }' for x in port_pair_groups
                     for y in x if 'name:' in y]
        ppg_depends = [str(y.split(':')[-1]) for x in port_pair_groups for y in x if 'name:' in y]
        self.add_value_in_template(port_chain_template, 'port_pair_groups:', ' ' +
                                   str(ppg_names+already_placed_ppg_names).replace('\'', ''))
        self.add_value_in_template(port_chain_template, 'depends_on:', ' '+str(ppg_depends).replace('\'', ''))

        service_template = ['heat_template_version: pike', '\n', 'resources:']
        for p in ports:
            service_template += p
            service_template.append('')
        for i in instances:
            service_template += i
            service_template.append('')
        for pp in port_pairs:
            service_template += pp
            service_template.append('')
        for ppg in port_pair_groups:
            service_template += ppg
            service_template.append('')
        service_template += port_chain_template
        with open('heat_templates/{}.yaml'.format(str(new_service.id)), 'w') as tf:
            tf.write('\n'.join(service_template))

        stack_name = 'service_'+new_service.id.replace('-', '_')
        callback_time = time.time()
        try:
            self.create_stack(stack_name, 'heat_templates/{}.yaml'.format(str(new_service.id)))
            self.sfc_queue.append({new_service.id: {'stack_name': stack_name, 'deploy_start': start_deploy_timestamp,
                                                    'callback_time': callback_time}})
        except Exception as e:
            print(e.message)
        return True

    @staticmethod
    def get_object_template_from_default_template(default_template, type, end):
        return default_template[default_template.index(
            next(x for x in default_template if type in x))-1:default_template.index(
            next(x for x in default_template if end in x))]

    @staticmethod
    def add_value_in_template(template, line, value):
        for i in range(len(template)):
            if line in template[i]:
                template[i] += value
        return template

    @staticmethod
    def change_value_in_template(template, line, value):
        for i in range(len(template)):
            if line in template[i]:
                template[i] = template[i].replace(line, value)
        return template

    def create_sfc(self, sfc_queue_item):
        port_pair_groups = []
        new_service_id = sfc_queue_item.keys()[0]
        for item in sfc_queue_item[new_service_id]['items']:
            vm = item['vm']
            p1 = item['p1']
            instance_id = item['instance_id']
            while not self.neutron.list_ports(id=p1['id'])['ports'][0]['binding:host_id']:
                pass

            pp = self.create_port_pair(p1["id"], str(vm.id) + "_VNF_PP")

            self.services[new_service_id]["instances"].append(instance_id)
            self.services[new_service_id]["pps"].append(pp["port_pair"]["id"])

            pg = self.create_port_pair_group(pp, 'GROUPZ')
            port_pair_groups.append(pg)
            self.services[new_service_id]["pgs"].append(pg['port_pair_group']['id'])
        pc = self.create_port_chain(port_pair_groups, new_service_id)
        self.services[new_service_id]["pcs"].append(pc['port_chain']['id'])
        sfc_queue_item[new_service_id]['deploy_end'] = time.time()

        print(new_service_id+" SERVICE IS CREATED")
        print("*********************************************************************************")

    def watch_sfc_queue(self, result_file):
        done_list = []
        while not self.finished or len(self.sfc_queue) > 0:
            if len(self.sfc_queue) > 0:
                sfc_queue_item = self.sfc_queue.pop(0)
                self.create_sfc(sfc_queue_item)
                done_list.append(sfc_queue_item)
        self.write_stat(done_list, result_file)

    def watch_stacks(self, result_file):
        done_list = []
        done_stacks = []
        timeout = 30
        while not self.finished or len(self.sfc_queue) > 0:
            if len(self.sfc_queue) > 0:
                for stack in self.heat.stacks.list():
                    if stack.stack_name in [x[x.keys()[0]]['stack_name'] for x in self.sfc_queue] and \
                            stack.stack_name not in done_stacks and 'COMPLETE' in stack.stack_status:
                        sfc_queue_item = self.sfc_queue.pop(self.sfc_queue.index(next(x for x in self.sfc_queue if
                                                                                      x[x.keys()[0]]['stack_name'] ==
                                                                                      stack.stack_name)))
                        sfc_queue_item[sfc_queue_item.keys()[0]]['deploy_end'] = time.time()
                        done_list.append(sfc_queue_item)
                        done_stacks.append(stack.stack_name)
                    if 'FAIL' in stack.stack_status:
                        stack_file_name = '-'.join(stack.stack_name.split('_')[1:]).replace('_', '-')
                        with open('heat_templates/{}.yaml'.format(stack_file_name)) as t_file:
                            template = t_file.read()
                        self.heat.stacks.update(stack.stack_name, template=template)
                time.sleep(0.5)
                if self.finished:
                    timeout -= 1
                if timeout <= 0:
                    break
        self.write_stat(done_list, result_file)

    @staticmethod
    def write_stat(done_list, result_file):
        sum_deploy = 0
        overall_end = str(time.time())
        with open(result_file, 'r') as f:
            lines = f.read().split('\n')

        for done_item in done_list:
            service_id = done_item.keys()[0]
            line_index = next(lines.index(l) for l in lines if 'service_id: ' in l and l.split(' ')[-1] ==
                              str(service_id))
            start_time = done_item[service_id]['deploy_start']
            end_time = done_item[service_id]['deploy_end']
            callback_time = done_item[service_id]['callback_time']
            lines.insert(line_index + 1, "start_deploy_timestamp: " + str(start_time))

            lines.insert(line_index + 2, "end_successed_deploy_timestamp: " + str(end_time))
            sum_deploy += (end_time - start_time)

            lines.insert(line_index + 3, "end_successed_timestamp: " + str(end_time))
            lines.insert(line_index + 4, "successful_callback_time: " + str(callback_time))
            start_timestamp = next(float(x.split(' ')[-1]) for x in lines[line_index:line_index+10]
                                   if 'start_timestamp:' in x)

            lines.insert(line_index + 1, "full_duration: " + str(end_time - start_timestamp))
        lines.append("TOTAL DEPLOY TIME: " + str(sum_deploy))
        lines.append("END MAPPING SERVICES: " + overall_end)
        with open(result_file, 'w') as f:
            f.write('\n'.join(lines))

    def get_or_set_flavor(self, vm, flavor_num):
        flavors = self.flavors
        flavor = None
        for fl in flavors:
            if vm.required_CPU == fl.vcpus and vm.required_RAM == fl.ram and vm.required_STORAGE == fl.disk:
                print("    Used flavor: " + str(fl))
                flavor = fl
                break
        # Generate new flavor if it's neccesary
        if flavor is None:
            print("    CREATE FLAVOR " + str(vm.service_graph) + "_FLAVOR_" + str(flavor_num))
            flavor = self.set_flavor(str(vm.service_graph) + "_FLAVOR_" + str(flavor_num), vm.required_RAM,
                                     vm.required_CPU, vm.required_STORAGE)
            flavor_num += 1
            print("    DONE")
        return flavor, flavor_num

    def create_stack(self, stack_name, stack_file_path='heat_templates/template', parameters=None):
        with open(stack_file_path) as t_file:
            template = t_file.read()

        if parameters:
            stack = self.heat.stacks.create(stack_name=stack_name, template=template, parameters=parameters)
        else:
            stack = self.heat.stacks.create(stack_name=stack_name, template=template)
        return stack

    def retry(self, vm, p1, flavor, zone):
        try_num = 0
        print("    First VNF creation failed. Try again...")
        while try_num < 5:
            time.sleep(1)

            response = self.create_instance(image=CIRROS_ID, ports=[p1['id']],
                                            name=str(vm.id), availability_zone=str(zone),
                                            flavor=flavor)
            if response.status_code != 500:
                break
            print("    VNF creation failed. Try again...")
            try_num += 1
        if try_num == 5:
            raise RuntimeError(response.text)
        return response

    def watch_vnf_creation(self, instance_id, vm, p1, zone, flavor):
        timout = 0
        while self.get_instance_status(instance_id) != "ACTIVE":
            time.sleep(1)
            timout += 1
            print(".", end='')
            if timout == 30:
                print("\n    VNF creation timeout (30 sec)")
                print("    DELETE VNF and try creation again.", end='')
                self.nova.servers.delete(instance_id)
                response = self.create_instance(image='cirros', ports=[p1['id']],
                                                name=str(vm.id), availability_zone=str(zone),
                                                flavor=flavor)
                instance = ast.literal_eval(response.text)
                instance_id = instance["server"]["id"]

    def migrate(self, vm_id, vnf, retry=1):
        """

        :return:
        """
        try:
            self.log("START MIGRATION: {} --> {}".format(vnf.id, vnf.mapped_to), 'INFO')
            self.nova.servers.live_migrate(vm_id, vnf.mapped_to, True, False)
            sys.stdout.write('\nDONE\n')
        except Exception as e:
            print(e.message)
            if retry < 3:
                retry += 1
                time.sleep(retry)
                self.migrate(vm_id, vnf, retry)

    @staticmethod
    def delete_rows_sql(database, table, port_chain_id=None):
        print(table)
        if not port_chain_id:
            sql = 'DELETE FROM {};'.format(table)
        else:
            sql = "DELETE FROM {} WHERE id = '{}';".format(table, port_chain_id)
        subprocess.call('ssh ubuntu@controller \'sudo mysql -u root --password=openstack {} -e "{};"\''.format(database,
                                                                                                               sql),
                        shell=True)

    def clear(self):
        # Deleting from OpenStack
        # for pc in self.neutron.list_port_chains()['port_chains']:
        #     self.neutron.delete_port_chain(pc['id'])
        self.delete_rows_sql(database='neutron', table='sfc_port_chains')

        # for pg in self.neutron.list_port_pair_groups()['port_pair_groups']:
        #     self.neutron.delete_port_pair_group(pg['id'])
        self.delete_rows_sql(database='neutron', table='sfc_port_pair_groups')

        # for pp in self.neutron.list_port_pairs()['port_pairs']:
        #     self.neutron.delete_port_pair(pp['id'])
        self.delete_rows_sql(database='neutron', table='sfc_port_pairs')

        # for instance in self.nova.servers.list():
        #     result = self.nova.servers.delete(instance)
        self.delete_rows_sql(database='nova', table='instance_faults')
        self.delete_rows_sql(database='nova', table='instance_id_mappings')
        self.delete_rows_sql(database='nova', table='instance_info_caches')
        self.delete_rows_sql(database='nova', table='instance_system_metadata')
        self.delete_rows_sql(database='nova', table='security_group_instance_association')
        self.delete_rows_sql(database='nova', table='block_device_mapping')
        self.delete_rows_sql(database='nova', table='fixed_ips')
        self.delete_rows_sql(database='nova', table='instance_actions_events')
        self.delete_rows_sql(database='nova', table='instance_actions')
        self.delete_rows_sql(database='nova', table='virtual_interfaces')
        self.delete_rows_sql(database='nova', table='instance_extra')
        self.delete_rows_sql(database='nova', table='instance_metadata')
        self.delete_rows_sql(database='nova', table='migrations')
        self.delete_rows_sql(database='nova', table='instances')
        self.delete_rows_sql(database='nova_api', table='instance_mappings')

        # for port in self.neutron.list_ports()['ports']:
        #     self.neutron.delete_port(port['id'])
        self.delete_rows_sql(database='neutron', table='ports')

        # for network in self.neutron.list_networks()['networks']:
        #     self.neutron.delete_network(network['id'])
        self.delete_rows_sql(database='neutron', table='subnets')
        self.delete_rows_sql(database='neutron', table='networks')
        self.delete_rows_sql(database='neutron', table='ml2_vxlan_allocations')

        # # Deleting from dictionary
        # self.services.pop(service_to_delete)
        #
        # # Saving the modified dictionary to file
        # self.write_services_to_file(self.services)
        self.delete_rows_sql(database='heat', table='event')
        self.delete_rows_sql(database='heat', table='stack')
        self.delete_rows_sql(database='heat', table='raw_template')
        self.delete_rows_sql(database='heat', table='raw_template_files')
        self.delete_rows_sql(database='heat', table='resource')
        self.delete_rows_sql(database='heat', table='resource_data')
        self.delete_rows_sql(database='heat', table='resource_properties_data')


if __name__ == '__main__':
    os = OpenStack()

