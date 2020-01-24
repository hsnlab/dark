REQUIREMENTS
=========================================
```bash
sudo pip install -r requirements.txt
sudo pip install vmtp 
sudo apt-get install python-matplotlib
```
Install VMTP: https://vmtp.readthedocs.io/en/latest/quickstart_pip.html

For the first time:

1, AZ setup of OpenStack
2, set VMTP conf file

VMTP version: 2.5.0

How to start a DARK mapping simulation
=========================================

The process is the following:
    1. Generate a resource topology
    2. Generate service chain requests
    3. Fingers crossed and start the simulation :)

How to generate a resource topology
-----------------------------------------
Example command:
```bash
python3 topology_gen_random.py
```

How to generate service chain requests
-----------------------------------------

Example command:
```bash
python3 request_gen.py -r topology.json
 ```

How to start the simulation
------------------------------
You need to use simulator.py python program. The resource topology, delay matrix and a requests json files must be generated previously.

For more information:
    `python simulator.py -h`

Example command:
```bash
python simulator.py -l test.log -r log/ostopo.json -dm log/delay_mtx.json -s log/requests/test2.json
```
    
    
Nova fake driver fix
-----------------------
Sfc port chain delete error fix:

python2.7/site-packages/networking_sfc/services/sfc/driver_manager.py
```python
def _call_drivers(self,method_name,context,raise_orig_exc=False):
    pass
```